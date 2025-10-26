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
import pytz

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

# Oman Timezone
OMAN_TZ = pytz.timezone('Asia/Muscat')

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

# Session management
user_sessions = {}
booking_sessions = {}
booking_reminders = {}

# ==============================
# TOUR CONFIGURATION
# ==============================
TOURS = {
    "dolphin": {
        "name": "Dolphin Watching Tour",
        "duration": "2-3 hours",
        "price": "20 OMR per person",
        "description": "Watch dolphins in their natural habitat",
        "includes": ["Boat ride", "Dolphin watching", "Refreshments", "Safety equipment"]
    },
    "snorkeling": {
        "name": "Snorkeling Adventure", 
        "duration": "3-4 hours",
        "price": "25 OMR per person",
        "description": "Explore beautiful coral reefs and marine life",
        "includes": ["Full equipment rental", "Professional guide", "Refreshments", "Safety briefing"]
    },
    "fishing": {
        "name": "Fishing Trip",
        "duration": "4-5 hours", 
        "price": "30 OMR per person",
        "description": "Traditional fishing experience in Omani waters",
        "includes": ["Fishing equipment", "Bait", "Expert guide", "Refreshments"]
    },
    "sunset": {
        "name": "Sunset Cruise",
        "duration": "2 hours",
        "price": "15 OMR per person", 
        "description": "Relaxing cruise during beautiful sunset",
        "includes": ["Scenic cruise", "Refreshments", "Photo opportunities", "Comfort seating"]
    }
}

# ==============================
# TIMEZONE FUNCTIONS - FIXED
# ==============================

def get_oman_time():
    """Get current time in Oman timezone - FIXED"""
    return datetime.datetime.now(OMAN_TZ)

def format_oman_timestamp():
    """Format timestamp in Oman time for Google Sheets - FIXED"""
    oman_time = get_oman_time()
    return oman_time.strftime("%Y-%m-%d %H:%M:%S")

def format_oman_time_display():
    """Format for display to users"""
    oman_time = get_oman_time()
    return oman_time.strftime("%Y-%m-%d %I:%M %p")

# ==============================
# REMINDER SYSTEM - FIXED
# ==============================

def schedule_reminder(booking_data):
    """Schedule a reminder for 24 hours before the booking - DEMO MODE"""
    try:
        # For demo purposes, schedule reminder 1 minute from now
        demo_reminder_time = get_oman_time() + timedelta(minutes=1)
        
        logger.info(f"📅 Scheduled DEMO reminder for {booking_data.get('name')} at {demo_reminder_time}")
        
        # Store reminder in session
        phone = booking_data.get('whatsapp_id')
        if phone not in booking_reminders:
            booking_reminders[phone] = {}
        
        booking_reminders[phone]['reminder_scheduled'] = True
        booking_reminders[phone]['reminder_time'] = demo_reminder_time
        booking_reminders[phone]['booking_details'] = booking_data
        
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
            f"🔔 *DEMO: Booking Reminder* 🔔\n\n"
            f"Hello {name}! 👋\n\n"
            f"This is a DEMO reminder for your sea adventure! 🌊\n\n"
            f"📋 *Booking Details:*\n"
            f"🚤 Tour: {tour_type}\n"
            f"👥 People: {people_count}\n"
            f"📅 Date: {booking_date}\n"
            f"🕒 Time: {booking_time}\n\n"
            f"📍 *Meeting Point:*\n"
            f"Marina Bandar Al Rowdha, Muscat\n\n"
            f"⏰ *Please arrive 30 minutes before departure*\n"
            f"🎒 *What to bring:* Swimwear, sunscreen, towel, camera\n\n"
            f"*This is a demo reminder - not a real booking*\n"
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
        current_time = get_oman_time()
        reminders_sent = 0
        
        for phone, reminder_data in list(booking_reminders.items()):
            if (reminder_data.get('reminder_scheduled') and 
                reminder_data.get('reminder_time') and 
                current_time >= reminder_data['reminder_time'] and
                not reminder_data.get('reminder_sent')):
                
                # Send reminder
                if send_reminder(phone, reminder_data.get('booking_details', {})):
                    # Mark as sent
                    reminder_data['reminder_sent'] = True
                    reminder_data['reminder_scheduled'] = False
                    reminders_sent += 1
                    logger.info(f"✅ Auto-reminder sent to {phone}")
        
        if reminders_sent > 0:
            logger.info(f"📬 Sent {reminders_sent} automatic reminders")
            
    except Exception as e:
        logger.error(f"❌ Error in reminder checker: {str(e)}")

def send_manual_reminder(admin_phone, target_phone=None):
    """Send manual reminder (admin command) - FIXED VERSION"""
    try:
        if not target_phone:
            # Send to ALL bookings for demo
            all_bookings = get_all_bookings()
            reminders_sent = 0
            
            for booking in all_bookings:
                phone = booking.get('whatsapp_id')
                if phone:
                    # Create demo booking details
                    demo_booking = {
                        'name': booking.get('name', 'Customer'),
                        'whatsapp_id': phone,
                        'tour_type': booking.get('tour_type', 'Sea Tour'),
                        'booking_date': booking.get('booking_date', 'Soon'),
                        'booking_time': booking.get('booking_time', 'Morning'),
                        'people_count': booking.get('people_count', '2 people')
                    }
                    
                    if send_reminder(phone, demo_booking):
                        reminders_sent += 1
                        time.sleep(1)  # Rate limiting
            
            return f"✅ Sent DEMO reminders to {reminders_sent} customers"
        
        else:
            # Send to specific phone number - FIXED LOGIC
            clean_target = clean_oman_number(target_phone)
            all_bookings = get_all_bookings()
            
            # First try exact match
            for booking in all_bookings:
                booking_phone = clean_oman_number(booking.get('whatsapp_id', ''))
                if booking_phone == clean_target:
                    if send_reminder(target_phone, booking):
                        return f"✅ DEMO reminder sent to {booking.get('name', 'customer')}"
                    else:
                        return "❌ Failed to send reminder"
            
            # If no exact match found, try partial matches
            for booking in all_bookings:
                booking_phone = booking.get('whatsapp_id', '')
                if target_phone in booking_phone or clean_target in booking_phone:
                    if send_reminder(booking_phone, booking):
                        return f"✅ DEMO reminder sent to {booking.get('name', 'customer')}"
                    else:
                        return "❌ Failed to send reminder"
            
            # If no booking found at all, send demo anyway
            demo_booking = {
                'name': 'Valued Customer',
                'tour_type': 'Sea Adventure', 
                'booking_date': 'Tomorrow',
                'booking_time': 'Morning',
                'people_count': 'Your group'
            }
            if send_reminder(target_phone, demo_booking):
                return f"✅ DEMO reminder sent to {target_phone}"
            else:
                return "❌ Failed to send demo reminder"
                
    except Exception as e:
        logger.error(f"❌ Error in manual reminder: {str(e)}")
        return f"❌ Error: {str(e)}"

