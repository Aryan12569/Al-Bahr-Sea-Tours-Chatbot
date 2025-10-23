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
except Exception as e:
    logger.error(f"Google Sheets initialization failed: {str(e)}")
    sheet = None

# ==============================
# HELPER FUNCTIONS
# ==============================

def add_lead_to_sheet(name, contact, intent, whatsapp_id, tour_type="Not specified"):
    """Add user entry to Google Sheet"""
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
        sheet.append_row([timestamp, name, contact, whatsapp_id, intent, tour_type])
        logger.info(f"Added lead to sheet: {name}, {contact}, {intent}, {tour_type}")
        return True
    except Exception as e:
        logger.error(f"Failed to add lead to sheet: {str(e)}")
        return False

def send_whatsapp_message(to, message, interactive_data=None):
    """Send WhatsApp message via Meta API with better error handling"""
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

        logger.info(f"Sending WhatsApp message to {clean_to}")
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response_data = response.json()
        
        if response.status_code == 200:
            logger.info(f"✅ WhatsApp message sent successfully to {clean_to}")
            return True
        else:
            error_message = response_data.get('error', {}).get('message', 'Unknown error')
            error_code = response_data.get('error', {}).get('code', 'Unknown')
            
            # Handle specific errors
            if error_code == 131030:
                logger.warning(f"⚠️ Number {clean_to} not in allowed list. Add it to Meta Business Account.")
                return False
            elif error_code == 131031:
                logger.warning(f"⚠️ Rate limit hit for {clean_to}. Waiting before retry.")
                time.sleep(2)
                return False
            else:
                logger.error(f"❌ WhatsApp API error {response.status_code} (Code: {error_code}): {error_message} for {clean_to}")
                return False
        
    except Exception as e:
        logger.error(f"🚨 Failed to send WhatsApp message to {to}: {str(e)}")
        return False

def send_welcome_message(to):
    """Send initial welcome message with ONE View Options button"""
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

We're located at the beautiful Bandar Al Rowdha Marina - the perfect starting point for your sea adventure! 🚤"""
        send_whatsapp_message(phone_number, response)
        return True
    
    # Price questions
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

👨‍👩‍👧‍👦 *Family & Group Discounts Available!*
💳 *Payment:* Cash/Card accepted"""
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

🌅 *Sunset Specials:*
• Sunset Dolphin: 5:00 PM
• Sunset Cruise: 6:30 PM

📅 *Advanced booking recommended!*
⏰ *Check-in:* 30 minutes before departure"""
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
Marina Bandar Al Rowdha, Muscat

We're here to help you plan the perfect sea adventure! 🐬"""
        send_whatsapp_message(phone_number, response)
        return True
    
    # Dolphin questions
    elif any(word in text_lower for word in ['dolphin', 'dolphins']):
        response = """🐬 *Dolphin Watching Tour* 🌊

*Experience:* Swim with wild dolphins in their natural habitat! 
*Duration:* 2 hours
*Price:* 25 OMR per person

*Includes:*
• Expert marine guide 🧭
• Safety equipment 🦺
• Refreshments & water 🥤
• Photography opportunities 📸

*What to bring:*
• Swimwear 🩱
• Sunscreen 🧴
• Towel 🧼
• Camera 📷

*Best time:* Morning tours (8AM-10AM) 
*Success rate:* 95% dolphin sightings!"""
        send_whatsapp_message(phone_number, response)
        return True
    
    # Snorkeling questions
    elif any(word in text_lower for word in ['snorkel', 'snorkeling', 'coral', 'fish']):
        response = """🤿 *Snorkeling Adventure* 🐠

*Explore:* Vibrant coral reefs & marine life
*Duration:* 3 hours  
*Price:* 35 OMR per person

*Includes:*
• Full snorkeling gear 🤿
• Professional guide 🧭
• Safety equipment 🦺
• Snacks & drinks 🍎🥤

*What to see:*
• Colorful coral gardens 🌸
• Tropical fish 🐠
• Sea turtles 🐢
• Amazing underwater world 🌊

*Suitable for:* Beginners & experienced"""
        send_whatsapp_message(phone_number, response)
        return True
    
    return False

