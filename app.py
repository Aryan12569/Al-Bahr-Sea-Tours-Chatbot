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
from collections import defaultdict
import threading
from datetime import timedelta

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
ADMIN_NUMBER = os.environ.get("ADMIN_NUMBER", "96878505509")  # Your admin number

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

# Simple session management
booking_sessions = {}

# ==============================
# REMINDER SYSTEM
# ==============================

def schedule_reminder(booking_data):
    """Schedule a reminder for 24 hours before the booking"""
    try:
        booking_date = parse_date(booking_data.get('booking_date'))
        if not booking_date:
            return
        
        # Calculate reminder time (24 hours before booking)
        reminder_time = booking_date - timedelta(days=1)
        
        # For demo purposes, we'll schedule reminders 2 minutes from now
        # In production, you'd use a proper task scheduler like Celery
        demo_reminder_time = datetime.datetime.now() + timedelta(minutes=2)
        
        logger.info(f"📅 Scheduled reminder for {booking_data.get('name')} on {reminder_time}")
        
        # Store reminder in session for demo (in production, use database)
        phone = booking_data.get('whatsapp_id')
        if phone not in booking_sessions:
            booking_sessions[phone] = {}
        
        booking_sessions[phone]['reminder_scheduled'] = True
        booking_sessions[phone]['reminder_time'] = demo_reminder_time
        booking_sessions[phone]['booking_details'] = booking_data
        
    except Exception as e:
        logger.error(f"❌ Error scheduling reminder: {str(e)}")

def send_reminder(phone_number, booking_details):
    """Send reminder message to customer"""
    try:
        name = booking_details.get('name', 'there')
        tour_type = booking_details.get('tour_type', 'your tour')
        booking_date = booking_details.get('booking_date', 'the scheduled date')
        booking_time = booking_details.get('booking_time', 'the scheduled time')
        people_count = booking_details.get('people_count', 'your group')
        
        reminder_message = (
            f"🔔 *Booking Reminder* 🔔\n\n"
            f"Hello {name}! 👋\n\n"
            f"Just a friendly reminder about your upcoming sea adventure! 🌊\n\n"
            f"📋 *Booking Details:*\n"
            f"🚤 Tour: {tour_type}\n"
            f"👥 People: {people_count}\n"
            f"📅 Date: {booking_date}\n"
            f"🕒 Time: {booking_time}\n\n"
            f"📍 *Meeting Point:*\n"
            f"Marina Bandar Al Rowdha, Muscat\n"
            f"https://maps.app.goo.gl/albahrseatours\n\n"
            f"⏰ *Please arrive 30 minutes before departure*\n"
            f"🎒 *What to bring:* Swimwear, sunscreen, towel, camera\n\n"
            f"We're excited to see you tomorrow! 🐬\n\n"
            f"Need to make changes? Contact us: +968 24 123456 📞"
        )
        
        success = send_whatsapp_message(phone_number, reminder_message)
        if success:
            logger.info(f"✅ Reminder sent successfully to {phone_number}")
            return True
        else:
            logger.error(f"❌ Failed to send reminder to {phone_number}")
            return False
            
    except Exception as e:
        logger.error(f"🚨 Error sending reminder: {str(e)}")
        return False

def check_and_send_reminders():
    """Check for pending reminders and send them"""
    try:
        current_time = datetime.datetime.now()
        reminders_sent = 0
        
        for phone, session_data in list(booking_sessions.items()):
            if (session_data.get('reminder_scheduled') and 
                session_data.get('reminder_time') and 
                current_time >= session_data['reminder_time']):
                
                # Send reminder
                if send_reminder(phone, session_data.get('booking_details', {})):
                    # Mark as sent
                    session_data['reminder_sent'] = True
                    session_data['reminder_scheduled'] = False
                    reminders_sent += 1
                    logger.info(f"✅ Auto-reminder sent to {phone}")
        
        if reminders_sent > 0:
            logger.info(f"📬 Sent {reminders_sent} automatic reminders")
            
    except Exception as e:
        logger.error(f"❌ Error in reminder checker: {str(e)}")