def get_all_bookings():
    """Get ALL bookings from Google Sheets (not just upcoming)"""
    try:
        if not sheet:
            return []
        
        all_records = sheet.get_all_records()
        bookings = []
        
        for record in all_records:
            if record.get('Intent', '').lower() == 'book tour':
                bookings.append({
                    'name': record.get('Name', ''),
                    'whatsapp_id': record.get('WhatsApp ID', ''),
                    'tour_type': record.get('Tour Type', ''),
                    'booking_date': record.get('Booking Date', ''),
                    'booking_time': record.get('Booking Time', ''),
                    'people_count': record.get('People Count', '')
                })
        
        return bookings
        
    except Exception as e:
        logger.error(f"❌ Error getting all bookings: {str(e)}")
        return []

# Start background reminder checker
def start_reminder_checker():
    """Start background thread to check reminders"""
    def reminder_loop():
        while True:
            try:
                check_and_send_reminders()
                time.sleep(30)  # Check every 30 seconds for demo
            except Exception as e:
                logger.error(f"❌ Reminder loop error: {str(e)}")
                time.sleep(30)
    
    reminder_thread = threading.Thread(target=reminder_loop, daemon=True)
    reminder_thread.start()
    logger.info("✅ Reminder checker started")

# ==============================
# ADMIN COMMANDS SYSTEM - FIXED
# ==============================

def handle_admin_command(phone_number, text):
    """Handle admin commands - FIXED VERSION"""
    try:
        # Check if the number is admin (more flexible matching)
        clean_admin = clean_oman_number(ADMIN_NUMBER)
        clean_sender = clean_oman_number(phone_number)
        
        logger.info(f"🔧 Admin check: {clean_sender} vs {clean_admin}")
        
        # Allow variations of admin number
        admin_variations = [
            clean_admin,
            clean_admin.replace('968', ''),  # Without country code
            '968' + clean_admin.replace('968', '') if not clean_admin.startswith('968') else clean_admin
        ]
        
        if clean_sender not in admin_variations:
            logger.info(f"❌ Not admin: {clean_sender}")
            return False, "Not authorized"
        
        command = text.strip().lower()
        logger.info(f"🔧 Admin command: {command}")
        
        if command == 'reminder':
            result = send_manual_reminder(phone_number)
            return True, result
            
        elif command.startswith('reminder '):
            target_phone = command.replace('reminder ', '').strip()
            # Clean the target phone
            clean_target = clean_oman_number(target_phone)
            if clean_target:
                result = send_manual_reminder(phone_number, clean_target)
            else:
                result = send_manual_reminder(phone_number, target_phone)
            return True, result
            
        elif command == 'stats':
            stats = get_booking_stats()
            return True, stats
            
        elif command == 'help':
            help_text = (
                "🔧 *Admin Commands:*\n\n"
                "• `reminder` - Send DEMO reminders to all bookings\n"
                "• `reminder 91234567` - Send DEMO reminder to specific number\n"
                "• `stats` - Get booking statistics\n"
                "• `help` - Show this help message\n\n"
                "📊 *Auto-reminders* are sent 1 minute after booking (DEMO)"
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
        today = get_oman_time().date()
        
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
            f"• Active Sessions: {len(booking_sessions)}\n"
            f"• Scheduled Reminders: {len([s for s in booking_reminders.values() if s.get('reminder_scheduled')])}\n\n"
            f"⏰ Oman Time: {format_oman_time_display()}"
        )
        
        return stats
        
    except Exception as e:
        logger.error(f"❌ Error getting stats: {str(e)}")
        return f"❌ Error getting statistics: {str(e)}"

# ==============================
# CORE HELPER FUNCTIONS - FIXED
# ==============================

def add_lead_to_sheet(name, contact, intent, whatsapp_id, tour_type="Not specified", booking_date="Not specified", booking_time="Not specified", people_count="Not specified", notes=""):
    """Add user entry to Google Sheet with Oman time - FIXED"""
    try:
        timestamp = format_oman_timestamp()  # Use proper Oman time
        sheet.append_row([timestamp, name, contact, whatsapp_id, intent, tour_type, booking_date, booking_time, people_count, notes])
        logger.info(f"✅ Added lead to sheet: {name}, {contact}, {intent}, {tour_type}")
        logger.info(f"🕒 Timestamp recorded: {timestamp}")
        
        # Schedule reminder for bookings (DEMO - 1 minute)
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
    """Clean and validate Oman phone numbers - IMPROVED FOR ADMIN"""
    if not number:
        return None
    
    # Remove all non-digit characters including quotes and special chars
    clean_number = re.sub(r'[^\d]', '', str(number))
    
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
    elif len(clean_number) == 9 and clean_number.startswith('9'):
        # Handle 9xxxxxxxx format
        return '968' + clean_number
    
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
        today = get_oman_time().date()
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

# ==============================
# CHATBOT FLOW FUNCTIONS - COMPLETE RESTORATION
# ==============================

