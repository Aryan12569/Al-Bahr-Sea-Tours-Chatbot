from flask import Flask, request, jsonify
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
import requests
import logging
import time
import re
import random
from apscheduler.schedulers.background import BackgroundScheduler

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ==============================
# CONFIGURATION - AL BAHR SEA TOURS
# ==============================
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "ALBAHRB0T")
WHATSAPP_TOKEN = os.environ.get("ACCESS_TOKEN")
SHEET_NAME = os.environ.get("SHEET_NAME", "Al Bahr Bot Leads")
WHATSAPP_PHONE_ID = os.environ.get("PHONE_NUMBER_ID", "797371456799734")
ADMIN_NUMBERS = os.environ.get("ADMIN_NUMBERS", "").split(",")

# Validate required environment variables
missing_vars = []
if not WHATSAPP_TOKEN:
    missing_vars.append("ACCESS_TOKEN")
if not WHATSAPP_PHONE_ID:
    missing_vars.append("PHONE_NUMBER_ID")
if not os.environ.get("GOOGLE_CREDS_JSON"):
    missing_vars.append("GOOGLE_CREDS_JSON")

if missing_vars:
    logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")

# Google Sheets setup
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = json.loads(os.environ["GOOGLE_CREDS_JSON"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1
    logger.info("✅ Google Sheets initialized successfully")
except Exception as e:
    logger.error(f"❌ Google Sheets initialization failed: {str(e)}")
    sheet = None

# Initialize scheduler for reminders
scheduler = BackgroundScheduler()
scheduler.start()

# Simple session management
booking_sessions = {}
inquiry_sessions = {}

# Tour capacity configuration
TOUR_CAPACITY = {
    "Dolphin Watching": 8,
    "Snorkeling": 6,
    "Dhow Cruise": 10,
    "Fishing Trip": 4
}

# ==============================
# ENHANCED HELPER FUNCTIONS
# ==============================

def add_lead_to_sheet(name, contact, intent, whatsapp_id, tour_type="Not specified", booking_date="Not specified", booking_time="Not specified", people_count="Not specified", questions="", status="New"):
    """Add user entry to Google Sheet with standardized date format"""
    try:
        # Standardize date format to DD/MM/YY
        if booking_date != "Not specified":
            booking_date = standardize_date_format(booking_date)
        
        # Standardize people count to numbers only
        if people_count != "Not specified":
            people_count = extract_number_from_people_count(people_count)
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
        sheet.append_row([
            timestamp, name, contact, whatsapp_id, intent, tour_type, 
            booking_date, booking_time, people_count, questions, status
        ])
        logger.info(f"✅ Added lead to sheet: {name}, {contact}, {intent}, People: {people_count}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to add lead to sheet: {str(e)}")
        return False

def extract_number_from_people_count(people_count):
    """Extract just the number from people count (e.g., '6 people' -> '6')"""
    if isinstance(people_count, str):
        # Extract digits only
        numbers = re.findall(r'\d+', people_count)
        if numbers:
            return numbers[0]
    return str(people_count)

def standardize_date_format(date_str):
    """Convert various date formats to DD/MM/YY format"""
    try:
        # If it's already in DD/MM/YY or similar format, return as is
        if re.match(r'\d{1,2}/\d{1,2}/\d{2,4}', date_str):
            parts = date_str.split('/')
            if len(parts) == 3:
                day, month, year = parts
                # Convert to 2-digit year
                if len(year) == 4:
                    year = year[2:]
                return f"{day.zfill(2)}/{month.zfill(2)}/{year}"
            return date_str
        
        # Parse the date from various formats
        date_formats = [
            '%Y-%m-%d', '%d-%m-%Y', '%m-%d-%Y',
            '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d',
            '%B %d, %Y', '%d %B %Y', '%b %d, %Y',
            '%d-%b-%Y', '%d/%b/%Y'
        ]
        
        for fmt in date_formats:
            try:
                parsed_date = datetime.datetime.strptime(date_str, fmt)
                # Format as DD/MM/YY
                return parsed_date.strftime('%d/%m/%y')
            except ValueError:
                continue
        
        # Handle relative dates
        today = datetime.datetime.now()
        if date_str.lower() == 'tomorrow':
            return (today + datetime.timedelta(days=1)).strftime('%d/%m/%y')
        elif date_str.lower().startswith('next '):
            # Simple handling for "next Monday", etc.
            return (today + datetime.timedelta(days=7)).strftime('%d/%m/%y')
        
        # If no format works, return original
        return date_str
    except Exception as e:
        logger.error(f"Error standardizing date format: {str(e)}")
        return date_str

def send_whatsapp_message(to, message, interactive_data=None):
    """Send WhatsApp message via Meta API"""
    try:
        clean_to = clean_oman_number(to)
        if not clean_to:
            logger.error(f"❌ Invalid phone number: {to}")
            return False
        
        url = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        
        if interactive_data:
            payload = {
                "messaging_product": "whatsapp",
                "to": clean_to,
                "type": "interactive",
                "interactive": interactive_data
            }
        else:
            payload = {
                "messaging_product": "whatsapp",
                "to": clean_to,
                "type": "text",
                "text": {
                    "body": message
                }
            }

        logger.info(f"📤 Sending WhatsApp message to {clean_to}")
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response_data = response.json()
        
        if response.status_code == 200:
            logger.info(f"✅ WhatsApp message sent successfully to {clean_to}")
            return True
        else:
            error_message = response_data.get('error', {}).get('message', 'Unknown error')
            logger.error(f"❌ WhatsApp API error {response.status_code}: {error_message}")
            return False
        
    except Exception as e:
        logger.error(f"🚨 Failed to send WhatsApp message: {str(e)}")
        return False

def clean_oman_number(number):
    """Clean and validate Oman phone numbers"""
    if not number:
        return None
    
    clean_number = ''.join(filter(str.isdigit, str(number)))
    
    if not clean_number:
        return None
        
    if len(clean_number) == 8 and clean_number.startswith(('9', '7', '8')):
        return '968' + clean_number
    elif len(clean_number) == 11 and clean_number.startswith('968'):
        return clean_number
    elif len(clean_number) == 12 and clean_number.startswith('968'):
        return clean_number
    
    return None

def send_welcome_message(to):
    """Send initial welcome message"""
    interactive_data = {
        "type": "button",
        "body": {
            "text": "🌊 *Al Bahr Sea Tours* 🐬\n\nWelcome to Oman's premier sea adventure company! 🚤\n\nDiscover breathtaking marine life, crystal clear waters, and unforgettable experiences. 🌅\n\nReady to explore? 🗺️"
        },
        "action": {
            "buttons": [
                {
                    "type": "reply",
                    "reply": {
                        "id": "view_options",
                        "title": "🌊 View Tours"
                    }
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def send_main_options_list(to):
    """Send ALL options in one list"""
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "🌊 Al Bahr Sea Tours"
        },
        "body": {
            "text": "Choose your sea adventure: 🗺️"
        },
        "action": {
            "button": "🌊 View Tours",
            "sections": [
                {
                    "title": "🚤 Popular Tours",
                    "rows": [
                        {
                            "id": "dolphin_tour",
                            "title": "🐬 Dolphin Watching",
                            "description": "Swim with dolphins in their natural habitat"
                        },
                        {
                            "id": "snorkeling", 
                            "title": "🤿 Snorkeling",
                            "description": "Explore vibrant coral reefs and marine life"
                        },
                        {
                            "id": "dhow_cruise",
                            "title": "⛵ Dhow Cruise", 
                            "description": "Traditional Omani boat sunset experience"
                        },
                        {
                            "id": "fishing",
                            "title": "🎣 Fishing Trip",
                            "description": "Deep sea fishing adventure"
                        }
                    ]
                },
                {
                    "title": "ℹ️ Information & Booking",
                    "rows": [
                        {
                            "id": "pricing",
                            "title": "💰 Pricing",
                            "description": "Tour prices and packages"
                        },
                        {
                            "id": "location",
                            "title": "📍 Location",
                            "description": "Our marina address and directions"
                        },
                        {
                            "id": "schedule",
                            "title": "🕒 Schedule",
                            "description": "Tour timings and availability"
                        },
                        {
                            "id": "contact",
                            "title": "📞 Contact",
                            "description": "Get in touch with our team"
                        },
                        {
                            "id": "book_now",
                            "title": "📅 Book Now", 
                            "description": "Reserve your sea adventure"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def send_booking_options(to):
    """Send booking options"""
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "📅 Book Your Tour"
        },
        "body": {
            "text": "Choose your booking option:"
        },
        "action": {
            "button": "📅 Book Now",
            "sections": [
                {
                    "title": "Booking Options",
                    "rows": [
                        {
                            "id": "book_tour",
                            "title": "📝 Book Tour", 
                            "description": "Complete booking immediately"
                        },
                        {
                            "id": "inquire_tour",
                            "title": "💬 Inquire First",
                            "description": "Get more info before booking"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

# ==============================
# CALENDAR INTEGRATION FUNCTIONS
# ==============================

def send_calendar_picker(to, message_text, session_data):
    """Send WhatsApp calendar picker for date selection"""
    try:
        # For now, use clear text instructions with multiple format examples
        send_whatsapp_message(to, 
            f"{message_text}\n\n"
            f"📅 *Please send your preferred date in one of these formats:*\n"
            f"• **DD/MM/YYYY** (e.g., 29/10/2024)\n"
            f"• **DD-MM-YYYY** (e.g., 29-10-2024)\n"
            f"• **October 29, 2024**\n"
            f"• **Tomorrow**\n"
            f"• **Next Friday**\n\n"
            f"We'll automatically convert it to standard format (DD/MM/YY)! 📋")
            
        return True
    except Exception as e:
        logger.error(f"❌ Error sending calendar picker: {str(e)}")
        # Fallback to text method
        send_whatsapp_message(to, 
            f"{message_text}\n\nPlease reply with your preferred date (e.g., 29/10/2024)")
        return False

# ==============================
# ENHANCED INQUIRY FLOW WITH FIXED 5+ PEOPLE HANDLING
# ==============================

def start_enhanced_inquiry_flow(to):
    """Start enhanced inquiry flow with mandatory questions"""
    # Clear any existing sessions for testing
    clear_user_sessions(to)
    
    inquiry_sessions[to] = {
        'step': 'awaiting_tour_interest',
        'flow': 'enhanced_inquiry',
        'answers': {},
        'created_at': time.time()
    }
    
    send_tour_selection_options(to)

def send_tour_selection_options(to):
    """Send tour selection options for inquiry"""
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "🚤 Which Tour Interests You?"
        },
        "body": {
            "text": "Please select your preferred tour:"
        },
        "action": {
            "button": "Select Tour",
            "sections": [
                {
                    "title": "Available Tours",
                    "rows": [
                        {
                            "id": f"inquire_dolphin|{to}",
                            "title": "🐬 Dolphin Watching",
                            "description": "2 hours • 25 OMR per person"
                        },
                        {
                            "id": f"inquire_snorkeling|{to}", 
                            "title": "🤿 Snorkeling",
                            "description": "3 hours • 35 OMR per person"
                        },
                        {
                            "id": f"inquire_dhow|{to}",
                            "title": "⛵ Dhow Cruise", 
                            "description": "2 hours • 40 OMR per person"
                        },
                        {
                            "id": f"inquire_fishing|{to}",
                            "title": "🎣 Fishing Trip",
                            "description": "4 hours • 50 OMR per person"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def ask_inquiry_people_count(to, tour_interest):
    """Ask for number of people in inquiry - FIXED 5+ HANDLING"""
    if to in inquiry_sessions:
        inquiry_sessions[to].update({
            'step': 'awaiting_people_count',
            'answers': {'tour_interest': tour_interest}
        })
    
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "👥 Number of People"
        },
        "body": {
            "text": f"How many people for {tour_interest}?"
        },
        "action": {
            "button": "Select Count",
            "sections": [
                {
                    "title": "Group Size",
                    "rows": [
                        {
                            "id": f"inquire_people_1|{to}|{tour_interest}",
                            "title": "👤 1 Person",
                            "description": "Individual inquiry"
                        },
                        {
                            "id": f"inquire_people_2|{to}|{tour_interest}", 
                            "title": "👥 2 People",
                            "description": "Couple or friends"
                        },
                        {
                            "id": f"inquire_people_3|{to}|{tour_interest}",
                            "title": "👨‍👩‍👦 3 People", 
                            "description": "Small group"
                        },
                        {
                            "id": f"inquire_people_4|{to}|{tour_interest}",
                            "title": "👨‍👩‍👧‍👦 4 People",
                            "description": "Family package"
                        },
                        {
                            "id": f"inquire_people_5plus|{to}|{tour_interest}",
                            "title": "👨‍👩‍👧‍👦 5+ People",
                            "description": "Large group (will ask for exact number)"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def ask_inquiry_exact_people_count(to, tour_interest):
    """Ask for exact number when 5+ is selected - FIXED VERSION"""
    if to in inquiry_sessions:
        inquiry_sessions[to].update({
            'step': 'awaiting_exact_people_count',
            'answers': {'tour_interest': tour_interest}
        })
    
    send_whatsapp_message(to,
        "👥 *Exact Number of People*\n\n"
        "Please enter the **exact number** of people in your group:\n\n"
        "🔢 *Examples:*\n"
        "• 5\n"
        "• 6\n" 
        "• 8\n"
        "• 10\n"
        "• 12\n\n"
        "We'll check availability for your exact group size! 🎯")

def ask_inquiry_preferred_date(to, tour_interest, people_count):
    """Ask for preferred date using calendar - FIXED VERSION"""
    if to in inquiry_sessions:
        inquiry_sessions[to].update({
            'step': 'awaiting_preferred_date',
            'answers': {
                'tour_interest': tour_interest,
                'people_count': people_count
            }
        })
    
    # Use calendar picker or clear text instructions
    session_data = {
        'flow': 'inquiry',
        'tour_interest': tour_interest,
        'people_count': people_count
    }
    
    send_calendar_picker(to,
        f"📅 *Preferred Date*\n\n"
        f"Great! {people_count} people for {tour_interest}. 🎯\n\n"
        f"Please select your preferred date:",
        session_data)

def ask_inquiry_questions(to, tour_interest, people_count, preferred_date):
    """Ask if they have any questions (optional)"""
    if to in inquiry_sessions:
        inquiry_sessions[to].update({
            'step': 'awaiting_questions',
            'answers': {
                'tour_interest': tour_interest,
                'people_count': people_count,
                'preferred_date': preferred_date
            }
        })
    
    send_whatsapp_message(to,
        f"❓ *Any Questions?* (Optional)\n\n"
        f"Almost done! Do you have any specific questions about:\n\n"
        f"• The {tour_interest} experience? 🚤\n"
        f"• Safety measures? 🦺\n"
        f"• What to bring? 🎒\n"
        f"• Payment options? 💳\n"
        f"• Anything else? 🤔\n\n"
        f"Type your questions or just send 'No' to complete your inquiry.")

def complete_enhanced_inquiry(to, questions="No questions"):
    """Complete the enhanced inquiry and save to sheet"""
    if to not in inquiry_sessions:
        return
    
    answers = inquiry_sessions[to].get('answers', {})
    
    # Check availability
    tour_interest = answers.get('tour_interest', 'Not specified')
    preferred_date = answers.get('preferred_date', 'Not specified')
    people_count = answers.get('people_count', '1')  # Now stored as number only
    
    is_available, available_slots, capacity = check_tour_availability(
        tour_interest, preferred_date, people_count
    )
    
    # Save to Google Sheets
    success = add_lead_to_sheet(
        name="Inquiry Customer",
        contact=to,
        intent="Custom Inquiry",
        whatsapp_id=to,
        tour_type=tour_interest,
        booking_date=preferred_date,
        booking_time="Not specified",
        people_count=people_count,  # Now just number
        questions=questions,
        status="Inquiry Received"
    )
    
    # Clear the session
    clear_user_sessions(to)
    
    # Send confirmation message with availability
    if is_available:
        availability_msg = f"✅ *Available!* We have {available_slots} slots available for {preferred_date}."
        suggestion = "Ready to book? Just type 'Book Now'! 📅"
    else:
        # Get alternative dates
        alternative_dates = get_next_available_dates(tour_interest, people_count)
        alternative_msg = ""
        if alternative_dates:
            alternative_msg = f"\n\n💡 *Alternative Available Dates:*\n" + "\n".join([f"• {date}" for date in alternative_dates])
        
        availability_msg = f"⚠️ *Limited Availability* Only {available_slots} slots available for {preferred_date}. Capacity: {capacity}{alternative_msg}"
        suggestion = "Please choose another date or contact us for special arrangements. 📞"
    
    send_whatsapp_message(to,
        f"🎉 *Inquiry Complete!* 📝\n\n"
        f"Thank you for your detailed inquiry! Here's what we have:\n\n"
        f"📋 *Your Inquiry Details:*\n"
        f"🚤 Tour: {tour_interest}\n"
        f"👥 People: {people_count}\n"
        f"📅 Preferred Date: {preferred_date}\n"
        f"❓ Questions: {questions}\n\n"
        f"{availability_msg}\n\n"
        f"{suggestion}")

# ==============================
# ENHANCED BOOKING FLOW WITH CALENDAR
# ==============================

def start_booking_flow(to):
    """Start the booking flow by asking for name"""
    clear_user_sessions(to)
    
    booking_sessions[to] = {
        'step': 'awaiting_name',
        'flow': 'booking',
        'created_at': time.time()
    }
    
    send_whatsapp_message(to, 
        "📝 *Let's Book Your Tour!* 🎫\n\n"
        "I'll help you book your sea adventure. 🌊\n\n"
        "First, please send me your:\n\n"
        "👤 *Full Name*\n\n"
        "*Example:*\n"
        "Ahmed Al Harthy")

def ask_for_contact(to, name):
    """Ask for contact after getting name"""
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_contact',
            'name': name
        })
    
    send_whatsapp_message(to, 
        f"Perfect, {name}! 👋\n\n"
        "Now please send me your:\n\n"
        "📞 *Phone Number*\n\n"
        "*Example:*\n"
        "91234567")

def ask_for_tour_type(to, name, contact):
    """Ask for tour type using interactive list"""
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_tour_type',
            'name': name,
            'contact': contact
        })
    
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "🚤 Choose Your Tour"
        },
        "body": {
            "text": f"Great {name}! Which tour would you like to book?"
        },
        "action": {
            "button": "Select Tour",
            "sections": [
                {
                    "title": "Available Tours",
                    "rows": [
                        {
                            "id": f"book_dolphin|{name}|{contact}",
                            "title": "🐬 Dolphin Watching",
                            "description": "2 hours • 25 OMR per person"
                        },
                        {
                            "id": f"book_snorkeling|{name}|{contact}", 
                            "title": "🤿 Snorkeling",
                            "description": "3 hours • 35 OMR per person"
                        },
                        {
                            "id": f"book_dhow|{name}|{contact}",
                            "title": "⛵ Dhow Cruise", 
                            "description": "2 hours • 40 OMR per person"
                        },
                        {
                            "id": f"book_fishing|{name}|{contact}",
                            "title": "🎣 Fishing Trip",
                            "description": "4 hours • 50 OMR per person"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def ask_for_people_count(to, name, contact, tour_type):
    """Ask for number of people - FIXED 5+ HANDLING"""
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_people_count',
            'name': name,
            'contact': contact,
            'tour_type': tour_type
        })
    
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "👥 Number of People"
        },
        "body": {
            "text": f"How many people for the {tour_type}?"
        },
        "action": {
            "button": "Select Count",
            "sections": [
                {
                    "title": "Group Size",
                    "rows": [
                        {
                            "id": f"people_1|{name}|{contact}|{tour_type}",
                            "title": "👤 1 Person",
                            "description": "Individual booking"
                        },
                        {
                            "id": f"people_2|{name}|{contact}|{tour_type}", 
                            "title": "👥 2 People",
                            "description": "Couple or friends"
                        },
                        {
                            "id": f"people_3|{name}|{contact}|{tour_type}",
                            "title": "👨‍👩‍👦 3 People", 
                            "description": "Small group"
                        },
                        {
                            "id": f"people_4|{name}|{contact}|{tour_type}",
                            "title": "👨‍👩‍👧‍👦 4 People",
                            "description": "Family package"
                        },
                        {
                            "id": f"people_5plus|{name}|{contact}|{tour_type}",
                            "title": "👨‍👩‍👧‍👦 5+ People",
                            "description": "Large group (will ask for exact number)"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def ask_for_exact_people_count(to, name, contact, tour_type):
    """Ask for exact number when 5+ is selected - FIXED VERSION"""
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_exact_people_count',
            'name': name,
            'contact': contact,
            'tour_type': tour_type
        })
    
    send_whatsapp_message(to,
        "👥 *Exact Number of People*\n\n"
        "Please enter the **exact number** of people in your group:\n\n"
        "🔢 *Examples:*\n"
        "• 5\n"
        "• 6\n" 
        "• 8\n"
        "• 10\n"
        "• 12\n\n"
        "We'll check availability for your exact group size! 🎯")

def ask_for_date(to, name, contact, tour_type, people_count):
    """Ask for preferred date using calendar - FIXED VERSION"""
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_date',
            'name': name,
            'contact': contact,
            'tour_type': tour_type,
            'people_count': people_count
        })
    
    # Use calendar picker or clear text instructions
    session_data = {
        'flow': 'booking',
        'name': name,
        'contact': contact,
        'tour_type': tour_type,
        'people_count': people_count
    }
    
    send_calendar_picker(to,
        f"📅 *Preferred Date*\n\n"
        f"Great choice! {people_count} people for {tour_type}. 🎯\n\n"
        f"Please select your preferred date:",
        session_data)

def ask_for_time(to, name, contact, tour_type, people_count, booking_date):
    """Ask for preferred time"""
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_time',
            'name': name,
            'contact': contact,
            'tour_type': tour_type,
            'people_count': people_count,
            'booking_date': booking_date
        })
    
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "🕒 Preferred Time"
        },
        "body": {
            "text": f"Perfect! {booking_date} for {tour_type}.\n\nChoose your preferred time:"
        },
        "action": {
            "button": "Select Time",
            "sections": [
                {
                    "title": "Morning Sessions",
                    "rows": [
                        {
                            "id": f"time_8am|{name}|{contact}|{tour_type}|{people_count}|{booking_date}",
                            "title": "🌅 8:00 AM",
                            "description": "Early morning adventure"
                        },
                        {
                            "id": f"time_9am|{name}|{contact}|{tour_type}|{people_count}|{booking_date}", 
                            "title": "☀️ 9:00 AM",
                            "description": "Morning session"
                        },
                        {
                            "id": f"time_10am|{name}|{contact}|{tour_type}|{people_count}|{booking_date}",
                            "title": "🌞 10:00 AM", 
                            "description": "Late morning"
                        }
                    ]
                },
                {
                    "title": "Afternoon Sessions",
                    "rows": [
                        {
                            "id": f"time_2pm|{name}|{contact}|{tour_type}|{people_count}|{booking_date}",
                            "title": "🌇 2:00 PM",
                            "description": "Afternoon adventure"
                        },
                        {
                            "id": f"time_4pm|{name}|{contact}|{tour_type}|{people_count}|{booking_date}",
                            "title": "🌅 4:00 PM",
                            "description": "Late afternoon"
                        },
                        {
                            "id": f"time_6pm|{name}|{contact}|{tour_type}|{people_count}|{booking_date}",
                            "title": "🌆 6:00 PM",
                            "description": "Evening session"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def complete_booking(to, name, contact, tour_type, people_count, booking_date, booking_time):
    """Complete the booking with enhanced availability checking"""
    # Check final availability
    is_available, available_slots, capacity = check_tour_availability(
        tour_type, booking_date, people_count
    )
    
    if not is_available:
        # Suggest alternative dates
        alternative_dates = get_next_available_dates(tour_type, people_count)
        
        alternative_msg = ""
        if alternative_dates:
            alternative_msg = f"\n\n💡 *Alternative Available Dates:*\n" + "\n".join([f"• {date}" for date in alternative_dates])
        
        send_whatsapp_message(to,
            f"⚠️ *Booking Conflict* ❌\n\n"
            f"Sorry {name}, the {tour_type} on {booking_date} is fully booked. 😔\n"
            f"Only {available_slots} slots available (needed: {people_count}).\n"
            f"{alternative_msg}\n\n"
            f"Please choose another date or contact us for special arrangements. 📞")
        
        # Restart the date selection process
        ask_for_date(to, name, contact, tour_type, people_count)
        return
    
    # Save to Google Sheets
    success = add_lead_to_sheet(
        name=name,
        contact=contact,
        intent="Book Tour",
        whatsapp_id=to,
        tour_type=tour_type,
        booking_date=booking_date,
        booking_time=booking_time,
        people_count=people_count,
        questions="",
        status="Confirmed"
    )
    
    # Schedule reminder
    schedule_reminder(to, name, tour_type, booking_date, booking_time)
    
    # Clear the session
    clear_user_sessions(to)
    
    # Send confirmation message
    if success:
        send_whatsapp_message(to,
            f"🎉 *Booking Confirmed!* ✅\n\n"
            f"Thank you {name}! Your tour has been booked successfully. 🐬\n\n"
            f"📋 *Booking Details:*\n"
            f"👤 Name: {name}\n"
            f"📞 Contact: {contact}\n"
            f"🚤 Tour: {tour_type}\n"
            f"👥 People: {people_count}\n"
            f"📅 Date: {booking_date}\n"
            f"🕒 Time: {booking_time}\n\n"
            f"💰 *Total: {calculate_price(tour_type, people_count)} OMR*\n\n"
            f"📲 *You'll receive a reminder 24 hours before your tour.*\n"
            f"Our team will contact you within 1 hour to confirm details. ⏰\n\n"
            f"Get ready for an amazing sea adventure! 🌊")

# ==============================
# AVAILABILITY CHECKING SYSTEM
# ==============================

def check_tour_availability(tour_type, preferred_date, people_count):
    """Check if tour has available slots with standardized date format"""
    try:
        # Convert people_count to integer
        try:
            people_int = int(extract_number_from_people_count(people_count))
        except:
            people_int = 1
        
        # Standardize the date format for comparison
        standardized_date = standardize_date_format(preferred_date)
        
        # Get all bookings for this tour and date
        all_records = sheet.get_all_records()
        booked_count = 0
        
        for record in all_records:
            record_tour = str(record.get('Tour Type', '')).strip()
            record_date = str(record.get('Booking Date', '')).strip()
            record_status = str(record.get('Status', '')).strip().lower()
            
            # Standardize the record date for comparison
            standardized_record_date = standardize_date_format(record_date)
            
            if (record_tour == tour_type and 
                standardized_record_date == standardized_date and 
                record_status in ['confirmed', 'booked', 'new']):
                
                try:
                    record_people = int(extract_number_from_people_count(record.get('People Count', '1')))
                    booked_count += record_people
                except:
                    booked_count += 1
        
        capacity = TOUR_CAPACITY.get(tour_type, 10)
        available = capacity - booked_count
        
        logger.info(f"📊 Availability check: {tour_type} on {standardized_date} - Booked: {booked_count}, Capacity: {capacity}, Available: {available}")
        
        return available >= people_int, available, capacity
        
    except Exception as e:
        logger.error(f"❌ Error checking tour availability: {str(e)}")
        return True, 0, TOUR_CAPACITY.get(tour_type, 10)

def get_next_available_dates(tour_type, people_count, days_to_check=7):
    """Get next available dates for a tour"""
    try:
        available_dates = []
        today = datetime.datetime.now().date()
        
        for i in range(1, days_to_check + 1):
            check_date = today + datetime.timedelta(days=i)
            date_str = check_date.strftime('%d/%m/%y')  # Standardized format
            
            is_available, available_slots, capacity = check_tour_availability(
                tour_type, date_str, people_count
            )
            
            if is_available and available_slots >= int(extract_number_from_people_count(people_count)):
                available_dates.append(check_date.strftime('%d/%m/%y'))
                
            if len(available_dates) >= 3:
                break
                
        return available_dates
    except Exception as e:
        logger.error(f"Error getting available dates: {str(e)}")
        return []

# ==============================
# SESSION MANAGEMENT FOR TESTING
# ==============================

def clear_user_sessions(phone_number):
    """Clear all sessions for a user - essential for testing"""
    if phone_number in booking_sessions:
        del booking_sessions[phone_number]
        logger.info(f"🧹 Cleared booking session for {phone_number}")
    
    if phone_number in inquiry_sessions:
        del inquiry_sessions[phone_number]
        logger.info(f"🧹 Cleared inquiry session for {phone_number}")

def cleanup_old_sessions():
    """Clean up sessions older than 2 hours"""
    try:
        current_time = time.time()
        expired_time = current_time - 7200  # 2 hours
        
        # Clean booking sessions
        expired_bookings = [phone for phone, session in booking_sessions.items() 
                          if session.get('created_at', 0) < expired_time]
        for phone in expired_bookings:
            del booking_sessions[phone]
        
        # Clean inquiry sessions  
        expired_inquiries = [phone for phone, session in inquiry_sessions.items()
                           if session.get('created_at', 0) < expired_time]
        for phone in expired_inquiries:
            del inquiry_sessions[phone]
            
        if expired_bookings or expired_inquiries:
            logger.info(f"🧹 Cleaned up {len(expired_bookings)} booking and {len(expired_inquiries)} inquiry sessions")
    except Exception as e:
        logger.error(f"Error cleaning up sessions: {str(e)}")

# ==============================
# REMINDER SYSTEM
# ==============================

def schedule_reminder(whatsapp_id, name, tour_type, booking_date, booking_time):
    """Schedule automatic reminder 24 hours before tour"""
    try:
        # Parse booking date from standardized format
        try:
            tour_datetime = datetime.datetime.strptime(booking_date, '%d/%m/%y')
        except:
            # Try other formats if standard format fails
            tour_datetime = datetime.datetime.now() + datetime.timedelta(days=1)
        
        # Set reminder for 24 hours before
        reminder_time = tour_datetime - datetime.timedelta(hours=24)
        
        # If reminder time is in the past, don't schedule
        if reminder_time < datetime.datetime.now():
            logger.info(f"Reminder time for {whatsapp_id} is in the past, not scheduling")
            return
        
        # Schedule the reminder
        scheduler.add_job(
            send_tour_reminder,
            'date',
            run_date=reminder_time,
            args=[whatsapp_id, name, tour_type, booking_date, booking_time],
            id=f"reminder_{whatsapp_id}_{booking_date.replace('/', '_')}"
        )
        
        logger.info(f"✅ Scheduled reminder for {whatsapp_id} on {tour_type} at {booking_date}")
        
    except Exception as e:
        logger.error(f"❌ Error scheduling reminder: {str(e)}")

def send_tour_reminder(whatsapp_id, name, tour_type, booking_date, booking_time):
    """Send tour reminder to customer"""
    reminder_message = (
        f"🔔 *Tour Reminder* 🚤\n\n"
        f"Hello {name}! This is a friendly reminder about your upcoming sea adventure:\n\n"
        f"📋 *Tour Details:*\n"
        f"🚤 Tour: {tour_type}\n"
        f"📅 Date: {booking_date}\n"
        f"🕒 Time: {booking_time}\n\n"
        f"📍 *Location:*\n"
        f"Marina Bandar Al Rowdha, Muscat\n"
        f"https://maps.app.goo.gl/albahrseatours\n\n"
        f"🎒 *What to bring:*\n"
        f"• Sunscreen 🌞\n"
        f"• Sunglasses 😎\n"
        f"• Camera 📸\n"
        f"• Comfortable clothes 👕\n\n"
        f"⏰ *Please arrive 30 minutes before departure*\n"
        f"📞 For questions: +968 24 123456\n\n"
        f"We're excited to see you! 🌊"
    )
    
    success = send_whatsapp_message(whatsapp_id, reminder_message)
    if success:
        logger.info(f"✅ Sent reminder to {whatsapp_id} for {tour_type}")
        update_booking_status(whatsapp_id, booking_date, "Reminder Sent")
    else:
        logger.error(f"❌ Failed to send reminder to {whatsapp_id}")

def update_booking_status(whatsapp_id, tour_date, new_status):
    """Update booking status in Google Sheets"""
    try:
        all_records = sheet.get_all_records()
        for i, record in enumerate(all_records, start=2):
            record_whatsapp_id = str(record.get('WhatsApp ID', '')).strip()
            record_date = str(record.get('Booking Date', '')).strip()
            
            if (record_whatsapp_id == whatsapp_id and 
                record_date == tour_date and 
                record.get('Intent', '').lower() in ['book tour', 'custom inquiry']):
                
                sheet.update_cell(i, 11, new_status)
                logger.info(f"✅ Updated status for {whatsapp_id} on {tour_date} to {new_status}")
                return True
        return False
    except Exception as e:
        logger.error(f"❌ Failed to update booking status: {str(e)}")
        return False

# ==============================
# ADMIN FEATURES
# ==============================

def is_admin_number(phone_number):
    """Check if the number is an admin number"""
    clean_number = clean_oman_number(phone_number)
    return clean_number in [clean_oman_number(num) for num in ADMIN_NUMBERS if num.strip()]

def handle_admin_command(phone_number, text):
    """Handle admin-specific commands"""
    if not is_admin_number(phone_number):
        return False
    
    text_lower = text.lower()
    
    if text_lower.startswith('reminder '):
        trigger_manual_reminder(phone_number, text)
        return True
    elif text_lower in ['stats', 'statistics']:
        send_admin_stats(phone_number)
        return True
    elif text_lower in ['help', 'admin help']:
        send_admin_help(phone_number)
        return True
    
    return False

def trigger_manual_reminder(admin_number, command):
    """Admin function to manually trigger reminders"""
    try:
        parts = command.split()
        if len(parts) < 3:
            send_whatsapp_message(admin_number, 
                "❌ Invalid format. Use: reminder <whatsapp_id> <tour_date>\n"
                "Example: reminder 96891234567 29/10/24")
            return False
        
        whatsapp_id = parts[1]
        tour_date = ' '.join(parts[2:])
        
        # Find booking details
        all_records = sheet.get_all_records()
        booking_found = False
        
        for record in all_records:
            record_whatsapp_id = str(record.get('WhatsApp ID', '')).strip()
            record_date = str(record.get('Booking Date', '')).strip()
            
            if (record_whatsapp_id == whatsapp_id and 
                record_date == tour_date and 
                record.get('Intent', '').lower() in ['book tour', 'custom inquiry']):
                
                send_tour_reminder(
                    whatsapp_id,
                    record.get('Name', 'Customer'),
                    record.get('Tour Type', 'Tour'),
                    tour_date,
                    record.get('Booking Time', 'Not specified')
                )
                
                booking_found = True
                break
        
        if booking_found:
            send_whatsapp_message(admin_number, f"✅ Reminder sent to {whatsapp_id} for {tour_date}")
            return True
        else:
            send_whatsapp_message(admin_number, 
                f"❌ No booking found for {whatsapp_id} on {tour_date}\n"
                f"Check the booking details and try again.")
            return False
            
    except Exception as e:
        logger.error(f"Error triggering manual reminder: {str(e)}")
        send_whatsapp_message(admin_number, f"❌ Error: {str(e)}")
        return False

def send_admin_stats(admin_number):
    """Send statistics to admin"""
    try:
        all_records = sheet.get_all_records()
        
        total_leads = len(all_records)
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        today_leads = len([r for r in all_records if r.get('Timestamp', '').startswith(today)])
        
        bookings_today = len([r for r in all_records if 
                             r.get('Timestamp', '').startswith(today) and 
                             'book' in r.get('Intent', '').lower()])
        
        inquiries_today = len([r for r in all_records if 
                              r.get('Timestamp', '').startswith(today) and 
                              'inquiry' in r.get('Intent', '').lower()])
        
        stats_message = (
            f"📊 *Admin Statistics* 📈\n\n"
            f"📅 Today ({today}):\n"
            f"• Total Leads: {today_leads}\n"
            f"• Bookings: {bookings_today}\n"
            f"• Inquiries: {inquiries_today}\n\n"
            f"📈 All Time:\n"
            f"• Total Leads: {total_leads}\n\n"
            f"🔧 Admin Commands:\n"
            f"• reminder <number> <date>\n"
            f"• stats\n"
            f"• help"
        )
        
        send_whatsapp_message(admin_number, stats_message)
        
    except Exception as e:
        logger.error(f"Error sending admin stats: {str(e)}")
        send_whatsapp_message(admin_number, f"❌ Error generating stats: {str(e)}")

def send_admin_help(admin_number):
    """Send admin help message"""
    help_message = (
        f"🛠️ *Admin Commands Help* 🔧\n\n"
        f"📋 Available Commands:\n\n"
        f"🔔 *Reminder Management:*\n"
        f"• `reminder <whatsapp_id> <tour_date>`\n"
        f"  Send immediate reminder to customer\n"
        f"  Example: `reminder 96891234567 29/10/24`\n\n"
        f"📊 *Statistics:*\n"
        f"• `stats` - View today's statistics\n\n"
        f"❓ *Help:*\n"
        f"• `help` - Show this help message\n\n"
        f"👥 *Regular Features:*\n"
        f"Admins can also use all regular customer features like booking tours, inquiries, etc."
    )
    
    send_whatsapp_message(admin_number, help_message)

# ==============================
# PRICE CALCULATION
# ==============================

def calculate_price(tour_type, people_count):
    """Calculate tour price based on type and people count"""
    prices = {
        "Dolphin Watching": 25,
        "Snorkeling": 35,
        "Dhow Cruise": 40,
        "Fishing Trip": 50
    }
    
    base_price = prices.get(tour_type, 30)
    try:
        people = int(extract_number_from_people_count(people_count))
    except:
        people = 1
    
    if people >= 4:
        return base_price * people * 0.9  # 10% discount
    
    return base_price * people

# ==============================
# KEYWORD HANDLING
# ==============================

def handle_keyword_questions(text, phone_number):
    """Handle direct keyword questions without menu"""
    text_lower = text.lower()
    
    if any(word in text_lower for word in ['where', 'location', 'address', 'located', 'map']):
        response = """📍 *Our Location:* 🌊

🏖️ *Al Bahr Sea Tours*
Marina Bandar Al Rowdha
Muscat, Oman

🗺️ *Google Maps:* 
https://maps.app.goo.gl/albahrseatours

🚗 *Parking:* Available at marina
⏰ *Opening Hours:* 7:00 AM - 7:00 PM Daily

We're located at the beautiful Bandar Al Rowdha Marina! 🚤"""
        send_whatsapp_message(phone_number, response)
        return True
    
    elif any(word in text_lower for word in ['price', 'cost', 'how much', 'fee', 'charge']):
        response = """💰 *Tour Prices & Packages:* 💵

🐬 *Dolphin Watching Tour:*
• 2 hours • 25 OMR per person
• Includes: Guide, safety equipment, refreshments

🤿 *Snorkeling Adventure:*
• 3 hours • 35 OMR per person  
• Includes: Equipment, guide, snacks & drinks

⛵ *Sunset Dhow Cruise:*
• 2 hours • 40 OMR per person
• Includes: Traditional Omani dinner, drinks

🎣 *Fishing Trip:*
• 4 hours • 50 OMR per person
• Includes: Fishing gear, bait, refreshments

👨‍👩‍👧‍👦 *Family & Group Discounts Available!*"""
        send_whatsapp_message(phone_number, response)
        return True
    
    elif any(word in text_lower for word in ['time', 'schedule', 'hour', 'when', 'available']):
        response = """🕒 *Tour Schedule & Timings:* ⏰

*Daily Tour Departures:*
🌅 *Morning Sessions:*
• Dolphin Watching: 8:00 AM, 10:00 AM
• Snorkeling: 9:00 AM, 11:00 AM

🌇 *Afternoon Sessions:*
• Fishing Trips: 2:00 PM
• Dhow Cruises: 4:00 PM, 6:00 PM

📅 *Advanced booking recommended!*"""
        send_whatsapp_message(phone_number, response)
        return True
    
    elif any(word in text_lower for word in ['contact', 'phone', 'call', 'number', 'whatsapp']):
        response = """📞 *Contact Al Bahr Sea Tours:* 📱

*Phone:* +968 24 123456
*WhatsApp:* +968 9123 4567
*Email:* info@albahrseatours.com

🌐 *Website:* www.albahrseatours.com

⏰ *Customer Service Hours:*
7:00 AM - 7:00 PM Daily

📍 *Visit Us:*
Marina Bandar Al Rowdha, Muscat"""
        send_whatsapp_message(phone_number, response)
        return True
    
    return False

# ==============================
# ENHANCED MESSAGE HANDLING
# ==============================

def handle_interaction(interaction_id, phone_number):
    """Handle list and button interactions - FIXED 5+ PEOPLE"""
    logger.info(f"Handling interaction: {interaction_id} for {phone_number}")
    
    # Handle enhanced inquiry interactions
    if interaction_id.startswith('inquire_'):
        parts = interaction_id.split('|')
        action = parts[0]
        
        if action in ['inquire_dolphin', 'inquire_snorkeling', 'inquire_dhow', 'inquire_fishing'] and len(parts) >= 2:
            tour_map = {
                'inquire_dolphin': 'Dolphin Watching',
                'inquire_snorkeling': 'Snorkeling', 
                'inquire_dhow': 'Dhow Cruise',
                'inquire_fishing': 'Fishing Trip'
            }
            ask_inquiry_people_count(phone_number, tour_map.get(action))
            return True
            
        elif action.startswith('inquire_people_') and len(parts) >= 3:
            people_count = action.replace('inquire_people_', '')
            tour_interest = parts[2]
            
            if people_count == '5plus':
                ask_inquiry_exact_people_count(phone_number, tour_interest)
            else:
                # Store as number only
                ask_inquiry_preferred_date(phone_number, tour_interest, people_count)
            return True
    
    # Handle booking flow interactions  
    if '|' in interaction_id:
        parts = interaction_id.split('|')
        action = parts[0]
        
        if action.startswith('book_') and len(parts) >= 3:
            tour_type_map = {
                'book_dolphin': 'Dolphin Watching',
                'book_snorkeling': 'Snorkeling',
                'book_dhow': 'Dhow Cruise',
                'book_fishing': 'Fishing Trip'
            }
            
            tour_type = tour_type_map.get(action)
            name = parts[1]
            contact = parts[2]
            
            ask_for_people_count(phone_number, name, contact, tour_type)
            return True
            
        elif action.startswith('people_') and len(parts) >= 4:
            people_count = action.replace('people_', '')
            name = parts[1]
            contact = parts[2]
            tour_type = parts[3]
            
            if people_count == '5plus':
                ask_for_exact_people_count(phone_number, name, contact, tour_type)
            else:
                # Store as number only
                ask_for_date(phone_number, name, contact, tour_type, people_count)
            return True
            
        elif action.startswith('time_') and len(parts) >= 6:
            time_map = {
                'time_8am': '8:00 AM',
                'time_9am': '9:00 AM',
                'time_10am': '10:00 AM',
                'time_2pm': '2:00 PM',
                'time_4pm': '4:00 PM',
                'time_6pm': '6:00 PM'
            }
            
            booking_time = time_map.get(action, 'Not specified')
            name = parts[1]
            contact = parts[2]
            tour_type = parts[3]
            people_count = parts[4]  # Now stored as number only
            booking_date = parts[5]
            
            complete_booking(phone_number, name, contact, tour_type, people_count, booking_date, booking_time)
            return True
    
    # Regular menu interactions
    responses = {
        "view_options": lambda: send_main_options_list(phone_number),
        
        "dolphin_tour": """🐬 *Dolphin Watching Tour* 🌊

*Experience the magic of swimming with wild dolphins!* 

📅 *Duration:* 2 hours
💰 *Price:* 25 OMR per person
👥 *Group size:* Small groups (max 8 people)

*What's included:*
• Expert marine guide 🧭
• Safety equipment & life jackets 🦺
• Refreshments & bottled water 🥤
• Photography opportunities 📸

*Best time:* Morning tours (8AM, 10AM)
*Success rate:* 95% dolphin sightings! 

Ready to book? Select 'Book Now'! 📅""",

        "snorkeling": """🤿 *Snorkeling Adventure* 🐠

*Discover Oman's underwater paradise!* 

📅 *Duration:* 3 hours
💰 *Price:* 35 OMR per person
👥 *Group size:* Small groups (max 6 people)

*What's included:*
• Full snorkeling equipment 🤿
• Professional guide 🧭
• Safety equipment 🦺
• Snacks & refreshments 🍎🥤

*What you'll see:*
• Vibrant coral gardens 🌸
• Tropical fish species 🐠
• Sea turtles (if lucky!) 🐢
• Crystal clear waters 💎

Ready to explore? Select 'Book Now'! 🌊""",

        "dhow_cruise": """⛵ *Traditional Dhow Cruise* 🌅

*Sail into the sunset on a traditional Omani boat!*

📅 *Duration:* 2 hours
💰 *Price:* 40 OMR per person
👥 *Group size:* Intimate groups (max 10 people)

*What's included:*
• Traditional Omani dhow cruise ⛵
• Sunset views & photography 🌅
• Omani dinner & refreshments 🍽️
• Soft drinks & water 🥤

*Departure times:* 4:00 PM, 6:00 PM
*Perfect for:* Couples, families, special occasions 

Ready to sail? Select 'Book Now'! ⛵""",

        "fishing": """🎣 *Deep Sea Fishing Trip* 🐟

*Experience the thrill of deep sea fishing!*

📅 *Duration:* 4 hours
💰 *Price:* 50 OMR per person
👥 *Group size:* Small groups (max 4 people)

*What's included:*
• Professional fishing gear 🎣
• Bait & tackle 🪱
• Expert fishing guide 🧭
• Refreshments & snacks 🥤🍎
• Clean & prepare your catch 🐟

*Suitable for:* Beginners to experienced
*Includes:* Fishing license

Ready to catch the big one? Select 'Book Now'! 🎣""",

        "pricing": """💰 *Tour Prices & Packages* 💵

*All prices include safety equipment & guides*

🐬 *Dolphin Watching:* 25 OMR
• 2 hours • Small groups • Refreshments included

🤿 *Snorkeling Adventure:* 35 OMR  
• 3 hours • Full equipment • Snacks & drinks

⛵ *Dhow Cruise:* 40 OMR
• 2 hours • Traditional boat • Dinner included

🎣 *Fishing Trip:* 50 OMR
• 4 hours • Professional gear • Refreshments

👨‍👩‍👧‍👦 *Special Offers:*
• Family Package (4 people): 10% discount
• Group Booking (6+ people): 15% discount
• Children under 12: 50% discount

Book your adventure today! 📅""",

        "location": """📍 *Our Location & Directions* 🗺️

🏖️ *Al Bahr Sea Tours*
Marina Bandar Al Rowdha
Muscat, Sultanate of Oman

🗺️ *Google Maps:*
https://maps.app.goo.gl/albahrseatours

🚗 *How to reach us:*
• From Muscat City Center: 15 minutes
• From Seeb Airport: 25 minutes  
• From Al Mouj: 10 minutes

🅿️ *Parking:* Ample parking available at marina

⏰ *Operating Hours:*
7:00 AM - 7:00 PM Daily

We're easy to find at Bandar Al Rowdha Marina! 🚤""",

        "schedule": """🕒 *Tour Schedule & Availability* 📅

*Daily Departure Times:*

🌅 *Morning Adventures:*
• 8:00 AM - Dolphin Watching 🐬
• 9:00 AM - Snorkeling 🤿
• 10:00 AM - Dolphin Watching 🐬
• 11:00 AM - Snorkeling 🤿

🌇 *Afternoon Experiences:*
• 2:00 PM - Fishing Trip 🎣
• 4:00 PM - Dhow Cruise ⛵
• 5:00 PM - Sunset Dolphin 🐬

🌅 *Evening Magic:*
• 6:00 PM - Dhow Cruise ⛵
• 6:30 PM - Sunset Cruise 🌅

📅 *Advanced booking recommended*
⏰ *Check-in:* 30 minutes before departure""",

        "contact": """📞 *Contact Al Bahr Sea Tours* 📱

*We're here to help you plan the perfect sea adventure!* 🌊

📞 *Phone:* +968 24 123456
📱 *WhatsApp:* +968 9123 4567
📧 *Email:* info@albahrseatours.com

🌐 *Website:* www.albahrseatours.com

⏰ *Customer Service Hours:*
7:00 AM - 7:00 PM Daily

📍 *Visit Us:*
Marina Bandar Al Rowdha
Muscat, Oman""",

        "book_now": lambda: send_booking_options(phone_number),
        
        "book_tour": lambda: start_booking_flow(phone_number),
        
        "inquire_tour": lambda: start_enhanced_inquiry_flow(phone_number)
    }
    
    response = responses.get(interaction_id)
    
    if callable(response):
        response()
        return True
    elif response:
        send_whatsapp_message(phone_number, response)
        return True
    else:
        send_whatsapp_message(phone_number, "Sorry, I didn't understand that option. Please select from the menu. 📋")
        return False

# ==============================
# ENHANCED WEBHOOK HANDLER
# ==============================

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

@app.route("/webhook", methods=["GET"])
def verify():
    """Webhook verification for Meta"""
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    
    if token == VERIFY_TOKEN:
        logger.info("✅ Webhook verified successfully")
        return challenge
    else:
        logger.warning("❌ Webhook verification failed: token mismatch")
        return "Verification token mismatch", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming WhatsApp messages - FIXED SESSION MANAGEMENT"""
    try:
        data = request.get_json()
        
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        
        if not messages:
            return jsonify({"status": "no_message"})
            
        message = messages[0]
        phone_number = message["from"]
        
        # Clean up old sessions periodically
        if random.random() < 0.1:  # 10% chance to cleanup
            cleanup_old_sessions()
        
        # Check for reset commands for testing
        if "text" in message:
            text = message["text"]["body"].strip().lower()
            
            # Reset commands for testing
            if text in ['reset', 'restart', 'new session', 'clear', 'start over']:
                clear_user_sessions(phone_number)
                send_whatsapp_message(phone_number, "🔄 *Session reset!* Starting fresh...")
                send_welcome_message(phone_number)
                return jsonify({"status": "session_reset"})
            
            # Check for admin commands
            if handle_admin_command(phone_number, text):
                return jsonify({"status": "admin_command_handled"})
        
        # Handle interactive messages
        if "interactive" in message:
            interactive_data = message["interactive"]
            interactive_type = interactive_data["type"]
            
            if interactive_type == "list_reply":
                list_reply = interactive_data["list_reply"]
                option_id = list_reply["id"]
                
                logger.info(f"📋 List option selected: {option_id} by {phone_number}")
                if handle_interaction(option_id, phone_number):
                    return jsonify({"status": "interaction_handled"})
                return jsonify({"status": "list_handled"})
            
            elif interactive_type == "button_reply":
                button_reply = interactive_data["button_reply"]
                button_id = button_reply["id"]
                
                logger.info(f"🔘 Button clicked: {button_id} by {phone_number}")
                
                if button_id == "view_options":
                    send_main_options_list(phone_number)
                    return jsonify({"status": "view_options_sent"})
                
                if handle_interaction(button_id, phone_number):
                    return jsonify({"status": "interaction_handled"})
                return jsonify({"status": "button_handled"})
        
        # Handle text messages
        if "text" in message:
            text = message["text"]["body"].strip()
            logger.info(f"💬 Text message: '{text}' from {phone_number}")
            
            booking_session = booking_sessions.get(phone_number)
            inquiry_session = inquiry_sessions.get(phone_number)
            
            # Handle enhanced inquiry flow steps
            if inquiry_session and inquiry_session.get('flow') == 'enhanced_inquiry':
                step = inquiry_session.get('step')
                
                if step == 'awaiting_exact_people_count':
                    if text.isdigit() and int(text) >= 5:
                        people_count = text  # Store as number only
                        tour_interest = inquiry_session['answers'].get('tour_interest', 'Tour')
                        ask_inquiry_preferred_date(phone_number, tour_interest, people_count)
                        return jsonify({"status": "exact_people_received"})
                    else:
                        send_whatsapp_message(phone_number,
                            "❌ Please enter a valid number of 5 or more people.\n"
                            "Example: 6, 8, 10, etc.")
                        return jsonify({"status": "invalid_people_count"})
                
                elif step == 'awaiting_preferred_date':
                    tour_interest = inquiry_session['answers'].get('tour_interest', 'Tour')
                    people_count = inquiry_session['answers'].get('people_count', '1')
                    ask_inquiry_questions(phone_number, tour_interest, people_count, text)
                    return jsonify({"status": "inquiry_date_received"})
                
                elif step == 'awaiting_questions':
                    complete_enhanced_inquiry(phone_number, text)
                    return jsonify({"status": "inquiry_completed"})
            
            # Handle booking flow steps
            if booking_session and booking_session.get('step') == 'awaiting_name':
                ask_for_contact(phone_number, text)
                return jsonify({"status": "name_received"})
            
            elif booking_session and booking_session.get('step') == 'awaiting_contact':
                name = booking_session.get('name', '')
                ask_for_tour_type(phone_number, name, text)
                return jsonify({"status": "contact_received"})
            
            elif booking_session and booking_session.get('step') == 'awaiting_date':
                name = booking_session.get('name', '')
                contact = booking_session.get('contact', '')
                tour_type = booking_session.get('tour_type', '')
                people_count = booking_session.get('people_count', '')
                
                ask_for_time(phone_number, name, contact, tour_type, people_count, text)
                return jsonify({"status": "date_received"})
            
            elif booking_session and booking_session.get('step') == 'awaiting_exact_people_count':
                if text.isdigit() and int(text) >= 5:
                    people_count = text  # Store as number only
                    name = booking_session.get('name', '')
                    contact = booking_session.get('contact', '')
                    tour_type = booking_session.get('tour_type', '')
                    ask_for_date(phone_number, name, contact, tour_type, people_count)
                    return jsonify({"status": "exact_people_received"})
                else:
                    send_whatsapp_message(phone_number,
                        "❌ Please enter a valid number of 5 or more people.\n"
                        "Example: 6, 8, 10, etc.")
                    return jsonify({"status": "invalid_people_count"})
            
            # Enhanced "Inquire Now" handling
            if not booking_session and not inquiry_session and text.lower() in ["inquire", "inquire now", "more info"]:
                start_enhanced_inquiry_flow(phone_number)
                return jsonify({"status": "enhanced_inquiry_started"})
            
            # Keyword questions and greeting handling
            if not booking_session and not inquiry_session and handle_keyword_questions(text, phone_number):
                return jsonify({"status": "keyword_answered"})
            
            if not booking_session and not inquiry_session and text.lower() in ["hi", "hello", "hey", "start", "menu"]:
                send_welcome_message(phone_number)
                return jsonify({"status": "welcome_sent"})
            
            # If no specific match, send welcome message
            if not booking_session and not inquiry_session:
                send_welcome_message(phone_number)
                return jsonify({"status": "fallback_welcome_sent"})
        
        return jsonify({"status": "unhandled_message_type"})
        
    except Exception as e:
        logger.error(f"🚨 Error in webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==============================
# API ENDPOINTS
# ==============================

@app.route("/api/leads", methods=["GET"])
def get_leads():
    """Return all leads for dashboard"""
    try:
        if not sheet:
            return jsonify({"error": "Google Sheets not configured"}), 500
        
        all_values = sheet.get_all_values()
        
        if not all_values or len(all_values) <= 1:
            return jsonify([])
        
        headers = all_values[0]
        valid_leads = []
        
        for row in all_values[1:]:
            if not any(cell.strip() for cell in row):
                continue
                
            processed_row = {}
            for j, header in enumerate(headers):
                value = row[j] if j < len(row) else ""
                processed_row[header] = str(value).strip() if value else ""
            
            has_data = any([
                processed_row.get('Name', ''),
                processed_row.get('Contact', ''), 
                processed_row.get('WhatsApp ID', ''),
                processed_row.get('Intent', '')
            ])
            
            if has_data:
                valid_leads.append(processed_row)
        
        return jsonify(valid_leads)
            
    except Exception as e:
        logger.error(f"Error in get_leads: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/broadcast", methods=["POST", "OPTIONS"])
def broadcast():
    """Send broadcast messages with better data handling"""
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
        
    try:
        data = request.get_json()
        logger.info(f"📨 Received broadcast request")
        
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        segment = data.get("segment", "all")
        message = data.get("message", "").strip()
        
        if not message:
            return jsonify({"error": "Message cannot be empty"}), 400
            
        if not sheet:
            return jsonify({"error": "Google Sheets not available"}), 500
        
        all_records = sheet.get_all_records()
        logger.info(f"📊 Found {len(all_records)} total records")
        
        target_leads = []
        
        for row in all_records:
            whatsapp_id = None
            for field in ["WhatsApp ID", "WhatsAppID", "whatsapp_id", "WhatsApp", "Phone", "Contact", "Mobile"]:
                if field in row and row[field]:
                    whatsapp_id = str(row[field]).strip()
                    if whatsapp_id and whatsapp_id.lower() not in ["pending", "none", "null", ""]:
                        break
            
            if not whatsapp_id:
                continue
                
            clean_whatsapp_id = clean_oman_number(whatsapp_id)
            if not clean_whatsapp_id:
                continue
                
            intent = ""
            for field in ["Intent", "intent", "Status", "status"]:
                if field in row and row[field]:
                    intent = str(row[field]).strip()
                    break
            
            intent_lower = intent.lower() if intent else ""
            
            if segment == "all":
                target_leads.append({
                    "whatsapp_id": clean_whatsapp_id,
                    "name": row.get('Name', '') or row.get('name', ''),
                    "intent": intent
                })
            elif segment == "book_tour" and "book" in intent_lower:
                target_leads.append({
                    "whatsapp_id": clean_whatsapp_id,
                    "name": row.get('Name', '') or row.get('name', ''),
                    "intent": intent
                })
            elif segment == "inquire_tour" and "inquiry" in intent_lower:
                target_leads.append({
                    "whatsapp_id": clean_whatsapp_id,
                    "name": row.get('Name', '') or row.get('name', ''),
                    "intent": intent
                })
        
        logger.info(f"🎯 Targeting {len(target_leads)} recipients for segment '{segment}'")
        
        if len(target_leads) == 0:
            return jsonify({
                "status": "no_recipients", 
                "sent": 0,
                "failed": 0,
                "total_recipients": 0,
                "message": "No valid recipients found for the selected segment."
            })
        
        sent_count = 0
        failed_count = 0
        
        for i, lead in enumerate(target_leads):
            try:
                if i > 0:
                    time.sleep(2)
                
                personalized_message = message
                if lead["name"] and lead["name"] not in ["", "Pending", "Unknown", "None"]:
                    personalized_message = f"Hello {lead['name']}! 👋\n\n{message}"
                
                logger.info(f"📤 Sending to {lead['whatsapp_id']} - {lead['name']}")
                
                success = send_whatsapp_message(lead["whatsapp_id"], personalized_message)
                
                if success:
                    sent_count += 1
                else:
                    failed_count += 1
                    
            except Exception as e:
                failed_count += 1
                logger.error(f"Error sending to {lead['whatsapp_id']}: {str(e)}")
        
        result = {
            "status": "broadcast_completed",
            "sent": sent_count,
            "failed": failed_count,
            "total_recipients": len(target_leads),
            "segment": segment,
            "message": f"Broadcast completed: {sent_count} sent, {failed_count} failed"
        }
        
        logger.info(f"📬 Broadcast result: {result}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Broadcast error: {str(e)}")
        return jsonify({"error": f"Broadcast failed: {str(e)}"}), 500

@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint"""
    status = {
        "status": "Al Bahr Sea Tours WhatsApp API Active 🌊",
        "timestamp": str(datetime.datetime.now()),
        "whatsapp_configured": bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_ID),
        "sheets_available": sheet is not None,
        "active_sessions": len(booking_sessions),
        "active_inquiry_sessions": len(inquiry_sessions),
        "scheduler_running": scheduler.running,
        "version": "7.0 - Fixed Calendar & 5+ People"
    }
    return jsonify(status)

# ==============================
# RUN APPLICATION
# ==============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    
    # Ensure scheduler is running
    if not scheduler.running:
        scheduler.start()
        logger.info("✅ Reminder scheduler started")
    
    app.run(host="0.0.0.0", port=port, debug=False)