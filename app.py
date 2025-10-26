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
    
    # Ensure the sheet has the right columns
    try:
        current_headers = sheet.row_values(1)
        required_headers = ['Timestamp', 'Name', 'Contact', 'WhatsApp ID', 'Intent', 'Tour Type', 'Booking Date', 'Booking Time', 'Adults Count', 'Children Count', 'Total Guests']
        if current_headers != required_headers:
            sheet.clear()
            sheet.append_row(required_headers)
            logger.info("✅ Updated Google Sheets headers")
    except:
        # If sheet is empty, add headers
        sheet.append_row(['Timestamp', 'Name', 'Contact', 'WhatsApp ID', 'Intent', 'Tour Type', 'Booking Date', 'Booking Time', 'Adults Count', 'Children Count', 'Total Guests'])
    
    logger.info("✅ Google Sheets initialized successfully")
except Exception as e:
    logger.error(f"❌ Google Sheets initialization failed: {str(e)}")
    sheet = None

# Simple session management
booking_sessions = {}

# ==============================
# HELPER FUNCTIONS
# ==============================

def add_lead_to_sheet(name, contact, intent, whatsapp_id, tour_type="Not specified", booking_date="Not specified", booking_time="Not specified", adults_count="0", children_count="0", total_guests="0"):
    """Add user entry to Google Sheet"""
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
        sheet.append_row([timestamp, name, contact, whatsapp_id, intent, tour_type, booking_date, booking_time, adults_count, children_count, total_guests])
        logger.info(f"✅ Added lead to sheet: {name}, {contact}, {intent}, Adults: {adults_count}, Children: {children_count}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to add lead to sheet: {str(e)}")
        return False

def send_whatsapp_message(to, message, interactive_data=None):
    """Send WhatsApp message via Meta API"""
    try:
        # Clean the phone number
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
    
    # Remove all non-digit characters
    clean_number = ''.join(filter(str.isdigit, str(number)))
    
    if not clean_number:
        return None
        
    # Handle Oman numbers specifically
    if len(clean_number) == 8 and clean_number.startswith(('9', '7', '8')):
        # Local Oman number (9xxxxxxx, 7xxxxxxx, or 8xxxxxxx)
        return '968' + clean_number
    elif len(clean_number) == 11 and clean_number.startswith('968'):
        # Full Oman number with country code
        return clean_number
    elif len(clean_number) == 12 and clean_number.startswith('968'):
        # Already in correct format
        return clean_number
    
    return None

def send_welcome_message(to):
    """Send initial welcome message with direct tour list"""
    send_main_options_list(to)

def send_main_options_list(to):
    """Send ALL options in one list - This is now the main menu"""
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "🌊 Al Bahr Sea Tours"
        },
        "body": {
            "text": "Welcome to Oman's premier sea adventure company! 🚤\n\nChoose your sea adventure: 🗺️"
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

def start_booking_flow(to):
    """Start the booking flow by asking for name"""
    # Clear any existing session
    if to in booking_sessions:
        del booking_sessions[to]
    
    # Create new session
    booking_sessions[to] = {
        'step': 'awaiting_name',
        'flow': 'booking'
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
    # Update session with name
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
    # Update session with contact
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

def ask_for_adults_count(to, name, contact, tour_type):
    """Ask for number of adults"""
    # Update session with tour type
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_adults_count',
            'name': name,
            'contact': contact,
            'tour_type': tour_type
        })
    
    send_whatsapp_message(to,
        f"👥 *Number of Adults*\n\n"
        f"Great choice! {tour_type} it is! 🎯\n\n"
        "How many *adults* (12 years and above) will be joining?\n\n"
        "Please send the number:\n"
        "*Examples:* 2, 4, 6")

def ask_for_children_count(to, name, contact, tour_type, adults_count):
    """Ask for number of children"""
    # Update session with adults count
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_children_count',
            'name': name,
            'contact': contact,
            'tour_type': tour_type,
            'adults_count': adults_count
        })
    
    send_whatsapp_message(to,
        f"👶 *Number of Children*\n\n"
        f"Adults: {adults_count}\n\n"
        "How many *children* (below 12 years) will be joining?\n\n"
        "Please send the number:\n"
        "*Examples:* 0, 1, 2\n\n"
        "If no children, just send: 0")