def send_welcome_message(phone_number):
    """Send welcome message with interactive buttons"""
    try:
        interactive_data = {
            "type": "button",
            "body": {
                "text": "🌊 *Welcome to Al Bahr Sea Tours!*\n\nExperience the beauty of Oman's coastline with our exciting sea adventures! Choose an option below:"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "view_tours",
                            "title": "🚤 View Tours"
                        }
                    },
                    {
                        "type": "reply", 
                        "reply": {
                            "id": "tour_info",
                            "title": "ℹ️ Tour Info"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "contact",
                            "title": "📞 Contact"
                        }
                    }
                ]
            }
        }
        
        # Initialize user session
        user_sessions[phone_number] = {
            'state': 'WELCOME',
            'data': {},
            'last_active': get_oman_time()
        }
        
        # Add to sheet as inquiry
        add_lead_to_sheet(
            name="Not provided", 
            contact=phone_number,
            intent="Initial Inquiry",
            whatsapp_id=phone_number
        )
        
        return send_whatsapp_message(phone_number, "", interactive_data)
    except Exception as e:
        logger.error(f"Error sending welcome message: {str(e)}")
        welcome_text = (
            "🌊 Welcome to Al Bahr Sea Tours!\n\n"
            "Please reply with:\n"
            "• 'Book' to make a reservation\n" 
            "• 'Info' for tour information\n"
            "• 'Contact' to speak with us"
        )
        return send_whatsapp_message(phone_number, welcome_text)

def send_main_tours_list(phone_number):
    """Send main tours list with interactive options"""
    try:
        interactive_data = {
            "type": "list",
            "header": {
                "type": "text",
                "text": "🚤 Al Bahr Sea Tours"
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
                                "id": "snorkeling_tour", 
                                "title": "🤿 Snorkeling",
                                "description": "Explore vibrant coral reefs and marine life"
                            },
                            {
                                "id": "fishing_tour",
                                "title": "🎣 Fishing Trip", 
                                "description": "Traditional fishing experience"
                            },
                            {
                                "id": "sunset_tour",
                                "title": "🌅 Sunset Cruise",
                                "description": "Relaxing cruise during beautiful sunset"
                            }
                        ]
                    },
                    {
                        "title": "📋 Quick Actions",
                        "rows": [
                            {
                                "id": "book_now",
                                "title": "📅 Book Now", 
                                "description": "Start booking process immediately"
                            },
                            {
                                "id": "pricing_info",
                                "title": "💰 Pricing",
                                "description": "Tour prices and packages"
                            },
                            {
                                "id": "contact_info",
                                "title": "📞 Contact",
                                "description": "Get in touch with our team"
                            }
                        ]
                    }
                ]
            }
        }
        
        user_sessions[phone_number]['state'] = 'VIEWING_TOURS'
        
        return send_whatsapp_message(phone_number, "", interactive_data)
    except Exception as e:
        logger.error(f"Error sending tours list: {str(e)}")
        return send_tour_options_fallback(phone_number)

def send_tour_options_fallback(phone_number):
    """Fallback tour options as buttons"""
    interactive_data = {
        "type": "button",
        "body": {
            "text": "🚤 *Available Sea Tours*\n\nChoose your adventure:"
        },
        "action": {
            "buttons": [
                {
                    "type": "reply",
                    "reply": {
                        "id": "dolphin_tour",
                        "title": "🐬 Dolphin Watch"
                    }
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": "snorkeling_tour", 
                        "title": "🤿 Snorkeling"
                    }
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": "fishing_tour",
                        "title": "🎣 Fishing"
                    }
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": "sunset_tour",
                        "title": "🌅 Sunset Cruise"
                    }
                }
            ]
        }
    }
    
    return send_whatsapp_message(phone_number, "", interactive_data)

def send_tour_details(phone_number, tour_key):
    """Send detailed information about a specific tour"""
    try:
        tour = TOURS.get(tour_key)
        if not tour:
            return send_whatsapp_message(phone_number, "❌ Tour not found. Please choose from available options.")
        
        details = (
            f"🚤 *{tour['name']}*\n\n"
            f"📝 {tour['description']}\n\n"
            f"⏰ Duration: {tour['duration']}\n"
            f"💰 Price: {tour['price']}\n\n"
            f"✅ Includes:\n"
        )
        
        for item in tour['includes']:
            details += f"• {item}\n"
            
        details += f"\n📍 Meeting Point: Marina Bandar Al Rowdha, Muscat\n\n"
        
        # Update user session
        user_sessions[phone_number].update({
            'state': f'TOUR_DETAILS_{tour_key}',
            'selected_tour': tour_key,
            'tour_name': tour['name']
        })
        
        # Send interactive buttons
        interactive_data = {
            "type": "button",
            "body": {
                "text": details
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"book_{tour_key}",
                            "title": "✅ Book This Tour"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "more_tours",
                            "title": "🔄 Other Tours"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "main_menu",
                            "title": "🏠 Main Menu"
                        }
                    }
                ]
            }
        }
        
        return send_whatsapp_message(phone_number, "", interactive_data)
    except Exception as e:
        logger.error(f"Error sending tour details: {str(e)}")
        return send_whatsapp_message(phone_number, "❌ Error loading tour details. Please try again.")

def start_booking_flow(phone_number, tour_key=None):
    """Start the booking process for a tour"""
    try:
        if not tour_key:
            # If no tour specified, ask for tour selection first
            return send_main_tours_list(phone_number)
        
        tour = TOURS.get(tour_key)
        if not tour:
            return send_whatsapp_message(phone_number, "❌ Invalid tour selection.")
            
        # Initialize booking session
        booking_sessions[phone_number] = {
            'step': 'awaiting_name',
            'tour_type': tour['name'],
            'tour_key': tour_key,
            'start_time': get_oman_time()
        }
        
        booking_msg = (
            f"📝 *Booking {tour['name']}*\n\n"
            "Let's get your booking started! 🎫\n\n"
            "Please provide your:\n\n"
            "👤 *Full Name*\n\n"
            "*Example:*\n"
            "Ahmed Al Harthy"
        )
        
        user_sessions[phone_number]['state'] = 'BOOKING_NAME'
        
        return send_whatsapp_message(phone_number, booking_msg)
    except Exception as e:
        logger.error(f"Error starting booking flow: {str(e)}")
        return send_whatsapp_message(phone_number, "❌ Error starting booking process. Please try again.")

