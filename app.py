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
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
SHEET_NAME = os.environ.get("SHEET_NAME", "Al Bahr Bot Leads")
WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID", "797371456799734")

# Validate required environment variables
missing_vars = []
if not WHATSAPP_TOKEN:
    missing_vars.append("WHATSAPP_TOKEN")
if not WHATSAPP_PHONE_ID:
    missing_vars.append("WHATSAPP_PHONE_ID")
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
    logger.info("Google Sheets initialized successfully")
    
    # Ensure headers exist
    try:
        headers = sheet.row_values(1)
        if not headers or len(headers) < 5:
            # Add headers if they don't exist
            header_row = ["Timestamp", "Name", "Contact", "WhatsApp ID", "Intent", "Tour Type", "Booking Date", "Booking Time", "People Count"]
            sheet.insert_row(header_row, 1)
            logger.info("Added headers to Google Sheet")
    except Exception as e:
        logger.error(f"Error checking headers: {str(e)}")
        
except Exception as e:
    logger.error(f"Google Sheets initialization failed: {str(e)}")
    sheet = None

# ==============================
# HELPER FUNCTIONS
# ==============================

def add_lead_to_sheet(name, contact, intent, whatsapp_id, tour_type="Not specified", booking_date="Not specified", booking_time="Not specified", people_count="Not specified"):
    """Add user entry to Google Sheet"""
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
        
        # Create row with all columns
        row_data = [
            timestamp,           # Timestamp
            name,                # Name
            contact,             # Contact
            whatsapp_id,         # WhatsApp ID
            intent,              # Intent
            tour_type,           # Tour Type
            booking_date,        # Booking Date
            booking_time,        # Booking Time
            people_count         # People Count
        ]
        
        sheet.append_row(row_data)
        logger.info(f"✅ Added lead to sheet: {name}, {contact}, {intent}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to add lead to sheet: {str(e)}")
        return False

def send_whatsapp_message(to, message, interactive_data=None):
    """Send WhatsApp message via Meta API"""
    try:
        # Clean the phone number
        clean_to = ''.join(filter(str.isdigit, str(to)))
        
        # Ensure proper format for WhatsApp API
        if not clean_to.startswith('968') and len(clean_to) >= 8:
            if clean_to.startswith('9'):
                clean_to = '968' + clean_to
            else:
                clean_to = '968' + clean_to.lstrip('0')
        
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

        logger.info(f"📤 Sending message to {clean_to}")
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response_data = response.json()
        
        if response.status_code == 200:
            logger.info(f"✅ Message sent to {clean_to}")
            return True
        else:
            error_message = response_data.get('error', {}).get('message', 'Unknown error')
            logger.error(f"❌ WhatsApp API error: {error_message}")
            return False
        
    except Exception as e:
        logger.error(f"🚨 Failed to send message: {str(e)}")
        return False