def ask_for_date(to, name, contact, tour_type, adults_count, children_count):
    """Ask for preferred date"""
    # Calculate total guests
    total_guests = int(adults_count) + int(children_count)
    
    # Update session with people counts
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_date',
            'name': name,
            'contact': contact,
            'tour_type': tour_type,
            'adults_count': adults_count,
            'children_count': children_count,
            'total_guests': total_guests
        })
    
    send_whatsapp_message(to,
        f"📅 *Preferred Date*\n\n"
        f"Perfect! {total_guests} guests total:\n"
        f"• {adults_count} adults\n"
        f"• {children_count} children\n\n"
        "Please send your *preferred date*:\n\n"
        "📋 *Format Examples:*\n"
        "• **Tomorrow**\n"
        "• **October 29**\n" 
        "• **Next Friday**\n"
        "• **15 November**\n"
        "• **2024-12-25**\n\n"
        "We'll check availability for your chosen date! 📅")

def ask_for_time(to, name, contact, tour_type, adults_count, children_count, booking_date):
    """Ask for preferred time"""
    total_guests = int(adults_count) + int(children_count)
    
    # Update session with date
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_time',
            'name': name,
            'contact': contact,
            'tour_type': tour_type,
            'adults_count': adults_count,
            'children_count': children_count,
            'total_guests': total_guests,
            'booking_date': booking_date
        })
    
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "🕒 Preferred Time"
        },
        "body": {
            "text": f"Perfect! {booking_date} for {tour_type}.\n\n{total_guests} guests:\n• {adults_count} adults\n• {children_count} children\n\nChoose your preferred time:"
        },
        "action": {
            "button": "Select Time",
            "sections": [
                {
                    "title": "Morning Sessions",
                    "rows": [
                        {
                            "id": f"time_8am|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}",
                            "title": "🌅 8:00 AM",
                            "description": "Early morning adventure"
                        },
                        {
                            "id": f"time_9am|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}", 
                            "title": "☀️ 9:00 AM",
                            "description": "Morning session"
                        },
                        {
                            "id": f"time_10am|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}",
                            "title": "🌞 10:00 AM", 
                            "description": "Late morning"
                        }
                    ]
                },
                {
                    "title": "Afternoon Sessions",
                    "rows": [
                        {
                            "id": f"time_2pm|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}",
                            "title": "🌇 2:00 PM",
                            "description": "Afternoon adventure"
                        },
                        {
                            "id": f"time_4pm|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}",
                            "title": "🌅 4:00 PM",
                            "description": "Late afternoon"
                        },
                        {
                            "id": f"time_6pm|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}",
                            "title": "🌆 6:00 PM",
                            "description": "Evening session"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def complete_booking(to, name, contact, tour_type, adults_count, children_count, booking_date, booking_time):
    """Complete the booking and save to sheet"""
    total_guests = int(adults_count) + int(children_count)
    
    # Save to Google Sheets
    success = add_lead_to_sheet(
        name=name,
        contact=contact,
        intent="Book Tour",
        whatsapp_id=to,
        tour_type=tour_type,
        booking_date=booking_date,
        booking_time=booking_time,
        adults_count=adults_count,
        children_count=children_count,
        total_guests=str(total_guests)
    )
    
    # Clear the session
    if to in booking_sessions:
        del booking_sessions[to]
    
    # Send confirmation message
    if success:
        send_whatsapp_message(to,
            f"🎉 *Booking Confirmed!* ✅\n\n"
            f"Thank you {name}! Your tour has been booked successfully. 🐬\n\n"
            f"📋 *Booking Details:*\n"
            f"👤 Name: {name}\n"
            f"📞 Contact: {contact}\n"
            f"🚤 Tour: {tour_type}\n"
            f"👥 Guests: {total_guests} total\n"
            f"   • {adults_count} adults\n"
            f"   • {children_count} children\n"
            f"📅 Date: {booking_date}\n"
            f"🕒 Time: {booking_time}\n\n"
            f"💰 *Total: {calculate_price(tour_type, adults_count, children_count)} OMR*\n\n"
            f"Our team will contact you within 1 hour to confirm details. ⏰\n"
            f"For immediate assistance: +968 24 123456 📞\n\n"
            f"Get ready for an amazing sea adventure! 🌊")
    else:
        send_whatsapp_message(to,
            f"📝 *Booking Received!*\n\n"
            f"Thank you {name}! We've received your booking request. 🐬\n\n"
            f"📋 *Your Details:*\n"
            f"👤 Name: {name}\n"
            f"📞 Contact: {contact}\n"
            f"🚤 Tour: {tour_type}\n"
            f"👥 Guests: {total_guests} total\n"
            f"   • {adults_count} adults\n"
            f"   • {children_count} children\n"
            f"📅 Date: {booking_date}\n"
            f"🕒 Time: {booking_time}\n\n"
            f"Our team will contact you within 1 hour to confirm. 📞")

def calculate_price(tour_type, adults_count, children_count):
    """Calculate tour price based on type and people count"""
    prices = {
        "Dolphin Watching": 25,
        "Snorkeling": 35,
        "Dhow Cruise": 40,
        "Fishing Trip": 50
    }
    
    base_price = prices.get(tour_type, 30)
    adults = int(adults_count)
    children = int(children_count)
    
    # Children under 12 get 50% discount
    adult_total = adults * base_price
    children_total = children * (base_price * 0.5)  # 50% discount for children
    
    total_price = adult_total + children_total
    
    # Apply group discount for 4+ total guests
    if (adults + children) >= 4:
        total_price = total_price * 0.9  # 10% discount
    
    return f"{total_price:.2f}"

def handle_keyword_questions(text, phone_number):
    """Handle direct keyword questions without menu"""
    text_lower = text.lower()
    
    # Location questions
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
    
    # Price questions
    elif any(word in text_lower for word in ['price', 'cost', 'how much', 'fee', 'charge']):
        response = """💰 *Tour Prices & Packages:* 💵

🐬 *Dolphin Watching Tour:*
• 2 hours • 25 OMR per adult
• Children under 12: 50% discount
• Includes: Guide, safety equipment, refreshments

🤿 *Snorkeling Adventure:*
• 3 hours • 35 OMR per adult
• Children under 12: 50% discount  
• Includes: Equipment, guide, snacks & drinks

⛵ *Sunset Dhow Cruise:*
• 2 hours • 40 OMR per adult
• Children under 12: 50% discount
• Includes: Traditional Omani dinner, drinks

🎣 *Fishing Trip:*
• 4 hours • 50 OMR per adult
• Children under 12: 50% discount
• Includes: Fishing gear, bait, refreshments

👨‍👩‍👧‍👦 *Special Offers:*
• Group of 4+ people: 10% discount
• Family packages available!"""
        send_whatsapp_message(phone_number, response)
        return True
    
    # Timing questions
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
    
    # Contact questions
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

def handle_interaction(interaction_id, phone_number):
    """Handle list and button interactions"""
    logger.info(f"Handling interaction: {interaction_id} for {phone_number}")
    
    # Check if it's a booking flow interaction
    if '|' in interaction_id:
        parts = interaction_id.split('|')
        action = parts[0]
        
        if action.startswith('book_') and len(parts) >= 3:
            # Tour type selection
            tour_type_map = {
                'book_dolphin': 'Dolphin Watching',
                'book_snorkeling': 'Snorkeling',
                'book_dhow': 'Dhow Cruise',
                'book_fishing': 'Fishing Trip'
            }
            
            tour_type = tour_type_map.get(action)
            name = parts[1]
            contact = parts[2]
            
            ask_for_adults_count(phone_number, name, contact, tour_type)
            return True
            
        elif action.startswith('time_') and len(parts) >= 7:
            # Time selection - complete booking
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
            adults_count = parts[4]
            children_count = parts[5]
            booking_date = parts[6]
            
            complete_booking(phone_number, name, contact, tour_type, adults_count, children_count, booking_date, booking_time)
            return True
    
    # Regular menu interactions
    responses = {
        # Welcome button - now directly sends main list
        "view_options": lambda: send_main_options_list(phone_number),
        
        # Tour options
        "dolphin_tour": """🐬 *Dolphin Watching Tour* 🌊

*Experience the magic of swimming with wild dolphins!* 

📅 *Duration:* 2 hours
💰 *Price:* 25 OMR per adult (50% off for children)
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
💰 *Price:* 35 OMR per adult (50% off for children)
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
💰 *Price:* 40 OMR per adult (50% off for children)
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
💰 *Price:* 50 OMR per adult (50% off for children)
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

        # Information options
        "pricing": """💰 *Tour Prices & Packages* 💵

*All prices include safety equipment & guides*
*Children under 12 get 50% discount!*

🐬 *Dolphin Watching:* 25 OMR per adult
• 2 hours • Small groups • Refreshments included

🤿 *Snorkeling Adventure:* 35 OMR per adult  
• 3 hours • Full equipment • Snacks & drinks

⛵ *Dhow Cruise:* 40 OMR per adult
• 2 hours • Traditional boat • Dinner included

🎣 *Fishing Trip:* 50 OMR per adult
• 4 hours • Professional gear • Refreshments

👨‍👩‍👧‍👦 *Special Offers:*
• Group of 4+ people: 10% discount
• Family packages available

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

        "book_now": lambda: start_booking_flow(phone_number)
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
# ADMIN CHAT INTERVENTION FUNCTIONS
# ==============================

def send_admin_message(phone_number, message):
    """Send message as admin to specific user"""
    try:
        # Add admin identifier to the message
        admin_message = f"💬 *Admin Support:*\n\n{message}\n\n— Al Bahr Sea Tours Team 🌊"
        
        success = send_whatsapp_message(phone_number, admin_message)
        
        if success:
            # Log the admin intervention
            logger.info(f"✅ Admin message sent to {phone_number}: {message}")
            return True
        else:
            logger.error(f"❌ Failed to send admin message to {phone_number}")
            return False
            
    except Exception as e:
        logger.error(f"🚨 Error sending admin message: {str(e)}")
        return False

def get_user_session(phone_number):
    """Get current session state for a user"""
    session = booking_sessions.get(phone_number)
    if session:
        return {
            'has_session': True,
            'step': session.get('step', 'unknown'),
            'flow': session.get('flow', 'unknown'),
            'name': session.get('name', 'Not provided'),
            'contact': session.get('contact', 'Not provided'),
            'tour_type': session.get('tour_type', 'Not selected'),
            'adults_count': session.get('adults_count', '0'),
            'children_count': session.get('children_count', '0'),
            'total_guests': session.get('total_guests', '0'),
            'booking_date': session.get('booking_date', 'Not selected')
        }
    else:
        return {'has_session': False}

# ==============================
# CORS FIX - SIMPLE AND CLEAN
# ==============================

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# ==============================
# WEBHOOK ENDPOINTS
# ==============================

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
    """Handle incoming WhatsApp messages and interactions"""
    try:
        data = request.get_json()
        
        # Extract message details
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        
        if not messages:
            return jsonify({"status": "no_message"})
            
        message = messages[0]
        phone_number = message["from"]
        
        # Check if it's an interactive message (list or button)
        if "interactive" in message:
            interactive_data = message["interactive"]
            interactive_type = interactive_data["type"]
            
            if interactive_type == "list_reply":
                list_reply = interactive_data["list_reply"]
                option_id = list_reply["id"]
                
                logger.info(f"📋 List option selected: {option_id} by {phone_number}")
                handle_interaction(option_id, phone_number)
                return jsonify({"status": "list_handled"})
            
            elif interactive_type == "button_reply":
                button_reply = interactive_data["button_reply"]
                button_id = button_reply["id"]
                
                logger.info(f"🔘 Button clicked: {button_id} by {phone_number}")
                
                if button_id == "view_options":
                    send_main_options_list(phone_number)
                    return jsonify({"status": "view_options_sent"})
                
                handle_interaction(button_id, phone_number)
                return jsonify({"status": "button_handled"})
        
        # Handle text messages
        if "text" in message:
            text = message["text"]["body"].strip()
            logger.info(f"💬 Text message: '{text}' from {phone_number}")
            
            # Get current session
            session = booking_sessions.get(phone_number)
            
            # First, check for keyword questions (unless in booking flow)
            if not session and handle_keyword_questions(text, phone_number):
                return jsonify({"status": "keyword_answered"})
            
            # Check for greeting
            if not session and text.lower() in ["hi", "hello", "hey", "start", "menu"]:
                send_welcome_message(phone_number)
                return jsonify({"status": "welcome_sent"})
            
            # Handle booking flow - name input
            if session and session.get('step') == 'awaiting_name':
                ask_for_contact(phone_number, text)
                return jsonify({"status": "name_received"})
            
            # Handle booking flow - contact input
            elif session and session.get('step') == 'awaiting_contact':
                name = session.get('name', '')
                ask_for_tour_type(phone_number, name, text)
                return jsonify({"status": "contact_received"})
            
            # Handle booking flow - adults count input
            elif session and session.get('step') == 'awaiting_adults_count':
                # Validate numeric input
                if text.isdigit() and int(text) > 0:
                    name = session.get('name', '')
                    contact = session.get('contact', '')
                    tour_type = session.get('tour_type', '')
                    ask_for_children_count(phone_number, name, contact, tour_type, text)
                    return jsonify({"status": "adults_count_received"})
                else:
                    send_whatsapp_message(phone_number, "Please enter a valid number of adults (e.g., 2, 4, 6)")
                    return jsonify({"status": "invalid_adults_count"})
            
            # Handle booking flow - children count input
            elif session and session.get('step') == 'awaiting_children_count':
                # Validate numeric input
                if text.isdigit() and int(text) >= 0:
                    name = session.get('name', '')
                    contact = session.get('contact', '')
                    tour_type = session.get('tour_type', '')
                    adults_count = session.get('adults_count', '')
                    ask_for_date(phone_number, name, contact, tour_type, adults_count, text)
                    return jsonify({"status": "children_count_received"})
                else:
                    send_whatsapp_message(phone_number, "Please enter a valid number of children (e.g., 0, 1, 2)")
                    return jsonify({"status": "invalid_children_count"})
            
            # Handle booking flow - date input
            elif session and session.get('step') == 'awaiting_date':
                name = session.get('name', '')
                contact = session.get('contact', '')
                tour_type = session.get('tour_type', '')
                adults_count = session.get('adults_count', '')
                children_count = session.get('children_count', '')
                
                ask_for_time(phone_number, name, contact, tour_type, adults_count, children_count, text)
                return jsonify({"status": "date_received"})
            
            # If no specific match, send welcome message
            if not session:
                send_welcome_message(phone_number)
                return jsonify({"status": "fallback_welcome_sent"})
        
        return jsonify({"status": "unhandled_message_type"})
        
    except Exception as e:
        logger.error(f"🚨 Error in webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==============================
# DASHBOARD API ENDPOINTS
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
            # Try multiple field names for WhatsApp ID
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
                
            # Extract intent
            intent = ""
            for field in ["Intent", "intent", "Status", "status"]:
                if field in row and row[field]:
                    intent = str(row[field]).strip()
                    break
            
            # Check segment filter
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
                    time.sleep(2)  # Rate limiting
                
                # Personalize message
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

# ==============================
# ADMIN CHAT INTERVENTION ENDPOINTS
# ==============================

@app.route("/api/send_message", methods=["POST", "OPTIONS"])
def send_admin_message_endpoint():
    """Send message as admin to specific user"""
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
        
    try:
        data = request.get_json()
        phone_number = data.get("phone_number")
        message = data.get("message")
        
        if not phone_number or not message:
            return jsonify({"error": "Phone number and message required"}), 400
        
        # Clean the phone number
        clean_phone = clean_oman_number(phone_number)
        if not clean_phone:
            return jsonify({"error": "Invalid phone number format"}), 400
        
        success = send_admin_message(clean_phone, message)
        
        if success:
            return jsonify({
                "status": "message_sent",
                "message": "Admin message sent successfully",
                "phone_number": clean_phone
            })
        else:
            return jsonify({"error": "Failed to send message"}), 500
            
    except Exception as e:
        logger.error(f"Error in send_admin_message: {str(e)}")
        return jsonify({"error": f"Failed to send message: {str(e)}"}), 500

@app.route("/api/user_session/<phone_number>", methods=["GET"])
def get_user_session_endpoint(phone_number):
    """Get current session state for a user"""
    try:
        # Clean the phone number
        clean_phone = clean_oman_number(phone_number)
        if not clean_phone:
            return jsonify({"error": "Invalid phone number format"}), 400
        
        session_info = get_user_session(clean_phone)
        return jsonify(session_info)
        
    except Exception as e:
        logger.error(f"Error getting user session: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/active_sessions", methods=["GET"])
def get_active_sessions():
    """Get all active booking sessions"""
    try:
        active_sessions = {}
        for phone, session in booking_sessions.items():
            active_sessions[phone] = {
                'step': session.get('step', 'unknown'),
                'flow': session.get('flow', 'unknown'),
                'name': session.get('name', 'Not provided'),
                'tour_type': session.get('tour_type', 'Not selected'),
                'timestamp': datetime.datetime.now().isoformat()
            }
        
        return jsonify({
            "total_active_sessions": len(active_sessions),
            "sessions": active_sessions
        })
        
    except Exception as e:
        logger.error(f"Error getting active sessions: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint"""
    status = {
        "status": "Al Bahr Sea Tours WhatsApp API Active 🌊",
        "timestamp": str(datetime.datetime.now()),
        "whatsapp_configured": bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_ID),
        "sheets_available": sheet is not None,
        "active_sessions": len(booking_sessions),
        "version": "7.0 - Admin Chat Intervention"
    }
    return jsonify(status)

# ==============================
# RUN APPLICATION
# ==============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)