def handle_booking_name(phone_number, name):
    """Handle name input in booking flow"""
    try:
        if phone_number not in booking_sessions:
            return send_welcome_message(phone_number)
        
        booking_sessions[phone_number].update({
            'step': 'awaiting_contact',
            'name': name
        })
        
        user_sessions[phone_number]['state'] = 'BOOKING_CONTACT'
        
        contact_msg = (
            f"Perfect, {name}! 👋\n\n"
            "Now please send me your:\n\n"
            "📞 *Phone Number*\n\n"
            "*Example:*\n"
            "91234567"
        )
        
        return send_whatsapp_message(phone_number, contact_msg)
    except Exception as e:
        logger.error(f"Error handling booking name: {str(e)}")
        return send_whatsapp_message(phone_number, "❌ Error processing name. Please try again.")

def handle_booking_contact(phone_number, contact):
    """Handle contact input in booking flow"""
    try:
        if phone_number not in booking_sessions:
            return send_welcome_message(phone_number)
        
        session = booking_sessions[phone_number]
        session.update({
            'step': 'awaiting_date',
            'contact': contact
        })
        
        user_sessions[phone_number]['state'] = 'BOOKING_DATE'
        
        # Send date options as interactive list
        interactive_data = {
            "type": "list",
            "header": {
                "type": "text",
                "text": "📅 Preferred Date"
            },
            "body": {
                "text": f"Great {session.get('name')}! When would you like to go?\n\nSelect your preferred date:"
            },
            "action": {
                "button": "Select Date",
                "sections": [
                    {
                        "title": "🕐 Quick Selection",
                        "rows": [
                            {
                                "id": f"date_tomorrow|{phone_number}",
                                "title": "📅 Tomorrow",
                                "description": "Book for tomorrow"
                            },
                            {
                                "id": f"date_weekend|{phone_number}",
                                "title": "🎉 This Weekend", 
                                "description": "Saturday or Sunday"
                            },
                            {
                                "id": f"date_nextweek|{phone_number}",
                                "title": "📋 Next Week", 
                                "description": "Any day next week"
                            }
                        ]
                    },
                    {
                        "title": "📅 Custom Date",
                        "rows": [
                            {
                                "id": f"date_custom|{phone_number}",
                                "title": "📝 Enter Custom Date",
                                "description": "Specify your preferred date"
                            }
                        ]
                    }
                ]
            }
        }
        
        return send_whatsapp_message(phone_number, "", interactive_data)
    except Exception as e:
        logger.error(f"Error handling booking contact: {str(e)}")
        return send_whatsapp_message(phone_number, "❌ Error processing contact. Please try again.")

def handle_booking_date_selection(phone_number, date_option):
    """Handle date selection from interactive list"""
    try:
        if phone_number not in booking_sessions:
            return send_welcome_message(phone_number)
        
        session = booking_sessions[phone_number]
        
        date_map = {
            'date_tomorrow': 'Tomorrow',
            'date_weekend': 'This Weekend', 
            'date_nextweek': 'Next Week',
            'date_custom': 'Custom Date'
        }
        
        selected_date = date_map.get(date_option, 'Not specified')
        
        if date_option == 'date_custom':
            # Ask for custom date input
            session['step'] = 'awaiting_custom_date'
            user_sessions[phone_number]['state'] = 'BOOKING_CUSTOM_DATE'
            
            custom_date_msg = (
                "Please enter your preferred date:\n\n"
                "*Format Examples:*\n"
                "• **2024-12-25**\n"
                "• **25 December**\n"
                "• **Next Friday**\n"
                "• **January 15**"
            )
            return send_whatsapp_message(phone_number, custom_date_msg)
        else:
            # Store the selected date and proceed to time selection
            session.update({
                'step': 'awaiting_time',
                'booking_date': selected_date
            })
            user_sessions[phone_number]['state'] = 'BOOKING_TIME'
            
            return send_time_selection(phone_number)
            
    except Exception as e:
        logger.error(f"Error handling date selection: {str(e)}")
        return send_whatsapp_message(phone_number, "❌ Error processing date selection.")

def handle_custom_date_input(phone_number, date_input):
    """Handle custom date input"""
    try:
        if phone_number not in booking_sessions:
            return send_welcome_message(phone_number)
        
        booking_sessions[phone_number].update({
            'step': 'awaiting_time',
            'booking_date': date_input
        })
        
        user_sessions[phone_number]['state'] = 'BOOKING_TIME'
        
        return send_time_selection(phone_number)
    except Exception as e:
        logger.error(f"Error handling custom date: {str(e)}")
        return send_whatsapp_message(phone_number, "❌ Error processing date. Please try again.")

def send_time_selection(phone_number):
    """Send time selection as interactive list"""
    try:
        if phone_number not in booking_sessions:
            return send_welcome_message(phone_number)
        
        session = booking_sessions[phone_number]
        
        interactive_data = {
            "type": "list",
            "header": {
                "type": "text",
                "text": "🕒 Preferred Time"
            },
            "body": {
                "text": f"Perfect! Date: {session.get('booking_date', 'Not specified')}\n\nSelect your preferred time:"
            },
            "action": {
                "button": "Select Time",
                "sections": [
                    {
                        "title": "🌅 Morning Sessions",
                        "rows": [
                            {
                                "id": f"time_8am|{phone_number}",
                                "title": "⛅ 8:00 AM",
                                "description": "Early morning adventure"
                            },
                            {
                                "id": f"time_9am|{phone_number}", 
                                "title": "☀️ 9:00 AM",
                                "description": "Morning session"
                            },
                            {
                                "id": f"time_10am|{phone_number}",
                                "title": "🌞 10:00 AM", 
                                "description": "Late morning"
                            }
                        ]
                    },
                    {
                        "title": "🌇 Afternoon Sessions",
                        "rows": [
                            {
                                "id": f"time_2pm|{phone_number}",
                                "title": "🏖️ 2:00 PM",
                                "description": "Afternoon adventure"
                            },
                            {
                                "id": f"time_4pm|{phone_number}",
                                "title": "🌅 4:00 PM",
                                "description": "Late afternoon"
                            },
                            {
                                "id": f"time_6pm|{phone_number}",
                                "title": "🌆 6:00 PM",
                                "description": "Evening session"
                            }
                        ]
                    }
                ]
            }
        }
        
        return send_whatsapp_message(phone_number, "", interactive_data)
    except Exception as e:
        logger.error(f"Error sending time selection: {str(e)}")
        return send_whatsapp_message(phone_number, "❌ Error loading time options. Please try again.")