def send_manual_reminder(admin_phone, target_phone=None):
    """Send manual reminder (admin command)"""
    try:
        if not target_phone:
            # Send to all upcoming bookings
            upcoming_bookings = get_upcoming_bookings()
            reminders_sent = 0
            
            for booking in upcoming_bookings:
                phone = booking.get('whatsapp_id')
                if phone and send_reminder(phone, booking):
                    reminders_sent += 1
            
            return f"✅ Sent reminders to {reminders_sent} customers"
        
        else:
            # Send to specific phone number
            booking = find_booking_by_phone(target_phone)
            if booking:
                if send_reminder(target_phone, booking):
                    return f"✅ Reminder sent to {booking.get('name', 'customer')}"
                else:
                    return "❌ Failed to send reminder"
            else:
                return "❌ No upcoming booking found for this number"
                
    except Exception as e:
        logger.error(f"❌ Error in manual reminder: {str(e)}")
        return f"❌ Error: {str(e)}"

def get_upcoming_bookings():
    """Get all upcoming bookings from Google Sheets"""
    try:
        if not sheet:
            return []
        
        all_records = sheet.get_all_records()
        upcoming_bookings = []
        today = datetime.date.today()
        
        for record in all_records:
            if (record.get('Intent', '').lower() == 'book tour' and
                record.get('Booking Date') and record.get('Booking Date').lower() not in ['not specified', 'pending']):
                
                booking_date = parse_date(record.get('Booking Date'))
                if booking_date and booking_date >= today:
                    upcoming_bookings.append({
                        'name': record.get('Name', ''),
                        'whatsapp_id': record.get('WhatsApp ID', ''),
                        'tour_type': record.get('Tour Type', ''),
                        'booking_date': record.get('Booking Date', ''),
                        'booking_time': record.get('Booking Time', ''),
                        'people_count': record.get('People Count', '')
                    })
        
        return upcoming_bookings
        
    except Exception as e:
        logger.error(f"❌ Error getting upcoming bookings: {str(e)}")
        return []

def find_booking_by_phone(phone_number):
    """Find upcoming booking by phone number"""
    try:
        clean_phone = clean_oman_number(phone_number)
        upcoming_bookings = get_upcoming_bookings()
        
        for booking in upcoming_bookings:
            if clean_oman_number(booking.get('whatsapp_id', '')) == clean_phone:
                return booking
        
        return None
        
    except Exception as e:
        logger.error(f"❌ Error finding booking by phone: {str(e)}")
        return None

# Start background reminder checker
def start_reminder_checker():
    """Start background thread to check reminders"""
    def reminder_loop():
        while True:
            try:
                check_and_send_reminders()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"❌ Reminder loop error: {str(e)}")
                time.sleep(60)
    
    reminder_thread = threading.Thread(target=reminder_loop, daemon=True)
    reminder_thread.start()
    logger.info("✅ Reminder checker started")

# ==============================
# ADMIN COMMANDS SYSTEM
# ==============================

def handle_admin_command(phone_number, text):
    """Handle admin commands"""
    try:
        # Check if the number is admin
        clean_admin = clean_oman_number(ADMIN_NUMBER)
        clean_sender = clean_oman_number(phone_number)
        
        if clean_sender != clean_admin:
            return False, "Not authorized"
        
        command = text.strip().lower()
        
        if command == 'reminder':
            result = send_manual_reminder(phone_number)
            return True, result
            
        elif command.startswith('reminder '):
            target_phone = command.replace('reminder ', '').strip()
            result = send_manual_reminder(phone_number, target_phone)
            return True, result
            
        elif command == 'stats':
            stats = get_booking_stats()
            return True, stats
            
        elif command == 'help':
            help_text = (
                "🔧 *Admin Commands:*\n\n"
                "• `reminder` - Send reminders to all upcoming bookings\n"
                "• `reminder 91234567` - Send reminder to specific number\n"
                "• `stats` - Get booking statistics\n"
                "• `help` - Show this help message\n\n"
                "📊 *Auto-reminders* are sent 24h before bookings"
            )
            return True, help_text
            
        else:
            return True, "❌ Unknown command. Type 'help' for available commands."
            
    except Exception as e:
        logger.error(f"❌ Admin command error: {str(e)}")
        return False, f"❌ Command error: {str(e)}"