def handle_interaction(interaction_id, phone_number):
    """Handle list and button interactions"""
    responses = {
        # Welcome button
        "view_options": lambda: send_main_options_list(phone_number),
        
        # Tour options
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

*What to bring:*
• Swimwear 🩱
• Sunscreen 🧴
• Towel 🧼
• Camera 📷

*Best time:* Morning tours (8AM, 10AM)
*Success rate:* 95% dolphin sightings! 

Ready to swim with dolphins? 🐬""",

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

*Suitable for:* Beginners to experienced
*Location:* Protected coral bays 

Book your underwater adventure! 🌊""",

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
• Traditional music 🎵

*Experience:*
• Sail along Muscat coast 🏖️
• Watch stunning sunset 🌅
• Enjoy Omani hospitality 🏽
• Relax in traditional setting 🛋️

*Departure times:* 4:00 PM, 6:00 PM
*Perfect for:* Couples, families, special occasions 

Sail with us! ⛵""",

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

*What you might catch:*
• Kingfish 🐟
• Tuna 🐠
• Barracuda 🦈
• Sultan Ibrahim 🐡

*Suitable for:* Beginners to experienced
*Includes:* Fishing license

Catch the big one! 🎣""",

        # Information options
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

💳 *Payment Methods:* Cash, Credit Card, Bank Transfer

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

We're easy to find at the beautiful Bandar Al Rowdha Marina! 🚤""",

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
⏰ *Check-in:* 30 minutes before departure
📞 *Confirm your booking:* +968 24 123456

Plan your perfect sea adventure! 🗓️""",

        "contact": """📞 *Contact Al Bahr Sea Tours* 📱

*We're here to help you plan the perfect sea adventure!* 🌊

📞 *Phone:* +968 24 123456
📱 *WhatsApp:* +968 9123 4567
📧 *Email:* info@albahrseatours.com

🌐 *Website:* www.albahrseatours.com
📷 *Instagram:* @albahrseatours

⏰ *Customer Service Hours:*
7:00 AM - 7:00 PM Daily

📍 *Visit Us:*
Marina Bandar Al Rowdha
Muscat, Oman

*Follow us for special offers & updates!* ✨""",

        "book_now": lambda: send_booking_options(phone_number),
        
        # Booking options
        "book_tour": """📝 *Book Your Tour* 🎫

To book your sea adventure, please send us:

👤 *Your Name*
📞 *Phone Number* 
📅 *Preferred Tour Date*
🕒 *Preferred Time*
👥 *Number of People*
🚤 *Tour Type* (Dolphin/Snorkeling/etc)

*Example:*
Ahmed | 91234567 | March 15 | 8:00 AM | 2 people | Dolphin Watching

We'll confirm your booking within 1 hour! ⏰

*Payment:* Cash at location or online transfer
*Cancellation:* 24 hours notice required

Ready for adventure? 🌊""",
        
        "inquire_tour": """💬 *Tour Inquiry* 🤔

Got questions? We're here to help! 😊

Please let us know:
• Which tour interests you? 🚤
• How many people? 👥
• Preferred date? 📅
• Any special requirements? 🌟

*We'll provide:*
• Detailed tour information 📋
• Available time slots 🕒
• Special offers & discounts 💰
• Answers to all your questions ❓

Contact us at:
📞 +968 24 123456
📱 +968 9123 4567

Let's plan your perfect sea adventure! 🌊"""
    }
    
    response = responses.get(interaction_id)
    
    if callable(response):
        response()
        return None
    elif response:
        send_whatsapp_message(phone_number, response)
        return response
    else:
        send_whatsapp_message(phone_number, "Sorry, I didn't understand that option. Please select '🌊 View Tours' to see available choices.")
        return None

# ==============================
# BROADCAST HELPER FUNCTIONS
# ==============================

def extract_whatsapp_id(row):
    """Extract WhatsApp ID from row with multiple field name support"""
    field_names = ["WhatsApp ID", "WhatsAppID", "whatsapp_id", "WhatsApp", "Phone", "Contact", "Mobile"]
    for field in field_names:
        if field in row and row[field]:
            value = str(row[field]).strip()
            if value and value.lower() not in ["pending", "none", "null", ""]:
                return value
    return None

def extract_intent(row):
    """Extract intent from row"""
    field_names = ["Intent", "intent", "Status", "status"]
    for field in field_names:
        if field in row and row[field]:
            return str(row[field]).strip()
    return ""

def extract_name(row):
    """Extract name from row"""
    field_names = ["Name", "name", "Full Name", "full_name"]
    for field in field_names:
        if field in row and row[field]:
            name = str(row[field]).strip()
            if name and name.lower() not in ["pending", "unknown", "none"]:
                return name
    return ""

def extract_tour_type(row):
    """Extract tour type from row"""
    field_names = ["Tour Type", "tour_type", "Tour", "tour"]
    for field in field_names:
        if field in row and row[field]:
            return str(row[field]).strip()
    return "Not specified"