def handle_time_selection(phone_number, time_option):
    """Handle time selection from interactive list"""
    try:
        if phone_number not in booking_sessions:
            return send_welcome_message(phone_number)
        
        time_map = {
            'time_8am': '8:00 AM',
            'time_9am': '9:00 AM',
            'time_10am': '10:00 AM',
            'time_2pm': '2:00 PM',
            'time_4pm': '4:00 PM',
            'time_6pm': '6:00 PM'
        }
        
        selected_time = time_map.get(time_option, 'Not specified')
        
        booking_sessions[phone_number].update({
            'step': 'awaiting_people',
            'booking_time': selected_time
        })
        
        user_sessions[phone_number]['state'] = 'BOOKING_PEOPLE'
        
        return send_people_selection(phone_number)
    except Exception as e:
        logger.error(f"Error handling time selection: {str(e)}")
        return send_whatsapp_message(phone_number, "❌ Error processing time selection.")

def send_people_selection(phone_number):
    """Send people count selection as interactive list"""
    try:
        if phone_number not in booking_sessions:
            return send_welcome_message(phone_number)
        
        session = booking_sessions[phone_number]
        
        interactive_data = {
            "type": "list",
            "header": {
                "type": "text",
                "text": "👥 Number of People"
            },
            "body": {
                "text": f"Great! Time: {session.get('booking_time', 'Not specified')}\n\nHow many people will be joining?"
            },
            "action": {
                "button": "Select Count",
                "sections": [
                    {
                        "title": "👤 Small Groups",
                        "rows": [
                            {
                                "id": f"people_1|{phone_number}",
                                "title": "👤 1 Person",
                                "description": "Individual booking"
                            },
                            {
                                "id": f"people_2|{phone_number}", 
                                "title": "👥 2 People",
                                "description": "Couple or friends"
                            },
                            {
                                "id": f"people_3|{phone_number}",
                                "title": "👨‍👩‍👦 3 People", 
                                "description": "Small group"
                            }
                        ]
                    },
                    {
                        "title": "👨‍👩‍👧‍👦 Larger Groups",
                        "rows": [
                            {
                                "id": f"people_4|{phone_number}",
                                "title": "👨‍👩‍👧‍👦 4 People",
                                "description": "Family package"
                            },
                            {
                                "id": f"people_5|{phone_number}",
                                "title": "👨‍👩‍👧‍👦 5 People",
                                "description": "Medium group"
                            },
                            {
                                "id": f"people_6|{phone_number}",
                                "title": "👨‍👩‍👧‍👦 6 People",
                                "description": "Large group"
                            },
                            {
                                "id": f"people_custom|{phone_number}",
                                "title": "🔢 Custom Number",
                                "description": "7+ people or special request"
                            }
                        ]
                    }
                ]
            }
        }
        
        return send_whatsapp_message(phone_number, "", interactive_data)
    except Exception as e:
        logger.error(f"Error sending people selection: {str(e)}")
        return send_whatsapp_message(phone_number, "❌ Error loading people options. Please try again.")

def handle_people_selection(phone_number, people_option):
    """Handle people count selection"""
    try:
        if phone_number not in booking_sessions:
            return send_welcome_message(phone_number)
        
        if people_option == 'people_custom':
            # Ask for custom people count
            booking_sessions[phone_number]['step'] = 'awaiting_custom_people'
            user_sessions[phone_number]['state'] = 'BOOKING_CUSTOM_PEOPLE'
            
            custom_people_msg = (
                "Please enter the number of people:\n\n"
                "*Examples:*\n"
                "• 8\n"
                "• 12 people\n"
                "• 4 adults + 2 children\n"
                "• 15 for corporate event"
            )
            return send_whatsapp_message(phone_number, custom_people_msg)
        else:
            # Extract number from option (e.g., "people_2" -> "2 people")
            people_count = people_option.replace('people_', '') + ' people'
            return handle_booking_summary(phone_number, people_count)
            
    except Exception as e:
        logger.error(f"Error handling people selection: {str(e)}")
        return send_whatsapp_message(phone_number, "❌ Error processing people count.")

def handle_custom_people_input(phone_number, people_input):
    """Handle custom people count input"""
    try:
        if phone_number not in booking_sessions:
            return send_welcome_message(phone_number)
        
        return handle_booking_summary(phone_number, people_input)
    except Exception as e:
        logger.error(f"Error handling custom people: {str(e)}")
        return send_whatsapp_message(phone_number, "❌ Error processing group size.")

def handle_booking_summary(phone_number, people_count):
    """Show booking summary and ask for confirmation"""
    try:
        if phone_number not in booking_sessions:
            return send_welcome_message(phone_number)
        
        session = booking_sessions[phone_number]
        
        # Calculate price
        tour_key = session.get('tour_key')
        tour = TOURS.get(tour_key, {})
        try:
            price_per_person = float(re.findall(r'(\d+)', tour.get('price', '0'))[0])
            people = int(re.findall(r'\d+', people_count)[0]) if re.findall(r'\d+', people_count) else 1
            total_price = price_per_person * people
        except:
            total_price = "To be confirmed"
        
        # Store people count
        session['people_count'] = people_count
        session['total_price'] = total_price
        
        # Show booking summary
        summary_msg = (
            f"✅ *Booking Summary*\n\n"
            f"👤 Name: {session.get('name', 'Not provided')}\n"
            f"📞 Contact: {session.get('contact', 'Not provided')}\n"
            f"🚤 Tour: {session.get('tour_type', 'Not specified')}\n"
            f"📅 Date: {session.get('booking_date', 'Not specified')}\n"
            f"🕒 Time: {session.get('booking_time', 'Not specified')}\n"
            f"👥 People: {people_count}\n"
            f"💰 Estimated Total: {total_price} OMR\n\n"
            f"📍 *Meeting Point:* Marina Bandar Al Rowdha, Muscat\n\n"
            f"Please confirm your booking:"
        )
        
        session['step'] = 'awaiting_confirmation'
        user_sessions[phone_number]['state'] = 'BOOKING_CONFIRMATION'
        
        # Send confirmation buttons
        interactive_data = {
            "type": "button",
            "body": {
                "text": summary_msg
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "confirm_booking",
                            "title": "✅ Confirm Booking"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "cancel_booking",
                            "title": "❌ Cancel"
                        }
                    }
                ]
            }
        }
        
        return send_whatsapp_message(phone_number, "", interactive_data)
    except Exception as e:
        logger.error(f"Error handling booking summary: {str(e)}")
        return send_whatsapp_message(phone_number, "❌ Error creating booking summary.")