def get_booking_stats():
    """Get booking statistics for admin"""
    try:
        if not sheet:
            return "❌ Google Sheets not available"
        
        all_records = sheet.get_all_records()
        total_bookings = 0
        upcoming_bookings = 0
        today = datetime.date.today()
        
        for record in all_records:
            if record.get('Intent', '').lower() == 'book tour':
                total_bookings += 1
                booking_date = parse_date(record.get('Booking Date', ''))
                if booking_date and booking_date >= today:
                    upcoming_bookings += 1
        
        stats = (
            f"📊 *Booking Statistics*\n\n"
            f"• Total Bookings: {total_bookings}\n"
            f"• Upcoming Bookings: {upcoming_bookings}\n"
            f"• Reminders Scheduled: {len([s for s in booking_sessions.values() if s.get('reminder_scheduled')])}\n\n"
            f"⏰ Last checked: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        
        return stats
        
    except Exception as e:
        logger.error(f"❌ Error getting stats: {str(e)}")
        return f"❌ Error getting statistics: {str(e)}"

# ==============================
# CORE HELPER FUNCTIONS
# ==============================

def add_lead_to_sheet(name, contact, intent, whatsapp_id, tour_type="Not specified", booking_date="Not specified", booking_time="Not specified", people_count="Not specified", notes=""):
    """Add user entry to Google Sheet"""
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
        sheet.append_row([timestamp, name, contact, whatsapp_id, intent, tour_type, booking_date, booking_time, people_count, notes])
        logger.info(f"✅ Added lead to sheet: {name}, {contact}, {intent}, {tour_type}")
        
        # Schedule reminder for bookings
        if intent.lower() == "book tour" and booking_date.lower() not in ["not specified", "pending"]:
            booking_data = {
                'name': name,
                'whatsapp_id': whatsapp_id,
                'tour_type': tour_type,
                'booking_date': booking_date,
                'booking_time': booking_time,
                'people_count': people_count
            }
            schedule_reminder(booking_data)
            
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

def parse_date(date_str):
    """Parse various date formats to datetime.date"""
    try:
        if not date_str or date_str.lower() in ['not specified', 'pending']:
            return None
            
        # Try different date formats
        formats = [
            '%Y-%m-%d',
            '%d/%m/%Y',
            '%m/%d/%Y',
            '%d-%m-%Y',
            '%B %d',
            '%b %d',
            '%d %B'
        ]
        
        for fmt in formats:
            try:
                return datetime.datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
                
        # Handle relative dates
        today = datetime.date.today()
        date_lower = date_str.lower()
        
        if 'tomorrow' in date_lower:
            return today + timedelta(days=1)
        elif 'today' in date_lower:
            return today
        elif 'monday' in date_lower:
            days_ahead = (0 - today.weekday()) % 7
            return today + timedelta(days=days_ahead)
        elif 'tuesday' in date_lower:
            days_ahead = (1 - today.weekday()) % 7
            return today + timedelta(days=days_ahead)
        elif 'wednesday' in date_lower:
            days_ahead = (2 - today.weekday()) % 7
            return today + timedelta(days=days_ahead)
        elif 'thursday' in date_lower:
            days_ahead = (3 - today.weekday()) % 7
            return today + timedelta(days=days_ahead)
        elif 'friday' in date_lower:
            days_ahead = (4 - today.weekday()) % 7
            return today + timedelta(days=days_ahead)
        elif 'saturday' in date_lower:
            days_ahead = (5 - today.weekday()) % 7
            return today + timedelta(days=days_ahead)
        elif 'sunday' in date_lower:
            days_ahead = (6 - today.weekday()) % 7
            return today + timedelta(days=days_ahead)
        
        return None
    except Exception as e:
        logger.error(f"Error parsing date {date_str}: {str(e)}")
        return None

def check_availability(tour_type, booking_date, booking_time, people_count):
    """Check if the requested tour slot is available"""
    try:
        if not sheet:
            return True, "No booking data available"
        
        all_records = sheet.get_all_records()
        
        # Parse the requested date and time
        requested_date = parse_date(booking_date)
        requested_time = parse_time(booking_time)
        
        if not requested_date:
            return True, "Could not parse date"
        
        # Count existing bookings for the same tour, date, and time
        conflicting_bookings = 0
        max_capacity = {
            "Dolphin Watching": 8,
            "Snorkeling": 6,
            "Dhow Cruise": 10,
            "Fishing Trip": 4
        }
        
        for record in all_records:
            if (record.get('Tour Type') == tour_type and 
                record.get('Intent', '').lower() == 'book tour' and
                record.get('Booking Date') and record.get('Booking Time')):
                
                record_date = parse_date(record.get('Booking Date'))
                record_time = parse_time(record.get('Booking Time'))
                
                if record_date == requested_date and record_time == requested_time:
                    # Add people from this booking
                    people_str = record.get('People Count', '1')
                    people = extract_people_count(people_str)
                    conflicting_bookings += people
        
        # Add the new booking's people count
        new_people = extract_people_count(people_count)
        total_people = conflicting_bookings + new_people
        capacity = max_capacity.get(tour_type, 6)
        
        if total_people > capacity:
            return False, f"❌ Sorry! This time slot is fully booked.\n\nOnly {capacity - conflicting_bookings} spots left, but you requested {new_people} people.\n\nPlease choose a different time or date."
        else:
            available_spots = capacity - total_people
            return True, f"✅ Time slot available! {available_spots} spots remaining after your booking."
            
    except Exception as e:
        logger.error(f"Error checking availability: {str(e)}")
        return True, "Availability check temporarily unavailable"

def parse_time(time_str):
    """Parse time string to standardized format"""
    try:
        if not time_str or time_str.lower() in ['not specified', 'pending']:
            return None
            
        # Extract time parts
        time_match = re.search(r'(\d{1,2}):?(\d{2})?\s*(am|pm|AM|PM)?', time_str, re.IGNORECASE)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            period = time_match.group(3)
            
            if period and period.lower() == 'pm' and hour < 12:
                hour += 12
            elif period and period.lower() == 'am' and hour == 12:
                hour = 0
                
            return f"{hour:02d}:{minute:02d}"
        
        return None
    except Exception as e:
        logger.error(f"Error parsing time {time_str}: {str(e)}")
        return None

def extract_people_count(people_str):
    """Extract number of people from various formats"""
    try:
        if not people_str:
            return 1
            
        # Handle "5+ people" format
        if '+' in people_str:
            return int(people_str.split('+')[0])
        
        # Extract digits
        numbers = re.findall(r'\d+', people_str)
        if numbers:
            return int(numbers[0])
        
        return 1
    except:
        return 1

# ==============================
# CHATBOT FLOW FUNCTIONS (ESSENTIALS)
# ==============================

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

def start_inquiry_flow(to):
    """Start the FORCED inquiry flow"""
    # Clear any existing session
    if to in booking_sessions:
        del booking_sessions[to]
    
    # Create new session for forced inquiry
    booking_sessions[to] = {
        'step': 'awaiting_inquiry_tour',
        'flow': 'inquiry',
        'inquiry_data': {}
    }
    
    send_whatsapp_message(to,
        "💬 *Tour Inquiry* 🤔\n\n"
        "I'd love to help you plan your perfect sea adventure! 🌊\n\n"
        "Let me gather some details to provide you with the best recommendations...\n\n"
        "First, which tour are you interested in? 🚤")

def ask_for_inquiry_tour_type(to):
    """Ask for tour type in inquiry flow"""
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "🚤 Interested Tour"
        },
        "body": {
            "text": "Which sea adventure catches your interest?"
        },
        "action": {
            "button": "Select Tour",
            "sections": [
                {
                    "title": "Available Tours",
                    "rows": [
                        {
                            "id": f"inquiry_dolphin|{to}",
                            "title": "🐬 Dolphin Watching",
                            "description": "Swim with wild dolphins"
                        },
                        {
                            "id": f"inquiry_snorkeling|{to}", 
                            "title": "🤿 Snorkeling",
                            "description": "Explore coral reefs"
                        },
                        {
                            "id": f"inquiry_dhow|{to}",
                            "title": "⛵ Dhow Cruise", 
                            "description": "Traditional sunset cruise"
                        },
                        {
                            "id": f"inquiry_fishing|{to}",
                            "title": "🎣 Fishing Trip",
                            "description": "Deep sea fishing adventure"
                        },
                        {
                            "id": f"inquiry_unsure|{to}",
                            "title": "🤔 Not Sure Yet",
                            "description": "Need recommendations"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def ask_for_inquiry_people_count(to, tour_type):
    """Ask for number of people in inquiry flow"""
    # Update session with tour type
    if to in booking_sessions:
        booking_sessions[to]['inquiry_data']['tour_type'] = tour_type
        booking_sessions[to]['step'] = 'awaiting_inquiry_people'
    
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "👥 Group Size"
        },
        "body": {
            "text": f"Great! {tour_type} is amazing! 🎯\n\nHow many people will be joining?"
        },
        "action": {
            "button": "Select Count",
            "sections": [
                {
                    "title": "Standard Groups",
                    "rows": [
                        {
                            "id": f"inquiry_people_1|{to}|{tour_type}",
                            "title": "👤 1 Person",
                            "description": "Solo adventure"
                        },
                        {
                            "id": f"inquiry_people_2|{to}|{tour_type}", 
                            "title": "👥 2 People",
                            "description": "Couple or friends"
                        },
                        {
                            "id": f"inquiry_people_3|{to}|{tour_type}",
                            "title": "👨‍👩‍👦 3 People", 
                            "description": "Small group"
                        },
                        {
                            "id": f"inquiry_people_4|{to}|{tour_type}",
                            "title": "👨‍👩‍👧‍👦 4 People",
                            "description": "Family package"
                        }
                    ]
                },
                {
                    "title": "Larger Groups",
                    "rows": [
                        {
                            "id": f"inquiry_people_5|{to}|{tour_type}",
                            "title": "👨‍👩‍👧‍👦 5 People",
                            "description": "Medium group"
                        },
                        {
                            "id": f"inquiry_people_6|{to}|{tour_type}",
                            "title": "👨‍👩‍👧‍👦 6 People",
                            "description": "Large group"
                        },
                        {
                            "id": f"inquiry_people_custom|{to}|{tour_type}",
                            "title": "🔢 Custom Number",
                            "description": "7+ people or special request"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def ask_for_custom_people_count(to, tour_type):
    """Ask for custom people count"""
    if to in booking_sessions:
        booking_sessions[to]['step'] = 'awaiting_inquiry_custom_people'
    
    send_whatsapp_message(to,
        f"🔢 *Custom Group Size*\n\n"
        f"For {tour_type}, we can accommodate larger groups! 🎉\n\n"
        "Please tell me:\n\n"
        "• How many people exactly? 👥\n"
        "• Any special requirements? 🌟\n\n"
        "*Example:*\n"
        "\"8 people, including 2 children\"\n"
        "or\n"
        "\"15 people for corporate event\"")

def ask_for_inquiry_date(to, tour_type, people_count):
    """Ask for preferred date in inquiry flow"""
    # Update session with people count
    if to in booking_sessions:
        booking_sessions[to]['inquiry_data']['people_count'] = people_count
        booking_sessions[to]['step'] = 'awaiting_inquiry_date'
    
    send_whatsapp_message(to,
        f"📅 *Preferred Date*\n\n"
        f"Perfect! {people_count} for {tour_type}. 🎯\n\n"
        "When would you like to go?\n\n"
        "Please send your preferred date:\n\n"
        "*Format Examples:*\n"
        "• **Tomorrow**\n"
        "• **October 29**\n" 
        "• **Next Friday**\n"
        "• **15 November**\n"
        "• **2024-12-25**\n\n"
        "I'll check availability for you! 📅")

def ask_for_inquiry_time(to, tour_type, people_count, booking_date):
    """Ask for preferred time in inquiry flow"""
    # Update session with date
    if to in booking_sessions:
        booking_sessions[to]['inquiry_data']['booking_date'] = booking_date
        booking_sessions[to]['step'] = 'awaiting_inquiry_time'
    
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "🕒 Preferred Time"
        },
        "body": {
            "text": f"Great! {booking_date} for {tour_type}.\n\nChoose your preferred time:"
        },
        "action": {
            "button": "Select Time",
            "sections": [
                {
                    "title": "Morning Sessions",
                    "rows": [
                        {
                            "id": f"inquiry_time_8am|{to}|{tour_type}|{people_count}|{booking_date}",
                            "title": "🌅 8:00 AM",
                            "description": "Early morning adventure"
                        },
                        {
                            "id": f"inquiry_time_9am|{to}|{tour_type}|{people_count}|{booking_date}", 
                            "title": "☀️ 9:00 AM",
                            "description": "Morning session"
                        },
                        {
                            "id": f"inquiry_time_10am|{to}|{tour_type}|{people_count}|{booking_date}",
                            "title": "🌞 10:00 AM", 
                            "description": "Late morning"
                        }
                    ]
                },
                {
                    "title": "Afternoon Sessions",
                    "rows": [
                        {
                            "id": f"inquiry_time_2pm|{to}|{tour_type}|{people_count}|{booking_date}",
                            "title": "🌇 2:00 PM",
                            "description": "Afternoon adventure"
                        },
                        {
                            "id": f"inquiry_time_4pm|{to}|{tour_type}|{people_count}|{booking_date}",
                            "title": "🌅 4:00 PM",
                            "description": "Late afternoon"
                        },
                        {
                            "id": f"inquiry_time_6pm|{to}|{tour_type}|{people_count}|{booking_date}",
                            "title": "🌆 6:00 PM",
                            "description": "Evening session"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def ask_for_inquiry_questions(to, tour_type, people_count, booking_date, booking_time):
    """Ask for additional questions in inquiry flow"""
    # Update session with time
    if to in booking_sessions:
        booking_sessions[to]['inquiry_data']['booking_time'] = booking_time
        booking_sessions[to]['step'] = 'awaiting_inquiry_questions'
    
    # Check availability
    is_available, availability_msg = check_availability(tour_type, booking_date, booking_time, people_count)
    
    send_whatsapp_message(to,
        f"🎯 *Perfect! Almost done...*\n\n"
        f"{availability_msg}\n\n"
        f"📋 *Your Inquiry Details:*\n"
        f"🚤 Tour: {tour_type}\n"
        f"👥 People: {people_count}\n"
        f"📅 Date: {booking_date}\n"
        f"🕒 Time: {booking_time}\n\n"
        "Finally, do you have any specific questions or special requirements? ❓\n\n"
        "*Examples:*\n"
        "• Dietary restrictions\n"
        "• Celebration occasion\n"
        "• Experience level\n"
        "• Photography requests\n\n"
        "Or just type 'No questions' if you're all set! ✅")

def complete_inquiry(to, name, contact, tour_type, people_count, booking_date, booking_time, questions):
    """Complete the inquiry and save to sheet"""
    # Save detailed inquiry to Google Sheets
    notes = f"Inquiry questions: {questions}" if questions and questions.lower() != 'no questions' else "No specific questions"
    
    success = add_lead_to_sheet(
        name=name,
        contact=contact,
        intent="Detailed Tour Inquiry",
        whatsapp_id=to,
        tour_type=tour_type,
        booking_date=booking_date,
        booking_time=booking_time,
        people_count=people_count,
        notes=notes
    )
    
    # Clear the session
    if to in booking_sessions:
        del booking_sessions[to]
    
    # Send confirmation message
    send_whatsapp_message(to,
        f"✅ *Inquiry Received!* 📝\n\n"
        f"Thank you for your detailed inquiry! Our team will contact you shortly with personalized recommendations. 📞\n\n"
        f"📋 *Your Inquiry Summary:*\n"
        f"🚤 Tour: {tour_type}\n"
        f"👥 People: {people_count}\n"
        f"📅 Date: {booking_date}\n"
        f"🕒 Time: {booking_time}\n\n"
        f"💬 Your notes: {questions if questions else 'No specific questions'}\n\n"
        f"⏰ *Expected response:* Within 1-2 hours\n"
        f"📞 *Immediate assistance:* +968 24 123456\n\n"
        f"We're excited to help you plan an unforgettable sea adventure! 🌊")

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

def ask_for_people_count(to, name, contact, tour_type):
    """Ask for number of people"""
    # Update session with tour type
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
                    "title": "Standard Groups",
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
                        }
                    ]
                },
                {
                    "title": "Larger Groups",
                    "rows": [
                        {
                            "id": f"people_5|{name}|{contact}|{tour_type}",
                            "title": "👨‍👩‍👧‍👦 5 People",
                            "description": "Medium group"
                        },
                        {
                            "id": f"people_6|{name}|{contact}|{tour_type}",
                            "title": "👨‍👩‍👧‍👦 6 People",
                            "description": "Large group"
                        },
                        {
                            "id": f"people_custom|{name}|{contact}|{tour_type}",
                            "title": "🔢 Custom Number",
                            "description": "7+ people or special request"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def ask_for_custom_people(to, name, contact, tour_type):
    """Ask for custom people count in booking flow"""
    if to in booking_sessions:
        booking_sessions[to]['step'] = 'awaiting_custom_people'
    
    send_whatsapp_message(to,
        f"🔢 *Custom Group Size*\n\n"
        f"Great! We can accommodate larger groups for {tour_type}! 🎉\n\n"
        "Please tell me:\n\n"
        "• Exact number of people 👥\n"
        "• Any special requirements 🌟\n\n"
        "*Example:*\n"
        "\"8 people\"\n"
        "or\n"
        "\"12 people including 3 children\"")

def ask_for_date(to, name, contact, tour_type, people_count):
    """Ask for preferred date"""
    # Update session with people count
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_date',
            'name': name,
            'contact': contact,
            'tour_type': tour_type,
            'people_count': people_count
        })
    
    send_whatsapp_message(to,
        f"📅 *Preferred Date*\n\n"
        f"Great choice! {people_count} for {tour_type}. 🎯\n\n"
        "Please send your preferred date:\n\n"
        "*Format Examples:*\n"
        "• **Tomorrow**\n"
        "• **October 29**\n" 
        "• **Next Friday**\n"
        "• **15 November**\n"
        "• **2024-12-25**\n\n"
        "I'll check availability for you! 📅")

def ask_for_time(to, name, contact, tour_type, people_count, booking_date):
    """Ask for preferred time"""
    # Update session with date
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
    """Complete the booking and save to sheet"""
    # Save to Google Sheets
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
            f"👥 People: {people_count}\n"
            f"📅 Date: {booking_date}\n"
            f"🕒 Time: {booking_time}\n\n"
            f"💰 *Total: {calculate_price(tour_type, people_count)} OMR*\n\n"
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
            f"👥 People: {people_count}\n"
            f"📅 Date: {booking_date}\n"
            f"🕒 Time: {booking_time}\n\n"
            f"Our team will contact you within 1 hour to confirm. 📞")

def calculate_price(tour_type, people_count):
    """Calculate tour price based on type and people count"""
    prices = {
        "Dolphin Watching": 25,
        "Snorkeling": 35,
        "Dhow Cruise": 40,
        "Fishing Trip": 50
    }
    
    base_price = prices.get(tour_type, 30)
    people = int(people_count.replace('+', '').replace(' people', '')) if people_count.replace('+', '').replace(' people', '').isdigit() else 1
    
    # Apply group discount for 4+ people
    if people >= 4:
        return base_price * people * 0.9  # 10% discount
    
    return base_price * people

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
            
            ask_for_people_count(phone_number, name, contact, tour_type)
            return True
            
        elif action.startswith('people_') and len(parts) >= 4:
            # People count selection
            people_count = action.replace('people_', '') + ' people'
            name = parts[1]
            contact = parts[2]
            tour_type = parts[3]
            
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
            
        elif action.startswith('inquiry_') and len(parts) >= 2:
            # Inquiry flow interactions
            if action.startswith('inquiry_dolphin'):
                ask_for_inquiry_people_count(phone_number, 'Dolphin Watching')
                return True
            elif action.startswith('inquiry_snorkeling'):
                ask_for_inquiry_people_count(phone_number, 'Snorkeling')
                return True
            elif action.startswith('inquiry_dhow'):
                ask_for_inquiry_people_count(phone_number, 'Dhow Cruise')
                return True
            elif action.startswith('inquiry_fishing'):
                ask_for_inquiry_people_count(phone_number, 'Fishing Trip')
                return True
            elif action.startswith('inquiry_unsure'):
                send_whatsapp_message(phone_number, 
                    "🤔 *Need Recommendations?*\n\n"
                    "Perfect! Let me suggest some options based on popular choices:\n\n"
                    "🐬 *Dolphin Watching* - Most popular, great for families\n"
                    "🤿 *Snorkeling* - Best for adventure seekers\n"
                    "⛵ *Dhow Cruise* - Perfect for couples & sunsets\n"
                    "🎣 *Fishing Trip* - Ideal for fishing enthusiasts\n\n"
                    "Which one sounds most interesting to you?")
                return True
                
            elif action.startswith('inquiry_people_') and len(parts) >= 3:
                if action == 'inquiry_people_custom':
                    tour_type = parts[2]
                    ask_for_custom_people_count(phone_number, tour_type)
                else:
                    people_count = action.replace('inquiry_people_', '') + ' people'
                    tour_type = parts[2]
                    ask_for_inquiry_date(phone_number, tour_type, people_count)
                return True
                
            elif action.startswith('inquiry_time_') and len(parts) >= 6:
                time_map = {
                    'inquiry_time_8am': '8:00 AM',
                    'inquiry_time_9am': '9:00 AM',
                    'inquiry_time_10am': '10:00 AM',
                    'inquiry_time_2pm': '2:00 PM',
                    'inquiry_time_4pm': '4:00 PM',
                    'inquiry_time_6pm': '6:00 PM'
                }
                
                booking_time = time_map.get(action, 'Not specified')
                tour_type = parts[2]
                people_count = parts[3]
                booking_date = parts[4]
                
                ask_for_inquiry_questions(phone_number, tour_type, people_count, booking_date, booking_time)
                return True
    
    # Regular menu interactions
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
        
        # Booking options
        "book_tour": lambda: start_booking_flow(phone_number),
        
        "inquire_tour": lambda: start_inquiry_flow(phone_number)
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
# WEBHOOK ENDPOINTS
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
        
        # Check for admin commands first
        if "text" in message:
            text = message["text"]["body"].strip()
            
            # Handle admin commands
            is_admin_command, admin_result = handle_admin_command(phone_number, text)
            if is_admin_command:
                send_whatsapp_message(phone_number, admin_result)
                return jsonify({"status": "admin_command_handled"})
        
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
            
            # Handle booking flow - date input
            elif session and session.get('step') == 'awaiting_date':
                name = session.get('name', '')
                contact = session.get('contact', '')
                tour_type = session.get('tour_type', '')
                people_count = session.get('people_count', '')
                
                ask_for_time(phone_number, name, contact, tour_type, people_count, text)
                return jsonify({"status": "date_received"})
            
            # Handle inquiry flow steps
            elif session and session.get('flow') == 'inquiry':
                if session.get('step') == 'awaiting_inquiry_tour':
                    # User selected tour type in inquiry
                    ask_for_inquiry_tour_type(phone_number)
                    return jsonify({"status": "inquiry_tour_prompted"})
                
                elif session.get('step') == 'awaiting_inquiry_custom_people':
                    # User provided custom people count
                    tour_type = session['inquiry_data'].get('tour_type', '')
                    session['inquiry_data']['people_count'] = text
                    ask_for_inquiry_date(phone_number, tour_type, text)
                    return jsonify({"status": "inquiry_custom_people_received"})
                
                elif session.get('step') == 'awaiting_inquiry_date':
                    # User provided date in inquiry
                    tour_type = session['inquiry_data'].get('tour_type', '')
                    people_count = session['inquiry_data'].get('people_count', '')
                    ask_for_inquiry_time(phone_number, tour_type, people_count, text)
                    return jsonify({"status": "inquiry_date_received"})
                
                elif session.get('step') == 'awaiting_inquiry_questions':
                    # User provided questions/comments
                    tour_type = session['inquiry_data'].get('tour_type', '')
                    people_count = session['inquiry_data'].get('people_count', '')
                    booking_date = session['inquiry_data'].get('booking_date', '')
                    booking_time = session['inquiry_data'].get('booking_time', '')
                    
                    # Complete inquiry with all details
                    complete_inquiry(phone_number, "Inquiry Customer", phone_number, tour_type, people_count, booking_date, booking_time, text)
                    return jsonify({"status": "inquiry_completed"})
            
            # Handle custom people count in booking flow
            elif session and session.get('step') == 'awaiting_custom_people':
                name = session.get('name', '')
                contact = session.get('contact', '')
                tour_type = session.get('tour_type', '')
                
                session['people_count'] = text
                ask_for_date(phone_number, name, contact, tour_type, text)
                return jsonify({"status": "custom_people_received"})
            
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

@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint"""
    status = {
        "status": "Al Bahr Sea Tours WhatsApp API Active 🌊",
        "timestamp": str(datetime.datetime.now()),
        "whatsapp_configured": bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_ID),
        "sheets_available": sheet is not None,
        "active_sessions": len(booking_sessions),
        "reminders_scheduled": len([s for s in booking_sessions.values() if s.get('reminder_scheduled')]),
        "version": "6.0 - Ultimate Edition with Reminders & Admin Commands"
    }
    return jsonify(status)

# ==============================
# RUN APPLICATION
# ==============================

if __name__ == "__main__":
    # Start the reminder system
    start_reminder_checker()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)