def is_valid_whatsapp_number(number):
    """Check if number looks like a valid WhatsApp number"""
    if not number:
        return False
    clean = ''.join(filter(str.isdigit, str(number)))
    return len(clean) >= 8

def clean_whatsapp_number(number):
    """Clean and format WhatsApp number"""
    if not number:
        return None
    
    clean_number = ''.join(filter(str.isdigit, str(number)))
    
    if not clean_number:
        return None
        
    # Handle Oman numbers specifically
    if not clean_number.startswith('968'):
        if clean_number.startswith('9') and len(clean_number) == 8:
            clean_number = '968' + clean_number
        else:
            clean_number = '968' + clean_number.lstrip('0')
    
    # Final validation
    if len(clean_number) >= 11 and clean_number.startswith('968'):
        return clean_number
    
    return None

def should_include_lead(segment, intent, name):
    """Check if lead should be included based on segment"""
    intent_lower = intent.lower() if intent else ""
    
    if segment == "all":
        return True
    elif segment == "book_tour":
        return "book tour" in intent_lower or "book now" in intent_lower
    elif segment == "inquire_tour":
        return "inquire" in intent_lower or "inquiry" in intent_lower
    return False

def personalize_message(message, name):
    """Personalize message with name"""
    if name and name not in ["", "Pending", "Unknown", "None"]:
        return f"Hello {name}! 👋\n\n{message}"
    return message

# ==============================
# CORS HEADERS
# ==============================