def confirm_booking_final(phone_number):
    """Finalize and save the booking"""
    try:
        if phone_number not in booking_sessions:
            return send_whatsapp_message(phone_number, "❌ No booking data found.")
        
        session = booking_sessions[phone_number]
        
        # Save to Google Sheets with ALL details
        success = add_lead_to_sheet(
            name=session.get('name', 'Not provided'),
            contact=session.get('contact', 'Not provided'),
            intent="Book Tour", 
            whatsapp_id=phone_number,
            tour_type=session.get('tour_type', 'Not specified'),
            booking_date=session.get('booking_date', 'Not specified'),
            booking_time=session.get('booking_time', 'Not specified'),
            people_count=session.get('people_count', 'Not specified'),
            notes=f"Estimated price: {session.get('total_price', 'To be confirmed')} OMR | Booking completed at: {format_oman_timestamp()}"
        )
        
        if success:
            confirmation_msg = (
                f"🎉 *Booking Confirmed!*\n\n"
                f"Thank you {session.get('name')}! Your {session.get('tour_type')} is booked.\n\n"
                f"📋 *Booking Details:*\n"
                f"📅 Date: {session.get('booking_date')}\n"
                f"🕒 Time: {session.get('booking_time')}\n"
                f"👥 People: {session.get('people_count')}\n"
                f"💰 Estimated: {session.get('total_price')} OMR\n\n"
                f"📍 *Meeting Point:*\n"
                f"Marina Bandar Al Rowdha, Muscat\n\n"
                f"📞 *Contact:* +968 24 123456\n\n"
                f"⏰ *Please arrive 30 minutes before departure*\n"
                f"🎒 *What to bring:* Swimwear, sunscreen, towel, camera\n\n"
                f"We'll send you a reminder before your tour! 🔔\n\n"
                f"Thank you for choosing Al Bahr Sea Tours! 🌊"
            )
            
            # Clear sessions
            if phone_number in booking_sessions:
                del booking_sessions[phone_number]
            if phone_number in user_sessions:
                user_sessions[phone_number]['state'] = 'WELCOME'
            
            return send_whatsapp_message(phone_number, confirmation_msg)
        else:
            return send_whatsapp_message(phone_number, "❌ Failed to save booking. Please contact us directly at +968 24 123456")
            
    except Exception as e:
        logger.error(f"Error confirming booking: {str(e)}")
        return send_whatsapp_message(phone_number, "❌ Error confirming booking. Please contact us directly.")

def cancel_booking_process(phone_number):
    """Cancel the current booking process"""
    try:
        if phone_number in booking_sessions:
            del booking_sessions[phone_number]
        if phone_number in user_sessions:
            user_sessions[phone_number]['state'] = 'WELCOME'
            
        cancel_msg = (
            "❌ Booking cancelled.\n\n"
            "No problem! Feel free to start over anytime when you're ready. 🚤\n\n"
            "We're here to help you plan the perfect sea adventure! 🌊"
        )
        
        return send_whatsapp_message(phone_number, cancel_msg)
    except Exception as e:
        logger.error(f"Error cancelling booking: {str(e)}")
        return send_whatsapp_message(phone_number, "Booking cancelled.")

def send_tour_information(phone_number):
    """Send general tour information"""
    info_msg = (
        "🚤 *Al Bahr Sea Tours - Adventure Awaits!*\n\n"
        
        "🐬 *Dolphin Watching Tour*\n"
        "Watch dolphins play in their natural habitat\n"
        "⏰ 2-3 hours | 💰 20 OMR/person\n\n"
        
        "🤿 *Snorkeling Adventure* \n"
        "Explore vibrant coral reefs and marine life\n"
        "⏰ 3-4 hours | 💰 25 OMR/person\n\n"
        
        "🎣 *Fishing Trip*\n"
        "Traditional fishing experience in Omani waters\n" 
        "⏰ 4-5 hours | 💰 30 OMR/person\n\n"
        
        "🌅 *Sunset Cruise*\n"
        "Relaxing cruise during beautiful sunset\n"
        "⏰ 2 hours | 💰 15 OMR/person\n\n"
        
        "✅ *All tours include:*\n"
        "• Professional guide\n• Safety equipment\n• Refreshments\n• Insurance\n\n"
        "Ready to book your adventure? 🎉"
    )
    
    # Log info inquiry with proper details
    add_lead_to_sheet(
        name="Tour Info Inquiry", 
        contact=phone_number,
        intent="Detailed Tour Information", 
        whatsapp_id=phone_number,
        notes="Requested comprehensive tour information and pricing"
    )
    
    user_sessions[phone_number]['state'] = 'VIEWING_INFO'
    
    # Send interactive buttons after info
    interactive_data = {
        "type": "button",
        "body": {
            "text": info_msg
        },
        "action": {
            "buttons": [
                {
                    "type": "reply",
                    "reply": {
                        "id": "view_tours",
                        "title": "🚤 View Tours"
                    }
                },
                {
                    "type": "reply",
                    "reply": {
                        "id": "contact",
                        "title": "📞 Contact"
                    }
                }
            ]
        }
    }
    
    return send_whatsapp_message(phone_number, "", interactive_data)

def send_contact_info(phone_number):
    """Send contact information"""
    contact_msg = (
        "📞 *Contact Al Bahr Sea Tours*\n\n"
        "📍 *Location:*\n"
        "Marina Bandar Al Rowdha, Muscat, Oman\n\n"
        "📱 *Phone:* +968 24 123456\n"
        "📧 *Email:* info@albahrseatours.com\n"
        "🌐 *Website:* www.albahrseatours.com\n\n"
        "🕒 *Operating Hours:*\n"
        "Daily: 7:00 AM - 7:00 PM\n\n"
        "We're here to help you plan your perfect sea adventure! 🌊"
    )
    
    # Log contact inquiry with proper details
    add_lead_to_sheet(
        name="Contact Inquiry",
        contact=phone_number, 
        intent="Contact Request",
        whatsapp_id=phone_number,
        notes="Requested contact information and location details"
    )
    
    user_sessions[phone_number]['state'] = 'VIEWING_CONTACT'
    
    return send_whatsapp_message(phone_number, contact_msg)