def send_welcome_message(to):
    """Send initial welcome message"""
    interactive_data = {
        "type": "button",
        "body": {
            "text": "🌊 *Al Bahr Sea Tours* 🐬\n\nWelcome to Oman's premier sea adventure company!\n\nReady to explore? 🗺️"
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
            "text": "Choose your sea adventure:"
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
                            "description": "Swim with wild dolphins"
                        },
                        {
                            "id": "snorkeling", 
                            "title": "🤿 Snorkeling",
                            "description": "Explore coral reefs"
                        },
                        {
                            "id": "dhow_cruise",
                            "title": "⛵ Dhow Cruise", 
                            "description": "Traditional sunset cruise"
                        },
                        {
                            "id": "fishing",
                            "title": "🎣 Fishing Trip",
                            "description": "Deep sea fishing"
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
                            "id": "book_now",
                            "title": "📅 Book Now", 
                            "description": "Reserve your sea adventure"
                        },
                        {
                            "id": "inquire_tour",
                            "title": "💬 Inquire",
                            "description": "Get more information"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def start_booking_flow(to):
    """Start the booking flow by asking for name"""
    send_whatsapp_message(to, 
        "📝 *Let's Book Your Tour!* 🎫\n\n"
        "I'll help you book your sea adventure. 🌊\n\n"
        "First, please send me your:\n\n"
        "👤 *Full Name*\n\n"
        "*Example:*\n"
        "Ahmed Al Harthy")

def ask_for_contact(to, name):
    """Ask for contact after getting name"""
    send_whatsapp_message(to, 
        f"Perfect, {name}! 👋\n\n"
        "Now please send me your:\n\n"
        "📞 *Phone Number*\n\n"
        "*Example:*\n"
        "91234567")

def ask_for_tour_type(to, name, contact):
    """Ask for tour type using interactive list"""
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
                            "description": "2 hours • 25 OMR"
                        },
                        {
                            "id": f"book_snorkeling|{name}|{contact}", 
                            "title": "🤿 Snorkeling",
                            "description": "3 hours • 35 OMR"
                        },
                        {
                            "id": f"book_dhow|{name}|{contact}",
                            "title": "⛵ Dhow Cruise", 
                            "description": "2 hours • 40 OMR"
                        },
                        {
                            "id": f"book_fishing|{name}|{contact}",
                            "title": "🎣 Fishing Trip",
                            "description": "4 hours • 50 OMR"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def ask_for_people_count(to, name, contact, tour_type):
    """Ask for number of people"""
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
                            "id": f"people_5+|{name}|{contact}|{tour_type}",
                            "title": "👨‍👩‍👧‍👦 5+ People",
                            "description": "Large group"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def ask_for_date(to, name, contact, tour_type, people_count):
    """Ask for preferred date"""
    send_whatsapp_message(to,
        f"📅 *Preferred Date*\n\n"
        f"Great choice! {people_count} for {tour_type}. 🎯\n\n"
        "Please send your *preferred date*:\n\n"
        "*Examples:*\n"
        "• October 29\n"
        "• Next Friday\n"
        "• November 5\n\n"
        "We'll check availability! 📅")

def ask_for_time(to, name, contact, tour_type, people_count, booking_date):
    """Ask for preferred time"""
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "🕒 Preferred Time"
        },
        "body": {
            "text": f"Perfect! {booking_date} for {tour_type}.\nChoose your time:"
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
                            "description": "Early morning"
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
                            "description": "Afternoon"
                        },
                        {
                            "id": f"time_4pm|{name}|{contact}|{tour_type}|{people_count}|{booking_date}",
                            "title": "🌅 4:00 PM",
                            "description": "Late afternoon"
                        },
                        {
                            "id": f"time_6pm|{name}|{contact}|{tour_type}|{people_count}|{booking_date}",
                            "title": "🌆 6:00 PM",
                            "description": "Evening"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def complete_booking(to, name, contact, tour_type, people_count, booking_date, booking_time):
    """Complete the booking and save to sheet"""
    # Save to Google Sheets
    if sheet:
        success = add_lead_to_sheet(
            name=name,
            contact=contact,
            intent="Book Tour",
            whatsapp_id=to,
            tour_type=tour_type,
            booking_date=booking_date,
            booking_time=booking_time,
            people_count=people_count
        )
        
        if success:
            logger.info(f"✅ Booking saved to sheet for {name}")
        else:
            logger.error(f"❌ Failed to save booking for {name}")
    
    # Send confirmation message
    send_whatsapp_message(to,
        f"🎉 *Booking Confirmed!* ✅\n\n"
        f"Thank you {name}! Your tour has been booked. 🐬\n\n"
        f"📋 *Booking Details:*\n"
        f"👤 Name: {name}\n"
        f"📞 Contact: {contact}\n"
        f"🚤 Tour: {tour_type}\n"
        f"👥 People: {people_count}\n"
        f"📅 Date: {booking_date}\n"
        f"🕒 Time: {booking_time}\n\n"
        f"💰 *Total: {calculate_price(tour_type, people_count)} OMR*\n\n"
        f"Our team will contact you within 1 hour. ⏰\n"
        f"For assistance: +968 24 123456 📞\n\n"
        f"Get ready for an amazing adventure! 🌊")

def calculate_price(tour_type, people_count):
    """Calculate tour price"""
    prices = {
        "Dolphin Watching": 25,
        "Snorkeling": 35,
        "Dhow Cruise": 40,
        "Fishing Trip": 50
    }
    
    base_price = prices.get(tour_type, 30)
    people = int(people_count.replace('+', '').replace(' people', '')) if people_count.replace('+', '').replace(' people', '').isdigit() else 1
    
    if people >= 4:
        return base_price * people * 0.9  # 10% discount
    
    return base_price * people

# Store booking sessions
booking_sessions = {}

def handle_keyword_questions(text, phone_number):
    """Handle direct keyword questions"""
    text_lower = text.lower()
    
    # Location questions
    if any(word in text_lower for word in ['where', 'location', 'address', 'located', 'map']):
        response = """📍 *Our Location:* 🌊

🏖️ *Al Bahr Sea Tours*
Marina Bandar Al Rowdha, Muscat

⏰ *Hours:* 7:00 AM - 7:00 PM Daily
📞 *Phone:* +968 24 123456

We're at Bandar Al Rowdha Marina! 🚤"""
        send_whatsapp_message(phone_number, response)
        return True
    
    # Price questions
    elif any(word in text_lower for word in ['price', 'cost', 'how much', 'fee']):
        response = """💰 *Tour Prices:* 💵

🐬 Dolphin Watching: 25 OMR
🤿 Snorkeling: 35 OMR  
⛵ Dhow Cruise: 40 OMR
🎣 Fishing Trip: 50 OMR

👨‍👩‍👧‍👦 Family & Group Discounts Available!"""
        send_whatsapp_message(phone_number, response)
        return True
    
    # Timing questions
    elif any(word in text_lower for word in ['time', 'schedule', 'hour', 'when']):
        response = """🕒 *Tour Schedule:* ⏰

*Daily Departures:*
🌅 Morning: 8AM, 9AM, 10AM, 11AM
🌇 Afternoon: 2PM, 4PM, 6PM

📅 Book in advance!"""
        send_whatsapp_message(phone_number, response)
        return True
    
    # Contact questions
    elif any(word in text_lower for word in ['contact', 'phone', 'call', 'number']):
        response = """📞 *Contact Us:* 📱

*Phone:* +968 24 123456
*WhatsApp:* +968 9123 4567
*Email:* info@albahrseatours.com

⏰ 7:00 AM - 7:00 PM Daily"""
        send_whatsapp_message(phone_number, response)
        return True
    
    return False

def handle_interaction(interaction_id, phone_number):
    """Handle list and button interactions"""
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
            
            ask_for_people_count(phone_number, name, contact, tour_type)
            return True
            
        elif action.startswith('people_') and len(parts) >= 4:
            # People count selection
            people_count = action.replace('people_', '') + ' people'
            name = parts[1]
            contact = parts[2]
            tour_type = parts[3]
            
            # Store in session for date input
            booking_sessions[phone_number] = {
                'name': name,
                'contact': contact,
                'tour_type': tour_type,
                'people_count': people_count,
                'expecting_date': True
            }
            
            ask_for_date(phone_number, name, contact, tour_type, people_count)
            return True
            
        elif action.startswith('time_') and len(parts) >= 6:
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
            people_count = parts[4]
            booking_date = parts[5]
            
            complete_booking(phone_number, name, contact, tour_type, people_count, booking_date, booking_time)
            return True
    
    # Regular menu interactions
    responses = {
        "view_options": lambda: send_main_options_list(phone_number),
        
        "dolphin_tour": """🐬 *Dolphin Watching Tour* 🌊

*Swim with wild dolphins!* 

📅 2 hours • 25 OMR
👥 Small groups (max 8)

*Includes:*
• Marine guide 🧭
• Safety equipment 🦺
• Refreshments 🥤

*Best time:* Morning tours
*Success rate:* 95% sightings!""",

        "snorkeling": """🤿 *Snorkeling Adventure* 🐠

*Discover underwater paradise!* 

📅 3 hours • 35 OMR
👥 Small groups (max 6)

*Includes:*
• Full equipment 🤿
• Professional guide 🧭
• Snacks & drinks 🍎🥤

*See:* Coral reefs, tropical fish, sea turtles""",

        "dhow_cruise": """⛵ *Traditional Dhow Cruise* 🌅

*Sail into the sunset!*

📅 2 hours • 40 OMR
👥 Intimate groups (max 10)

*Includes:*
• Traditional Omani dinner 🍽️
• Refreshments 🥤
• Sunset views 🌅

*Perfect for:* Couples, families""",

        "fishing": """🎣 *Deep Sea Fishing Trip* 🐟

*Experience fishing thrill!*

📅 4 hours • 50 OMR
👥 Small groups (max 4)

*Includes:*
• Professional gear 🎣
• Bait & tackle 🪱
• Expert guide 🧭
• Refreshments 🥤""",

        "pricing": """💰 *Tour Prices:* 💵

🐬 Dolphin Watching: 25 OMR
🤿 Snorkeling: 35 OMR  
⛵ Dhow Cruise: 40 OMR
🎣 Fishing Trip: 50 OMR

👨‍👩‍👧‍👦 Family & Group Discounts!""",

        "book_now": lambda: start_booking_flow(phone_number),
        
        "inquire_tour": lambda: handle_inquiry(phone_number)
    }
    
    response = responses.get(interaction_id)
    
    if callable(response):
        response()
        return True
    elif response:
        send_whatsapp_message(phone_number, response)
        return True
    
    return False

def handle_inquiry(phone_number):
    """Handle tour inquiry"""
    if sheet:
        add_lead_to_sheet(
            name="Inquiry",
            contact=phone_number,
            intent="Tour Inquiry",
            whatsapp_id=phone_number,
            tour_type="General"
        )
    
    send_whatsapp_message(phone_number,
        "💬 *Tour Inquiry Received* ✅\n\n"
        "Thank you for your interest! We've noted your inquiry. 📝\n\n"
        "Our team will contact you shortly with:\n"
        "• Detailed tour information 📋\n"
        "• Available time slots 🕒\n"
        "• Special offers & discounts 💰\n\n"
        "For immediate assistance:\n"
        "📞 +968 24 123456\n"
        "📱 +968 9123 4567\n\n"
        "We'll help plan your perfect sea adventure! 🌊")

# ==============================
# CORS & WEBHOOK
# ==============================

@app.after_request
def after_request(response):
    """Add CORS headers to all responses"""
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
        logger.info("Webhook verified successfully")
        return challenge
    else:
        logger.warning("Webhook verification failed")
        return "Verification token mismatch", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming WhatsApp messages"""
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
        
        logger.info(f"📨 Message from {phone_number}")
        
        # Handle interactive messages
        if "interactive" in message:
            interactive_data = message["interactive"]
            interactive_type = interactive_data["type"]
            
            if interactive_type == "list_reply":
                list_reply = interactive_data["list_reply"]
                option_id = list_reply["id"]
                
                if handle_interaction(option_id, phone_number):
                    return jsonify({"status": "interaction_handled"})
                
            elif interactive_type == "button_reply":
                button_reply = interactive_data["button_reply"]
                button_id = button_reply["id"]
                
                if button_id == "view_options":
                    send_main_options_list(phone_number)
                    return jsonify({"status": "view_options_sent"})
                
                if handle_interaction(button_id, phone_number):
                    return jsonify({"status": "interaction_handled"})
            
            return jsonify({"status": "interaction_processed"})
        
        # Handle text messages
        if "text" in message:
            text = message["text"]["body"].strip()
            
            # Check for keyword questions FIRST
            if handle_keyword_questions(text, phone_number):
                return jsonify({"status": "keyword_answered"})
            
            # Handle booking flow
            if phone_number in booking_sessions:
                session = booking_sessions[phone_number]
                
                if session.get('expecting_date'):
                    # Store date and ask for time
                    name = session['name']
                    contact = session['contact']
                    tour_type = session['tour_type']
                    people_count = session['people_count']
                    booking_date = text
                    
                    ask_for_time(phone_number, name, contact, tour_type, people_count, booking_date)
                    del booking_sessions[phone_number]
                    return jsonify({"status": "date_received"})
                
                elif session.get('expecting_name'):
                    # Store name and ask for contact
                    booking_sessions[phone_number] = {
                        'name': text,
                        'expecting_contact': True
                    }
                    ask_for_contact(phone_number, text)
                    return jsonify({"status": "name_received"})
                
                elif session.get('expecting_contact'):
                    # Store contact and ask for tour type
                    name = booking_sessions[phone_number]['name']
                    contact = text
                    ask_for_tour_type(phone_number, name, contact)
                    del booking_sessions[phone_number]
                    return jsonify({"status": "contact_received"})
            
            # Check for simple name/contact format
            parts = text.split()
            if len(parts) >= 2 and any(char.isdigit() for char in text):
                name = ' '.join(parts[:-1])
                contact = parts[-1]
                
                if contact.isdigit() and len(contact) >= 7:
                    ask_for_tour_type(phone_number, name, contact)
                    return jsonify({"status": "quick_booking_started"})
            
            # Handle greetings
            if text.lower() in ["hi", "hello", "hey", "start", "menu"]:
                send_welcome_message(phone_number)
                return jsonify({"status": "welcome_sent"})
            
            # Default response
            send_welcome_message(phone_number)
            return jsonify({"status": "fallback_welcome"})
        
        return jsonify({"status": "unhandled_message"})
        
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({"status": "error"}), 500

# ==============================
# DASHBOARD ENDPOINTS
# ==============================

@app.route("/api/leads", methods=["GET"])
def get_leads():
    """Return all leads for dashboard"""
    try:
        if not sheet:
            return jsonify({"error": "Google Sheets not available"}), 500
        
        all_values = sheet.get_all_values()
        
        if not all_values or len(all_values) <= 1:
            return jsonify([])
        
        # Use first row as headers or default headers
        first_row = all_values[0]
        has_headers = any(any(c.isalpha() for c in str(cell)) for cell in first_row)
        
        if has_headers:
            headers = first_row
            data_rows = all_values[1:]
        else:
            headers = ["Timestamp", "Name", "Contact", "WhatsApp ID", "Intent", "Tour Type", "Booking Date", "Booking Time", "People Count"]
            data_rows = all_values
        
        valid_leads = []
        for row in data_rows:
            if not any(cell.strip() for cell in row):
                continue
                
            processed_row = {}
            for j in range(min(len(headers), len(row))):
                header = headers[j] if j < len(headers) else f"Column_{j+1}"
                value = row[j] if j < len(row) else ""
                processed_row[header] = str(value).strip() if value else ""
            
            # Check if row has data
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
        logger.error(f"Error getting leads: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/broadcast", methods=["POST"])
def broadcast():
    """Send broadcast messages"""
    try:
        data = request.get_json()
        segment = data.get("segment", "all")
        message = data.get("message", "").strip()
        
        if not message or not sheet:
            return jsonify({"error": "Invalid request"}), 400
        
        all_records = sheet.get_all_records()
        target_leads = []
        
        for row in all_records:
            whatsapp_id = str(row.get("WhatsApp ID", "")).strip()
            intent = str(row.get("Intent", "")).strip().lower()
            
            if not whatsapp_id or whatsapp_id.lower() in ["pending", "none"]:
                continue
                
            clean_id = ''.join(filter(str.isdigit, whatsapp_id))
            if not clean_id.startswith('968') and len(clean_id) >= 8:
                if clean_id.startswith('9'):
                    clean_id = '968' + clean_id
                else:
                    clean_id = '968' + clean_id.lstrip('0')
            
            if len(clean_id) >= 11:
                if (segment == "all" or
                    (segment == "book_tour" and "book" in intent) or
                    (segment == "inquire_tour" and "inquiry" in intent)):
                    target_leads.append(clean_id)
        
        sent_count = 0
        failed_count = 0
        
        for i, lead_id in enumerate(target_leads):
            if i > 0:
                time.sleep(2)
                
            if send_whatsapp_message(lead_id, message):
                sent_count += 1
            else:
                failed_count += 1
        
        return jsonify({
            "status": "completed",
            "sent": sent_count,
            "failed": failed_count,
            "total": len(target_leads)
        })
        
    except Exception as e:
        logger.error(f"Broadcast error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "Al Bahr Sea Tours API Active 🌊",
        "timestamp": str(datetime.datetime.now()),
        "sheets_available": sheet is not None
    })

# ==============================
# RUN APPLICATION
# ==============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)