@app.after_request
def after_request(response):
    """Add CORS headers to all responses"""
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
        logger.info("Webhook verified successfully")
        return challenge
    else:
        logger.warning("Webhook verification failed: token mismatch")
        return "Verification token mismatch", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming WhatsApp messages and interactions"""
    try:
        data = request.get_json()
        
        # Extract message details
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
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
                # Handle list selection
                list_reply = interactive_data["list_reply"]
                option_id = list_reply["id"]
                option_title = list_reply["title"]
                
                logger.info(f"List option selected: {option_id} - {option_title} by {phone_number}")
                
                # Handle booking actions - FIXED: Save actual phone number
                if option_id == "inquire_tour":
                    if sheet:
                        # Save with actual WhatsApp number instead of "Pending"
                        add_lead_to_sheet("Pending", phone_number, "Tour Inquiry", phone_number, "General Inquiry")
                    send_whatsapp_message(phone_number, "Thank you! We've noted your interest and will contact you with more information about our tours. 🌊")
                    return jsonify({"status": "inquiry_saved"})
                
                if option_id == "book_tour":
                    # For book tour, prompt for details
                    send_whatsapp_message(phone_number, 
                        "📝 *Book Your Tour* 🎫\n\nPlease send us:\n\n"
                        "👤 Your Name\n"
                        "📞 Phone Number\n" 
                        "📅 Preferred Date\n"
                        "🕒 Preferred Time\n"
                        "👥 Number of People\n"
                        "🚤 Tour Type\n\n"
                        "*Example:*\n"
                        "Ahmed | 91234567 | March 15 | 8:00 AM | 2 people | Dolphin Watching\n\n"
                        "We'll confirm within 1 hour! ⏰")
                    return jsonify({"status": "book_tour_prompt"})
                
                # Handle other list selections
                handle_interaction(option_id, phone_number)
                return jsonify({"status": "list_handled"})
            
            elif interactive_type == "button_reply":
                # Handle button click
                button_reply = interactive_data["button_reply"]
                button_id = button_reply["id"]
                button_title = button_reply["title"]
                
                logger.info(f"Button clicked: {button_id} - {button_title} by {phone_number}")
                
                # Handle view_options button
                if button_id == "view_options":
                    send_main_options_list(phone_number)
                    return jsonify({"status": "view_options_sent"})
                
                handle_interaction(button_id, phone_number)
                return jsonify({"status": "button_handled"})
        
        # Handle text messages (fallback)
        if "text" in message:
            text = message["text"]["body"].strip()
            logger.info(f"Text message received: {text} from {phone_number}")
            
            # First, check for keyword questions
            if handle_keyword_questions(text, phone_number):
                return jsonify({"status": "keyword_answered"})
            
            # Check for greeting or any message to show welcome
            if text.lower() in ["hi", "hello", "hey", "start", "menu", "hola"]:
                send_welcome_message(phone_number)
                return jsonify({"status": "welcome_sent"})
            
            # Check for booking data (name and contact with tour details)
            if any(char.isdigit() for char in text) and len(text.split()) >= 2:
                try:
                    # Parse booking information
                    parts = [p.strip() for p in text.replace("|", " ").split() if p.strip()]
                    if len(parts) >= 2:
                        name = ' '.join(parts[:-1])
                        contact = parts[-1]
                        
                        # Try to extract tour type from message
                        tour_type = "Not specified"
                        text_lower = text.lower()
                        if 'dolphin' in text_lower:
                            tour_type = "Dolphin Watching"
                        elif 'snorkel' in text_lower:
                            tour_type = "Snorkeling"
                        elif 'dhow' in text_lower or 'cruise' in text_lower:
                            tour_type = "Dhow Cruise"
                        elif 'fish' in text_lower:
                            tour_type = "Fishing Trip"
                        
                        if sheet:
                            add_lead_to_sheet(name, contact, "Book Tour", phone_number, tour_type)
                        
                        send_whatsapp_message(phone_number, 
                            f"🎫 *Booking Received!* ✅\n\n"
                            f"Thank you {name}! We have received your tour booking request. 🐬\n\n"
                            f"👤 *Name:* {name}\n"
                            f"📞 *Contact:* {contact}\n"
                            f"🚤 *Tour Type:* {tour_type}\n\n"
                            f"Our team will contact you within 1 hour to confirm your booking. ⏰\n\n"
                            f"For immediate assistance: +968 24 123456 📞\n\n"
                            f"Get ready for an amazing sea adventure! 🌊")
                        return jsonify({"status": "booked"})
                    
                except Exception as e:
                    logger.error(f"Booking parsing error: {str(e)}")
                    send_whatsapp_message(phone_number, 
                        "Please send your booking information as:\n\n"
                        "Name | Phone Number | Date | Time | People | Tour Type\n\n"
                        "*Example:*\n"
                        "Ahmed | 91234567 | March 15 | 8:00 AM | 2 people | Dolphin Watching\n\n"
                        "Or simply send: Ahmed 91234567")
                    return jsonify({"status": "booking_error"})
            
            # If no specific match and no keyword handled, send welcome message
            send_welcome_message(phone_number)
            return jsonify({"status": "fallback_welcome_sent"})
        
        return jsonify({"status": "unhandled_message_type"})
        
    except Exception as e:
        logger.error(f"Error in webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==============================
# DASHBOARD ENDPOINTS
# ==============================

@app.route("/api/leads", methods=["GET"])
def get_leads():
    """Return all leads for dashboard"""
    try:
        if sheet:
            all_data = sheet.get_all_records()
            valid_leads = []
            
            for row in all_data:
                processed_row = {}
                for key, value in row.items():
                    processed_row[key] = str(value) if value is not None else ""
                
                has_data = any([
                    processed_row.get('Name', ''),
                    processed_row.get('Contact', ''), 
                    processed_row.get('WhatsApp ID', ''),
                    processed_row.get('Intent', '')
                ])
                
                if has_data:
                    valid_leads.append(processed_row)
            
            logger.info(f"✅ Returning {len(valid_leads)} valid leads")
            return jsonify(valid_leads)
        else:
            return jsonify({"error": "Google Sheets not available"}), 500
    except Exception as e:
        logger.error(f"Error getting leads: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/broadcast", methods=["POST"])
def broadcast():
    """Send broadcast messages with better data handling"""
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
            whatsapp_id = extract_whatsapp_id(row)
            intent = extract_intent(row)
            name = extract_name(row)
            
            if not whatsapp_id or not is_valid_whatsapp_number(whatsapp_id):
                continue
                
            clean_whatsapp_id = clean_whatsapp_number(whatsapp_id)
            if not clean_whatsapp_id:
                continue
                
            if should_include_lead(segment, intent, name):
                target_leads.append({
                    "whatsapp_id": clean_whatsapp_id,
                    "name": name,
                    "intent": intent,
                    "tour_type": extract_tour_type(row),
                    "original_data": row
                })
        
        logger.info(f"🎯 Targeting {len(target_leads)} recipients for segment '{segment}'")
        
        if len(target_leads) == 0:
            return jsonify({
                "status": "no_recipients", 
                "sent": 0,
                "failed": 0,
                "total_recipients": 0,
                "debug_info": {
                    "total_records": len(all_records),
                    "segment": segment,
                    "message": "No valid recipients found. Check if you have WhatsApp numbers and correct intent values in Google Sheets."
                }
            })
        
        sent_count = 0
        failed_count = 0
        failed_details = []
        
        for i, lead in enumerate(target_leads):
            try:
                if i > 0:
                    time.sleep(3)
                
                personalized_message = personalize_message(message, lead["name"])
                
                logger.info(f"📤 Sending to {lead['whatsapp_id']} - {lead['name']}")
                
                success = send_whatsapp_message(lead["whatsapp_id"], personalized_message)
                
                if success:
                    sent_count += 1
                else:
                    failed_count += 1
                    failed_details.append({
                        "number": lead["whatsapp_id"],
                        "name": lead["name"],
                        "intent": lead["intent"],
                        "tour_type": lead["tour_type"],
                        "reason": "WhatsApp API rejected message - may need to add number to allowed list"
                    })
                    
            except Exception as e:
                failed_count += 1
                logger.error(f"Error sending to {lead['whatsapp_id']}: {str(e)}")
                failed_details.append({
                    "number": lead["whatsapp_id"],
                    "name": lead["name"],
                    "intent": lead["intent"],
                    "tour_type": lead["tour_type"],
                    "reason": str(e)
                })
        
        result = {
            "status": "broadcast_completed",
            "sent": sent_count,
            "failed": failed_count,
            "total_recipients": len(target_leads),
            "segment": segment,
            "failed_details": failed_details[:10],
            "message": f"Broadcast completed: {sent_count} sent, {failed_count} failed for segment '{segment}'"
        }
        
        logger.info(f"📬 Broadcast result: {result}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Broadcast error: {str(e)}")
        return jsonify({"error": f"Broadcast failed: {str(e)}"}), 500

@app.route("/api/debug-leads", methods=["GET"])
def debug_leads():
    """Debug endpoint to check leads data"""
    try:
        if not sheet:
            return jsonify({"error": "Google Sheets not available"}), 500
        
        all_records = sheet.get_all_records()
        processed_data = []
        
        for i, row in enumerate(all_records):
            whatsapp_id = extract_whatsapp_id(row)
            intent = extract_intent(row)
            name = extract_name(row)
            tour_type = extract_tour_type(row)
            
            clean_whatsapp_id = clean_whatsapp_number(whatsapp_id)
            is_valid = len(clean_whatsapp_id) >= 11 if clean_whatsapp_id else False
            is_book_tour = "book tour" in intent.lower() if intent else False
            is_inquire_tour = "inquiry" in intent.lower() if intent else False
            
            processed_data.append({
                "row": i + 2,
                "name": name,
                "original_whatsapp": whatsapp_id,
                "cleaned_whatsapp": clean_whatsapp_id,
                "intent": intent,
                "tour_type": tour_type,
                "is_valid": is_valid,
                "is_book_tour": is_book_tour,
                "is_inquire_tour": is_inquire_tour
            })
        
        book_tour_count = len([x for x in processed_data if x["is_book_tour"]])
        inquire_tour_count = len([x for x in processed_data if x["is_inquire_tour"]])
        valid_numbers_count = len([x for x in processed_data if x["is_valid"]])
        
        return jsonify({
            "total_records": len(all_records),
            "book_tour_count": book_tour_count,
            "inquire_tour_count": inquire_tour_count,
            "valid_whatsapp_numbers": valid_numbers_count,
            "data": processed_data
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cleanup-data", methods=["POST"])
def cleanup_data():
    """Cleanup existing data - fix Register Later users with 'Pending' contact"""
    try:
        if not sheet:
            return jsonify({"error": "Google Sheets not available"}), 500
        
        all_records = sheet.get_all_records()
        updated_count = 0
        
        for i, row in enumerate(all_records):
            intent = extract_intent(row)
            contact = extract_whatsapp_id(row)
            whatsapp_id = extract_whatsapp_id(row)
            
            # Fix Tour Inquiry users who have 'Pending' as contact but have WhatsApp ID
            if (intent and "inquiry" in intent.lower() and 
                contact and contact.lower() == "pending" and 
                whatsapp_id and whatsapp_id.lower() != "pending" and 
                is_valid_whatsapp_number(whatsapp_id)):
                
                # Update the Contact field with the WhatsApp ID
                sheet.update_cell(i+2, 3, whatsapp_id)  # +2 because of header row, 3 is Contact column
                updated_count += 1
                logger.info(f"Updated row {i+2}: Contact = {whatsapp_id}")
        
        return jsonify({
            "status": "cleanup_completed",
            "updated_records": updated_count,
            "message": f"Successfully updated {updated_count} records"
        })
        
    except Exception as e:
        logger.error(f"Cleanup error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint"""
    status = {
        "status": "Al Bahr Sea Tours WhatsApp API Active 🌊",
        "timestamp": str(datetime.datetime.now()),
        "whatsapp_configured": bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_ID),
        "sheets_available": sheet is not None,
        "version": "1.0"
    }
    return jsonify(status)

# ==============================
# RUN APPLICATION
# ==============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)