def send_pricing_info(phone_number):
    """Send detailed pricing information"""
    pricing_msg = (
        "💰 *Tour Prices & Packages*\n\n"
        
        "🐬 *Dolphin Watching:* 20 OMR/person\n"
        "• 2-3 hours\n• Small groups\n• Refreshments included\n\n"
        
        "🤿 *Snorkeling Adventure:* 25 OMR/person\n"
        "• 3-4 hours\n• Full equipment\n• Professional guide\n\n"
        
        "🎣 *Fishing Trip:* 30 OMR/person\n"
        "• 4-5 hours\n• Fishing gear & bait\n• Expert guidance\n\n"
        
        "🌅 *Sunset Cruise:* 15 OMR/person\n"
        "• 2 hours\n• Scenic views\n• Refreshments\n\n"
        
        "👨‍👩‍👧‍👦 *Special Offers:*\n"
        "• Family Package (4+ people): 10% discount\n"
        "• Group Booking (6+ people): 15% discount\n"
        "• Children under 12: 50% discount\n\n"
        "💎 *All prices include safety equipment and professional guides*"
    )
    
    add_lead_to_sheet(
        name="Pricing Inquiry",
        contact=phone_number,
        intent="Pricing Information", 
        whatsapp_id=phone_number,
        notes="Requested detailed pricing and package information"
    )
    
    user_sessions[phone_number]['state'] = 'VIEWING_PRICING'
    
    return send_whatsapp_message(phone_number, pricing_msg)

# ==============================
# INTERACTION HANDLER - COMPLETE
# ==============================

def handle_interaction(phone_number, interaction_id):
    """Handle all interactive messages (buttons and lists)"""
    logger.info(f"🔄 Handling interaction: {interaction_id} from {phone_number}")
    
    try:
        # Update user session activity
        if phone_number not in user_sessions:
            user_sessions[phone_number] = {'state': 'WELCOME', 'data': {}}
        user_sessions[phone_number]['last_active'] = get_oman_time()
        
        # Main menu interactions
        if interaction_id == "view_tours":
            return send_main_tours_list(phone_number)
            
        elif interaction_id == "tour_info":
            return send_tour_information(phone_number)
            
        elif interaction_id == "contact":
            return send_contact_info(phone_number)
            
        elif interaction_id == "pricing_info":
            return send_pricing_info(phone_number)
            
        elif interaction_id == "book_now":
            return start_booking_flow(phone_number)
            
        elif interaction_id == "contact_info":
            return send_contact_info(phone_number)
        
        # Tour selection interactions
        elif interaction_id in ["dolphin_tour", "snorkeling_tour", "fishing_tour", "sunset_tour"]:
            tour_key = interaction_id.replace("_tour", "")
            return send_tour_details(phone_number, tour_key)
        
        # Tour booking from details page
        elif interaction_id.startswith("book_"):
            tour_key = interaction_id.replace("book_", "")
            return start_booking_flow(phone_number, tour_key)
        
        # Navigation interactions
        elif interaction_id == "more_tours":
            return send_main_tours_list(phone_number)
            
        elif interaction_id == "main_menu":
            return send_welcome_message(phone_number)
        
        # Date selection interactions
        elif interaction_id.startswith("date_") and "|" in interaction_id:
            date_option, target_phone = interaction_id.split("|")
            if target_phone == phone_number:
                return handle_booking_date_selection(phone_number, date_option)
        
        # Time selection interactions  
        elif interaction_id.startswith("time_") and "|" in interaction_id:
            time_option, target_phone = interaction_id.split("|")
            if target_phone == phone_number:
                return handle_time_selection(phone_number, time_option)
        
        # People selection interactions
        elif interaction_id.startswith("people_") and "|" in interaction_id:
            people_option, target_phone = interaction_id.split("|")
            if target_phone == phone_number:
                return handle_people_selection(phone_number, people_option)
        
        # Booking confirmation interactions
        elif interaction_id == "confirm_booking":
            return confirm_booking_final(phone_number)
            
        elif interaction_id == "cancel_booking":
            return cancel_booking_process(phone_number)
        
        # Default fallback
        else:
            logger.warning(f"Unknown interaction ID: {interaction_id}")
            return send_welcome_message(phone_number)
            
    except Exception as e:
        logger.error(f"Error handling interaction: {str(e)}")
        return send_welcome_message(phone_number)

# ==============================
# TEXT MESSAGE HANDLER - COMPLETE
# ==============================

def handle_text_message(phone_number, text):
    """Handle incoming text messages with complete session management"""
    text_lower = text.strip().lower()
    logger.info(f"💬 Handling text: '{text}' from {phone_number}")
    
    # Initialize user session if not exists
    if phone_number not in user_sessions:
        user_sessions[phone_number] = {
            'state': 'WELCOME',
            'data': {},
            'last_active': get_oman_time()
        }
    
    # Update last activity
    user_sessions[phone_number]['last_active'] = get_oman_time()
    
    # Handle admin commands first (with proper admin detection)
    if any(text_lower.startswith(cmd) for cmd in ['reminder', 'stats', 'help']):
        is_admin_command, admin_result = handle_admin_command(phone_number, text)
        if is_admin_command:
            send_whatsapp_message(phone_number, admin_result)
            return
    
    # Check if user is in booking flow
    if phone_number in booking_sessions:
        session = booking_sessions[phone_number]
        current_step = session.get('step')
        
        if current_step == 'awaiting_name':
            return handle_booking_name(phone_number, text)
            
        elif current_step == 'awaiting_contact':
            return handle_booking_contact(phone_number, text)
            
        elif current_step == 'awaiting_custom_date':
            return handle_custom_date_input(phone_number, text)
            
        elif current_step == 'awaiting_custom_people':
            return handle_custom_people_input(phone_number, text)
            
        elif current_step == 'awaiting_confirmation':
            if text_lower in ['yes', 'y', 'confirm']:
                return confirm_booking_final(phone_number)
            elif text_lower in ['no', 'n', 'cancel']:
                return cancel_booking_process(phone_number)
            else:
                return send_whatsapp_message(phone_number, "Please reply 'YES' to confirm or 'NO' to cancel your booking.")
    
    # Handle quick commands regardless of state
    if text_lower in ['hi', 'hello', 'hey', 'start', 'menu']:
        return send_welcome_message(phone_number)
        
    elif text_lower in ['book', 'booking', 'reservation']:
        return send_main_tours_list(phone_number)
        
    elif text_lower in ['info', 'information', 'tours']:
        return send_tour_information(phone_number)
        
    elif text_lower in ['contact', 'call', 'phone']:
        return send_contact_info(phone_number)
        
    elif text_lower in ['price', 'pricing', 'cost']:
        return send_pricing_info(phone_number)
    
    # Handle keyword-based inquiries
    elif any(word in text_lower for word in ['where', 'location', 'address']):
        location_msg = (
            "📍 *Our Location:*\n\n"
            "🏖️ Al Bahr Sea Tours\n"
            "Marina Bandar Al Rowdha\n"
            "Muscat, Oman\n\n"
            "🗺️ *Google Maps:*\n"
            "https://maps.app.goo.gl/albahrseatours\n\n"
            "We're easy to find at the beautiful Bandar Al Rowdha Marina! 🚤"
        )
        return send_whatsapp_message(phone_number, location_msg)
    
    elif any(word in text_lower for word in ['time', 'schedule', 'hour']):
        schedule_msg = (
            "🕒 *Tour Schedule:*\n\n"
            "🌅 *Morning Sessions:*\n"
            "• 8:00 AM - Dolphin Watching\n"
            "• 9:00 AM - Snorkeling\n"
            "• 10:00 AM - Dolphin Watching\n\n"
            "🌇 *Afternoon Sessions:*\n"
            "• 2:00 PM - Fishing Trip\n"
            "• 4:00 PM - Sunset Cruise\n"
            "• 6:00 PM - Sunset Cruise\n\n"
            "📅 *Advanced booking recommended!*"
        )
        return send_whatsapp_message(phone_number, schedule_msg)
    
    # Default response for unrecognized text
    unknown_msg = (
        "🤔 I'm not sure what you're looking for.\n\n"
        "Here are some things I can help you with:\n"
        "• Book a tour 🚤\n"
        "• Get tour information ℹ️\n"
        "• Contact details 📞\n"
        "• Pricing information 💰\n\n"
        "Just type 'menu' to see all options! 📋"
    )
    return send_whatsapp_message(phone_number, unknown_msg)

# ==============================
# WEBHOOK ENDPOINTS - COMPLETE
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
    """Handle incoming WhatsApp messages and interactions - COMPLETE FIX"""
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
        
        logger.info(f"📱 Message from: {phone_number}")
        
        # Check for admin commands first (FIXED - admin can now interact as customer)
        if "text" in message:
            text = message["text"]["body"].strip()
            
            # DEBUG: Log admin check
            clean_admin = clean_oman_number(ADMIN_NUMBER)
            clean_sender = clean_oman_number(phone_number)
            logger.info(f"🔧 Admin check - Sender: {clean_sender}, Admin: {clean_admin}")
            
            # Check if sender is admin
            admin_variations = [
                clean_admin,
                clean_admin.replace('968', ''),  # Without country code
                '968' + clean_admin.replace('968', '') if not clean_admin.startswith('968') else clean_admin
            ]
            
            if clean_sender in admin_variations:
                logger.info(f"✅ Admin detected: {clean_sender}")
                # Check if it's a known admin command
                command = text.lower()
                if any(command.startswith(cmd) for cmd in ['reminder', 'stats', 'help']):
                    is_admin_command, admin_result = handle_admin_command(phone_number, text)
                    if is_admin_command:
                        send_whatsapp_message(phone_number, admin_result)
                        return jsonify({"status": "admin_command_handled"})
                else:
                    # Admin sent regular message - process as customer
                    handle_text_message(phone_number, text)
                    return jsonify({"status": "admin_regular_message"})
            else:
                # Regular user - process normally
                handle_text_message(phone_number, text)
                return jsonify({"status": "user_message_processed"})
        
        # Handle interactive messages
        elif "interactive" in message:
            interactive_data = message["interactive"]
            interactive_type = interactive_data["type"]
            
            if interactive_type == "list_reply":
                option_id = interactive_data["list_reply"]["id"]
                handle_interaction(phone_number, option_id)
                return jsonify({"status": "list_handled"})
            
            elif interactive_type == "button_reply":
                button_id = interactive_data["button_reply"]["id"]
                handle_interaction(phone_number, button_id)
                return jsonify({"status": "button_handled"})
        
        # If no text message or other types, send welcome
        send_welcome_message(phone_number)
        return jsonify({"status": "welcome_sent"})
        
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
        "timestamp": format_oman_timestamp(),
        "display_time": format_oman_time_display(),
        "whatsapp_configured": bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_ID),
        "sheets_available": sheet is not None,
        "active_sessions": len(booking_sessions),
        "user_sessions": len(user_sessions),
        "reminders_scheduled": len([s for s in booking_reminders.values() if s.get('reminder_scheduled')]),
        "admin_number": ADMIN_NUMBER,
        "admin_clean": clean_oman_number(ADMIN_NUMBER),
        "version": "8.0 - PERFECTION ACHIEVED - All Features Working"
    }
    return jsonify(status)

@app.route("/api/stats", methods=["GET"])
def api_stats():
    """API endpoint for statistics"""
    return jsonify({"stats": get_booking_stats()})

@app.route("/", methods=["GET"])
def home():
    """Home page"""
    return jsonify({
        "message": "Al Bahr Sea Tours WhatsApp Bot API - PERFECTION",
        "status": "Running",
        "timestamp": format_oman_timestamp(),
        "version": "8.0",
        "features": "Complete booking flow, Interactive lists, Reminders, Admin commands, Oman timezone"
    })

# ==============================
# RUN APPLICATION
# ==============================

if __name__ == "__main__":
    # Start the reminder system
    start_reminder_checker()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)