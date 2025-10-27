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
        required_headers = ['Timestamp', 'Name', 'Contact', 'WhatsApp ID', 'Intent', 'Tour Type', 'Booking Date', 'Booking Time', 'Adults Count', 'Children Count', 'Total Guests', 'Language']
        if current_headers != required_headers:
            sheet.clear()
            sheet.append_row(required_headers)
            logger.info("✅ Updated Google Sheets headers")
    except:
        # If sheet is empty, add headers
        sheet.append_row(['Timestamp', 'Name', 'Contact', 'WhatsApp ID', 'Intent', 'Tour Type', 'Booking Date', 'Booking Time', 'Adults Count', 'Children Count', 'Total Guests', 'Language'])
    
    logger.info("✅ Google Sheets initialized successfully")
except Exception as e:
    logger.error(f"❌ Google Sheets initialization failed: {str(e)}")
    sheet = None

# Simple session management
booking_sessions = {}

# ==============================
# MESSAGE STORAGE FOR TWO-WAY CHAT - ENHANCED
# ==============================
chat_messages = {}  # Format: { phone_number: [ {message, sender, timestamp}, ... ] }

# Track admin messages to prevent bot responses to admin-initiated conversations
admin_message_tracker = {}

def store_message(phone_number, message, sender):
    """Store message in chat history with proper formatting"""
    try:
        clean_phone = clean_oman_number(phone_number)
        if not clean_phone:
            return False
            
        if clean_phone not in chat_messages:
            chat_messages[clean_phone] = []
        
        # Create message entry with proper timestamp
        message_entry = {
            'message': message,
            'sender': sender,  # 'user' or 'admin'
            'timestamp': datetime.datetime.now().isoformat(),
            'id': len(chat_messages[clean_phone]) + 1  # Add unique ID for tracking
        }
            
        chat_messages[clean_phone].append(message_entry)
        
        # Keep only last 200 messages per user to prevent memory issues
        if len(chat_messages[clean_phone]) > 200:
            chat_messages[clean_phone] = chat_messages[clean_phone][-200:]
            
        logger.info(f"💬 Stored {sender} message for {clean_phone}: {message[:50]}...")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error storing message: {str(e)}")
        return False

def get_user_messages(phone_number):
    """Get complete chat history for a user, sorted by timestamp"""
    try:
        clean_phone = clean_oman_number(phone_number)
        if not clean_phone:
            return []
            
        messages = chat_messages.get(clean_phone, [])
        # Sort messages by timestamp to ensure correct order
        messages.sort(key=lambda x: x['timestamp'])
        return messages
        
    except Exception as e:
        logger.error(f"❌ Error getting user messages: {str(e)}")
        return []

def get_all_chat_users():
    """Get all users who have chat history"""
    try:
        users = []
        for phone, messages in chat_messages.items():
            if messages:
                last_message = messages[-1]
                users.append({
                    'phone_number': phone,
                    'last_message': last_message['message'],
                    'last_sender': last_message['sender'],
                    'last_timestamp': last_message['timestamp'],
                    'message_count': len(messages)
                })
        return users
    except Exception as e:
        logger.error(f"❌ Error getting chat users: {str(e)}")
        return []

# ==============================
# ARABIC LANGUAGE SUPPORT
# ==============================

# Arabic translations for all bot messages
ARABIC_MESSAGES = {
    "welcome": "🌊 مرحباً بكم في جولات البحر للرحلات البحرية!\n\nاختر لغتك المفضلة / Choose your preferred language:",
    
    "booking_start": "📝 *لنحجز رحلتك!* 🎫\n\nسأساعدك في حجز رحلتك البحرية. 🌊\n\nأولاً، الرجاء إرسال:\n\n👤 *الاسم الكامل*\n\n*مثال:*\nأحمد الحارثي",
    
    "ask_contact": "ممتاز، {}! 👋\n\nالآن الرجاء إرسال:\n\n📞 *رقم الهاتف*\n\n*مثال:*\n91234567",
    
    "ask_adults": "👥 *عدد البالغين*\n\nاختيار رائع! {} سيكون! 🎯\n\nكم عدد *البالغين* (12 سنة فما فوق) الذين سينضمون؟\n\nالرجاء إرسال الرقم:\n*أمثلة:* 2, 4, 6",
    
    "ask_children": "👶 *عدد الأطفال*\n\nالبالغين: {}\n\nكم عدد *الأطفال* (أقل من 12 سنة) الذين سينضمون؟\n\nالرجاء إرسال الرقم:\n*أمثلة:* 0, 1, 2\n\nإذا لم يكن هناك أطفال، أرسل فقط: 0",
    
    "ask_date": "📅 *التاريخ المفضل*\n\nممتاز! {} ضيوف إجمالاً:\n• {} بالغين\n• {} أطفال\n\nالرجاء إرسال *التاريخ المفضل*:\n\n📋 *أمثلة على التنسيق:*\n• **غداً**\n• **29 أكتوبر**\n• **الجمعة القادمة**\n• **15 نوفمبر**\n• **2024-12-25**\n\nسنتحقق من التوفر لتاريخك المختار! 📅",
    
    "booking_complete": "🎉 *تم تأكيد الحجز!* ✅\n\nشكراً {}! تم حجز رحلتك بنجاح. 🐬\n\n📋 *تفاصيل الحجز:*\n👤 الاسم: {}\n📞 الاتصال: {}\n🚤 الجولة: {}\n👥 الضيوف: {} إجمالاً\n   • {} بالغين\n   • {} أطفال\n📅 التاريخ: {}\n🕒 الوقت: {}\n\n💰 *المجموع: {} ريال عماني*\n\nسيتصل بك فريقنا خلال ساعة واحدة لتأكيد التفاصيل. ⏰\nللمساعدة الفورية: +968 24 123456 📞\n\nاستعد لمغامرة بحرية رائعة! 🌊",
    
    "tour_descriptions": {
        "Dolphin Watching": "🐬 *جولة مشاهدة الدلافين* 🌊\n\n*جولة لمدة ساعتين - 25 ريال عماني للبالغ*\n(خصم 50٪ للأطفال تحت 12 سنة)\n\n*المشمول:*\n• مرشد بحري خبير 🧭\n• معدات السلامة 🦺\n• المرطبات والمياه 🥤\n• فرص التصوير 📸\n\n*أفضل وقت:* جولات الصباح (8 صباحاً، 10 صباحاً)",
        "Snorkeling": "🤿 *مغامرة الغوص* 🐠\n\n*جولة لمدة 3 ساعات - 35 ريال عماني للبالغ*\n(خصم 50٪ للأطفال تحت 12 سنة)\n\n*المشمول:*\n• معدات الغوص الكاملة 🤿\n• مرشد محترف 🧭\n• معدات السلامة 🦺\n• وجبات خفيفة ومرطبات 🍎🥤",
        "Dhow Cruise": "⛵ *رحلة القارب التقليدي* 🌅\n\n*جولة لمدة ساعتين - 40 ريال عماني للبالغ*\n(خصم 50٪ للأطفال تحت 12 سنة)\n\n*المشمول:*\n• رحلة قارب عماني تقليدي ⛵\n• مشاهد الغروب 🌅\n• عشاء عماني 🍽️\n• مشروبات 🥤",
        "Fishing Trip": "🎣 *رحلة صيد* 🐟\n\n*جولة لمدة 4 ساعات - 50 ريال عماني للبالغ*\n(خصم 50٪ للأطفال تحت 12 سنة)\n\n*المشمOL:*\n• معدات الصيد المحترفة 🎣\n• الطعم 🪱\n• مرشد صيد خبير 🧭\n• مرطبات ووجبات خفيفة 🥤🍎"
    },
    
    "pricing": "💰 *أسعار الجولات والباقات* 💵\n\n🐬 *مشاهدة الدلافين:* 25 ريال عماني للبالغ\n🤿 *الغوص:* 35 ريال عماني للبالغ\n⛵ *رحلة القارب:* 40 ريال عماني للبالغ\n🎣 *رحلة الصيد:* 50 ريال عماني للبالغ\n\n👨‍👩‍👧‍👦 *عروض خاصة:*\n• الأطفال تحت 12 سنة: خصم 50٪\n• مجموعة 4+ أشخاص: خصم 10٪",
    
    "location": "📍 *موقعنا والتوجيهات* 🗺️\n\n🏖️ *جولات البحر للرحلات البحرية*\nمارينا بندر الروضة\nمسقط، سلطنة عمان\n\n🗺️ *خرائط جوجل:*\nhttps://maps.app.goo.gl/albahrseatours\n\n🚗 *مواقف سيارات:* متوفرة في المارينا\n⏰ *ساعات العمل:* 7:00 صباحاً - 7:00 مساءً يومياً"
}

# Arabic to English mapping for common responses
ARABIC_TO_ENGLISH = {
    # Common names
    "أحمد": "Ahmed",
    "محمد": "Mohammed", 
    "خالد": "Khalid",
    "مريم": "Maryam",
    "فاطمة": "Fatima",
    
    # Common responses
    "نعم": "Yes",
    "لا": "No",
    "غداً": "Tomorrow",
    "بكرا": "Tomorrow",
    "اليوم": "Today"
}

def translate_arabic_to_english(text):
    """Simple Arabic to English translation for common words/phrases"""
    if not text or not any('\u0600' <= char <= '\u06FF' for char in text):
        return text  # Return as is if no Arabic characters
    
    # Simple word-by-word translation
    words = text.split()
    translated_words = []
    
    for word in words:
        # Remove any punctuation for matching
        clean_word = re.sub(r'[^\w\u0600-\u06FF]', '', word)
        if clean_word in ARABIC_TO_ENGLISH:
            translated_words.append(ARABIC_TO_ENGLISH[clean_word])
        else:
            translated_words.append(word)
    
    return ' '.join(translated_words)

def get_user_language(phone_number):
    """Get user's preferred language from session"""
    session = booking_sessions.get(phone_number, {})
    return session.get('language', 'english')

def send_language_selection(to):
    """Send language selection menu"""
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "🌊 Al Bahr Sea Tours"
        },
        "body": {
            "text": ARABIC_MESSAGES["welcome"]
        },
        "action": {
            "button": "🌐 Select Language",
            "sections": [
                {
                    "title": "Choose Language / اختر اللغة",
                    "rows": [
                        {
                            "id": "lang_english",
                            "title": "🇺🇸 English",
                            "description": "Continue in English"
                        },
                        {
                            "id": "lang_arabic", 
                            "title": "🇴🇲 العربية",
                            "description": "المتابعة باللغة العربية"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

# ==============================
# HELPER FUNCTIONS
# ==============================

def add_lead_to_sheet(name, contact, intent, whatsapp_id, tour_type="Not specified", booking_date="Not specified", booking_time="Not specified", adults_count="0", children_count="0", total_guests="0", language="english"):
    """Add user entry to Google Sheet"""
    try:
        # Translate Arabic inputs to English for sheet storage
        translated_name = translate_arabic_to_english(name)
        translated_tour_type = translate_arabic_to_english(tour_type)
        translated_booking_date = translate_arabic_to_english(booking_date)
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
        sheet.append_row([timestamp, translated_name, contact, whatsapp_id, intent, translated_tour_type, translated_booking_date, booking_time, adults_count, children_count, total_guests, language])
        logger.info(f"✅ Added lead to sheet: {translated_name}, {contact}, {intent}, Language: {language}")
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

def send_welcome_message(to, language='english'):
    """Send appropriate welcome message based on language"""
    if language == 'arabic':
        send_main_options_list_arabic(to)
    else:
        send_main_options_list(to)

def send_main_options_list(to):
    """Send ALL options in one list - English version"""
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

def send_main_options_list_arabic(to):
    """Send ALL options in one list - Arabic version"""
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "🌊 جولات البحر للرحلات البحرية"
        },
        "body": {
            "text": "مرحباً بكم في شركة عمان الرائدة في المغامرات البحرية! 🚤\n\nاختر مغامرتك البحرية: 🗺️"
        },
        "action": {
            "button": "🌊 عرض الجولات",
            "sections": [
                {
                    "title": "🚤 الجولات الشعبية",
                    "rows": [
                        {
                            "id": "dolphin_tour_ar",
                            "title": "🐬 مشاهدة الدلافين",
                            "description": "السباحة مع الدلافين في بيئتها الطبيعية"
                        },
                        {
                            "id": "snorkeling_ar", 
                            "title": "🤿 الغوص",
                            "description": "استكشاف الشعاب المرجانية والحياة البحرية"
                        },
                        {
                            "id": "dhow_cruise_ar",
                            "title": "⛵ رحلة القارب", 
                            "description": "تجربة غروب الشمس على القارب العماني التقليدي"
                        },
                        {
                            "id": "fishing_ar",
                            "title": "🎣 رحلة صيد",
                            "description": "مغامرة صيد في أعماق البحر"
                        }
                    ]
                },
                {
                    "title": "ℹ️ المعلومات والحجز",
                    "rows": [
                        {
                            "id": "pricing_ar",
                            "title": "💰 الأسعار",
                            "description": "أسعار الجولات والباقات"
                        },
                        {
                            "id": "location_ar",
                            "title": "📍 الموقع",
                            "description": "عنوان المارينا والتوجيهات"
                        },
                        {
                            "id": "schedule_ar",
                            "title": "🕒 الجدول",
                            "description": "مواعيد الجولات والتوفر"
                        },
                        {
                            "id": "contact_ar",
                            "title": "📞 اتصل بنا",
                            "description": "تواصل مع فريقنا"
                        },
                        {
                            "id": "book_now_ar",
                            "title": "📅 احجز الآن", 
                            "description": "احجز مغامرتك البحرية"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def start_booking_flow(to, language='english'):
    """Start the booking flow by asking for name"""
    # Clear any existing session
    if to in booking_sessions:
        del booking_sessions[to]
    
    # Create new session
    booking_sessions[to] = {
        'step': 'awaiting_name',
        'flow': 'booking',
        'language': language,
        'created_at': datetime.datetime.now().isoformat()
    }
    
    if language == 'arabic':
        message = ARABIC_MESSAGES["booking_start"]
    else:
        message = "📝 *Let's Book Your Tour!* 🎫\n\nI'll help you book your sea adventure. 🌊\n\nFirst, please send me your:\n\n👤 *Full Name*\n\n*Example:*\nAhmed Al Harthy"
    
    send_whatsapp_message(to, message)

def ask_for_contact(to, name, language='english'):
    """Ask for contact after getting name"""
    # Update session with name
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_contact',
            'name': name
        })
    
    if language == 'arabic':
        message = ARABIC_MESSAGES["ask_contact"].format(name)
    else:
        message = f"Perfect, {name}! 👋\n\nNow please send me your:\n\n📞 *Phone Number*\n\n*Example:*\n91234567"
    
    send_whatsapp_message(to, message)

def ask_for_tour_type(to, name, contact, language='english'):
    """Ask for tour type using interactive list"""
    # Update session with contact
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_tour_type',
            'name': name,
            'contact': contact
        })
    
    if language == 'arabic':
        interactive_data = {
            "type": "list",
            "header": {
                "type": "text",
                "text": "🚤 اختر جولتك"
            },
            "body": {
                "text": f"ممتاز {name}! أي جولة تريد حجزها؟"
            },
            "action": {
                "button": "اختر الجولة",
                "sections": [
                    {
                        "title": "الجولات المتاحة",
                        "rows": [
                            {
                                "id": f"book_dolphin_ar|{name}|{contact}",
                                "title": "🐬 مشاهدة الدلافين",
                                "description": "ساعتين • 25 ريال عماني للشخص"
                            },
                            {
                                "id": f"book_snorkeling_ar|{name}|{contact}", 
                                "title": "🤿 الغوص",
                                "description": "3 ساعات • 35 ريال عماني للشخص"
                            },
                            {
                                "id": f"book_dhow_ar|{name}|{contact}",
                                "title": "⛵ رحلة القارب", 
                                "description": "ساعتين • 40 ريال عماني للشخص"
                            },
                            {
                                "id": f"book_fishing_ar|{name}|{contact}",
                                "title": "🎣 رحلة صيد",
                                "description": "4 ساعات • 50 ريال عماني للشخص"
                            }
                        ]
                    }
                ]
            }
        }
    else:
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

def ask_for_adults_count(to, name, contact, tour_type, language='english'):
    """Ask for number of adults"""
    # Update session with tour type
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_adults_count',
            'name': name,
            'contact': contact,
            'tour_type': tour_type
        })
    
    if language == 'arabic':
        message = ARABIC_MESSAGES["ask_adults"].format(tour_type)
    else:
        message = f"👥 *Number of Adults*\n\nGreat choice! {tour_type} it is! 🎯\n\nHow many *adults* (12 years and above) will be joining?\n\nPlease send the number:\n*Examples:* 2, 4, 6"
    
    send_whatsapp_message(to, message)

def ask_for_children_count(to, name, contact, tour_type, adults_count, language='english'):
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
    
    if language == 'arabic':
        message = ARABIC_MESSAGES["ask_children"].format(adults_count)
    else:
        message = f"👶 *Number of Children*\n\nAdults: {adults_count}\n\nHow many *children* (below 12 years) will be joining?\n\nPlease send the number:\n*Examples:* 0, 1, 2\n\nIf no children, just send: 0"
    
    send_whatsapp_message(to, message)

def ask_for_date(to, name, contact, tour_type, adults_count, children_count, language='english'):
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
    
    if language == 'arabic':
        message = ARABIC_MESSAGES["ask_date"].format(total_guests, adults_count, children_count)
    else:
        message = f"📅 *Preferred Date*\n\nPerfect! {total_guests} guests total:\n• {adults_count} adults\n• {children_count} children\n\nPlease send your *preferred date*:\n\n📋 *Format Examples:*\n• **Tomorrow**\n• **October 29**\n• **Next Friday**\n• **15 November**\n• **2024-12-25**\n\nWe'll check availability for your chosen date! 📅"
    
    send_whatsapp_message(to, message)

def ask_for_time(to, name, contact, tour_type, adults_count, children_count, booking_date, language='english'):
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
    
    if language == 'arabic':
        interactive_data = {
            "type": "list",
            "header": {
                "type": "text",
                "text": "🕒 الوقت المفضل"
            },
            "body": {
                "text": f"ممتاز! {booking_date} لـ {tour_type}.\n\n{total_guests} ضيوف:\n• {adults_count} بالغين\n• {children_count} أطفال\n\nاختر الوقت المفضل:"
            },
            "action": {
                "button": "اختر الوقت",
                "sections": [
                    {
                        "title": "جولات الصباح",
                        "rows": [
                            {
                                "id": f"time_8am_ar|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}",
                                "title": "🌅 8:00 صباحاً",
                                "description": "مغامرة الصباح الباكر"
                            },
                            {
                                "id": f"time_9am_ar|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}", 
                                "title": "☀️ 9:00 صباحاً",
                                "description": "جولة الصباح"
                            },
                            {
                                "id": f"time_10am_ar|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}",
                                "title": "🌞 10:00 صباحاً", 
                                "description": "آخر الصباح"
                            }
                        ]
                    },
                    {
                        "title": "جولات الظهيرة",
                        "rows": [
                            {
                                "id": f"time_2pm_ar|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}",
                                "title": "🌇 2:00 ظهراً",
                                "description": "مغامرة الظهيرة"
                            },
                            {
                                "id": f"time_4pm_ar|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}",
                                "title": "🌅 4:00 عصراً",
                                "description": "آخر الظهيرة"
                            },
                            {
                                "id": f"time_6pm_ar|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}",
                                "title": "🌆 6:00 مساءً",
                                "description": "جولة المساء"
                            }
                        ]
                    }
                ]
            }
        }
    else:
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

def complete_booking(to, name, contact, tour_type, adults_count, children_count, booking_date, booking_time, language='english'):
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
        total_guests=str(total_guests),
        language=language
    )
    
    # Clear the session
    if to in booking_sessions:
        del booking_sessions[to]
    
    # Send confirmation message
    price = calculate_price(tour_type, adults_count, children_count)
    
    if language == 'arabic':
        if success:
            message = ARABIC_MESSAGES["booking_complete"].format(name, name, contact, tour_type, total_guests, adults_count, children_count, booking_date, booking_time, price)
        else:
            message = f"📝 *تم استلام الحجز!*\n\nشكراً {name}! لقد استلمنا طلب حجزك. 🐬\n\nسيتصل بك فريقنا خلال ساعة واحدة للتأكيد. 📞"
    else:
        if success:
            message = f"🎉 *Booking Confirmed!* ✅\n\nThank you {name}! Your tour has been booked successfully. 🐬\n\n📋 *Booking Details:*\n👤 Name: {name}\n📞 Contact: {contact}\n🚤 Tour: {tour_type}\n👥 Guests: {total_guests} total\n   • {adults_count} adults\n   • {children_count} children\n📅 Date: {booking_date}\n🕒 Time: {booking_time}\n\n💰 *Total: {price} OMR*\n\nOur team will contact you within 1 hour to confirm details. ⏰\nFor immediate assistance: +968 24 123456 📞\n\nGet ready for an amazing sea adventure! 🌊"
        else:
            message = f"📝 *Booking Received!*\n\nThank you {name}! We've received your booking request. 🐬\n\n📋 *Your Details:*\n👤 Name: {name}\n📞 Contact: {contact}\n🚤 Tour: {tour_type}\n👥 Guests: {total_guests} total\n   • {adults_count} adults\n   • {children_count} children\n📅 Date: {booking_date}\n🕒 Time: {booking_time}\n\nOur team will contact you within 1 hour to confirm. 📞"
    
    send_whatsapp_message(to, message)

def calculate_price(tour_type, adults_count, children_count):
    """Calculate tour price based on type and people count"""
    prices = {
        "Dolphin Watching": 25,
        "Snorkeling": 35,
        "Dhow Cruise": 40,
        "Fishing Trip": 50,
        "مشاهدة الدلافين": 25,
        "الغوص": 35,
        "رحلة القارب": 40,
        "رحلة صيد": 50
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

def handle_keyword_questions(text, phone_number, language='english'):
    """Handle direct keyword questions without menu"""
    text_lower = text.lower()
    
    # Location questions
    if any(word in text_lower for word in ['where', 'location', 'address', 'located', 'map', 'اين', 'موقع', 'عنوان']):
        if language == 'arabic':
            response = ARABIC_MESSAGES["location"]
        else:
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
    elif any(word in text_lower for word in ['price', 'cost', 'how much', 'fee', 'charge', 'سعر', 'كم', 'ثمن', 'تكلفة']):
        if language == 'arabic':
            response = ARABIC_MESSAGES["pricing"]
        else:
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
    elif any(word in text_lower for word in ['time', 'schedule', 'hour', 'when', 'available', 'وقت', 'موعد', 'جدول', 'متى']):
        if language == 'arabic':
            response = """🕒 *جدول الجولات والمواعيد:* ⏰

*مواعيد انطلاق الجولات اليومية:*
🌅 *جولات الصباح:*
• مشاهدة الدلافين: 8:00 صباحاً، 10:00 صباحاً
• الغوص: 9:00 صباحاً، 11:00 صباحاً

🌇 *جولات الظهيرة:*
• رحلات الصيد: 2:00 ظهراً
• رحلات القارب: 4:00 عصراً، 6:00 مساءً

📅 *يوصى بالحجز المسبق!*"""
        else:
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
    elif any(word in text_lower for word in ['contact', 'phone', 'call', 'number', 'whatsapp', 'اتصال', 'هاتف', 'رقم', 'اتصل']):
        if language == 'arabic':
            response = """📞 *اتصل بجولات البحر:* 📱

*هاتف:* +968 24 123456
*واتساب:* +968 9123 4567
*بريد إلكتروني:* info@albahrseatours.com

🌐 *الموقع:* www.albahrseatours.com

⏰ *ساعات خدمة العملاء:*
7:00 صباحاً - 7:00 مساءً يومياً

📍 *زورنا:*
مارينا بندر الروضة، مسقط"""
        else:
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
    
    # Get user language from session
    language = get_user_language(phone_number)
    
    # Check if it's a language selection
    if interaction_id == "lang_english":
        # Set English language
        if phone_number in booking_sessions:
            booking_sessions[phone_number]['language'] = 'english'
        else:
            booking_sessions[phone_number] = {'language': 'english'}
        
        send_welcome_message(phone_number, 'english')
        return True
        
    elif interaction_id == "lang_arabic":
        # Set Arabic language
        if phone_number in booking_sessions:
            booking_sessions[phone_number]['language'] = 'arabic'
        else:
            booking_sessions[phone_number] = {'language': 'arabic'}
        
        send_welcome_message(phone_number, 'arabic')
        return True
    
    # Check if it's a booking flow interaction
    if '|' in interaction_id:
        parts = interaction_id.split('|')
        action = parts[0]
        
        # Handle Arabic booking flows
        if action.startswith('book_') and len(parts) >= 3:
            # Tour type selection
            tour_type_map = {
                'book_dolphin': 'Dolphin Watching',
                'book_snorkeling': 'Snorkeling',
                'book_dhow': 'Dhow Cruise',
                'book_fishing': 'Fishing Trip',
                'book_dolphin_ar': 'مشاهدة الدلافين',
                'book_snorkeling_ar': 'الغوص',
                'book_dhow_ar': 'رحلة القارب',
                'book_fishing_ar': 'رحلة صيد'
            }
            
            tour_type = tour_type_map.get(action)
            name = parts[1]
            contact = parts[2]
            
            ask_for_adults_count(phone_number, name, contact, tour_type, language)
            return True
            
        elif action.startswith('time_') and len(parts) >= 7:
            # Time selection - complete booking
            time_map = {
                'time_8am': '8:00 AM',
                'time_9am': '9:00 AM',
                'time_10am': '10:00 AM',
                'time_2pm': '2:00 PM',
                'time_4pm': '4:00 PM',
                'time_6pm': '6:00 PM',
                'time_8am_ar': '8:00 صباحاً',
                'time_9am_ar': '9:00 صباحاً',
                'time_10am_ar': '10:00 صباحاً',
                'time_2pm_ar': '2:00 ظهراً',
                'time_4pm_ar': '4:00 عصراً',
                'time_6pm_ar': '6:00 مساءً'
            }
            
            booking_time = time_map.get(action, 'Not specified')
            name = parts[1]
            contact = parts[2]
            tour_type = parts[3]
            adults_count = parts[4]
            children_count = parts[5]
            booking_date = parts[6]
            
            complete_booking(phone_number, name, contact, tour_type, adults_count, children_count, booking_date, booking_time, language)
            return True
    
    # Regular menu interactions - Arabic versions
    if language == 'arabic':
        arabic_responses = {
            # Tour options in Arabic
            "dolphin_tour_ar": ARABIC_MESSAGES["tour_descriptions"]["Dolphin Watching"],
            "snorkeling_ar": ARABIC_MESSAGES["tour_descriptions"]["Snorkeling"],
            "dhow_cruise_ar": ARABIC_MESSAGES["tour_descriptions"]["Dhow Cruise"],
            "fishing_ar": ARABIC_MESSAGES["tour_descriptions"]["Fishing Trip"],
            
            # Information options in Arabic
            "pricing_ar": ARABIC_MESSAGES["pricing"],
            "location_ar": ARABIC_MESSAGES["location"],
            "schedule_ar": """🕒 *جدول الجولات والتوفر* 📅

*مواعيد الانطلاق اليومية:*

🌅 *مغامرات الصباح:*
• 8:00 صباحاً - مشاهدة الدلافين 🐬
• 9:00 صباحاً - الغوص 🤿
• 10:00 صباحاً - مشاهدة الدلافين 🐬
• 11:00 صباحاً - الغوص 🤿

🌇 *تجارب الظهيرة:*
• 2:00 ظهراً - رحلة صيد 🎣
• 4:00 عصراً - رحلة القارب ⛵
• 5:00 عصراً - دلافين الغروب 🐬

🌅 *سحر المساء:*
• 6:00 مساءً - رحلة القارب ⛵
• 6:30 مساءً - رحلة الغروب 🌅

📅 *يوصى بالحجز المسبق*
⏰ *التسجيل:* 30 دقيقة قبل الانطلاق""",
            
            "contact_ar": """📞 *اتصل بجولات البحر* 📱

*نحن هنا لمساعدتك في تخطيط مغامرة بحرية مثالية!* 🌊

📞 *هاتف:* +968 24 123456
📱 *واتساب:* +968 9123 4567
📧 *بريد إلكتروني:* info@albahrseatours.com

🌐 *الموقع:* www.albahrseatours.com

⏰ *ساعات خدمة العملاء:*
7:00 صباحاً - 7:00 مساءً يومياً

📍 *زورنا:*
مارينا بندر الروضة
مسقط، عمان""",
            
            "book_now_ar": lambda: start_booking_flow(phone_number, 'arabic')
        }
        
        response = arabic_responses.get(interaction_id)
        if callable(response):
            response()
            return True
        elif response:
            send_whatsapp_message(phone_number, response)
            return True
    
    # English menu interactions (existing code)
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

        "book_now": lambda: start_booking_flow(phone_number, 'english')
    }
    
    response = responses.get(interaction_id)
    
    if callable(response):
        response()
        return True
    elif response:
        send_whatsapp_message(phone_number, response)
        return True
    else:
        if language == 'arabic':
            send_whatsapp_message(phone_number, "عذراً، لم أفهم هذا الخيار. الرجاء الاختيار من القائمة. 📋")
        else:
            send_whatsapp_message(phone_number, "Sorry, I didn't understand that option. Please select from the menu. 📋")
        return False

# ==============================
# ADMIN CHAT INTERVENTION FUNCTIONS - ENHANCED
# ==============================

def send_admin_message(phone_number, message):
    """Send message as admin to specific user - CLEAN FORMATTING"""
    try:
        # Track that this is an admin-initiated message to prevent bot responses
        clean_phone = clean_oman_number(phone_number)
        if clean_phone:
            admin_message_tracker[clean_phone] = datetime.datetime.now().isoformat()
            logger.info(f"🔧 Admin message tracked for {clean_phone}")
        
        success = send_whatsapp_message(phone_number, message)
        
        if success:
            # Store the admin message in chat history with proper timestamp
            store_message(phone_number, message, 'admin')
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
            'booking_date': session.get('booking_date', 'Not selected'),
            'language': session.get('language', 'english'),
            'created_at': session.get('created_at', 'Unknown')
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
    """Handle incoming WhatsApp messages and interactions - ENHANCED CHAT STORAGE"""
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
        
        # Get user language
        language = get_user_language(phone_number)
        
        # STORE USER MESSAGE FOR TWO-WAY CHAT - ENHANCED
        if "text" in message:
            user_message = message["text"]["body"].strip()
            store_message(phone_number, user_message, 'user')
            logger.info(f"💬 Stored user message from {phone_number}: {user_message}")
        
        # Check if it's an interactive message (list or button)
        if "interactive" in message:
            interactive_data = message["interactive"]
            interactive_type = interactive_data["type"]
            
            if interactive_type == "list_reply":
                list_reply = interactive_data["list_reply"]
                option_id = list_reply["id"]
                
                # Store the interaction as a user message for chat history
                option_title = list_reply.get("title", option_id)
                store_message(phone_number, f"Selected: {option_title}", 'user')
                
                logger.info(f"📋 List option selected: {option_id} by {phone_number}")
                handle_interaction(option_id, phone_number)
                return jsonify({"status": "list_handled"})
            
            elif interactive_type == "button_reply":
                button_reply = interactive_data["button_reply"]
                button_id = button_reply["id"]
                
                # Store the interaction as a user message for chat history
                button_title = button_reply.get("title", button_id)
                store_message(phone_number, f"Clicked: {button_title}", 'user')
                
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
            
            # CHECK FOR RECENT ADMIN MESSAGES FIRST - PREVENT BOT INTERRUPTION
            clean_phone = clean_oman_number(phone_number)
            if clean_phone and clean_phone in admin_message_tracker:
                admin_time = datetime.datetime.fromisoformat(admin_message_tracker[clean_phone])
                current_time = datetime.datetime.now()
                time_diff = (current_time - admin_time).total_seconds()
                
                # If admin message was sent within the last 2 minutes, don't auto-respond
                if time_diff < 120:  # 2 minutes
                    logger.info(f"🔧 Skipping auto-response due to recent admin message to {clean_phone}")
                    # Remove from tracker after processing
                    del admin_message_tracker[clean_phone]
                    return jsonify({"status": "admin_conversation_ongoing"})
            
            # CHECK FOR LANGUAGE SELECTION FIRST - NEW USERS
            # If user has no session and sends any greeting, show language selection
            if not session:
                text_lower = text.lower()
                greetings_english = ["hi", "hello", "hey", "start", "menu", "hola", "good morning", "good afternoon", "good evening"]
                greetings_arabic = ["مرحبا", "اهلا", "السلام عليكم", "اهلين", "سلام", "مرحباً", "أهلاً", "السلام"]
                
                # Check if it's any kind of greeting
                is_greeting = (text_lower in greetings_english or 
                             any(ar_greeting in text for ar_greeting in greetings_arabic) or
                             text_lower in [g.lower() for g in greetings_arabic])
                
                if is_greeting:
                    send_language_selection(phone_number)
                    return jsonify({"status": "language_selection_sent"})
                
                # If it's not a greeting but contains Arabic characters, assume Arabic preference
                elif any('\u0600' <= char <= '\u06FF' for char in text):
                    # Auto-set to Arabic and send Arabic welcome
                    booking_sessions[phone_number] = {'language': 'arabic'}
                    send_welcome_message(phone_number, 'arabic')
                    return jsonify({"status": "auto_arabic_detected"})
                
                # First, check for keyword questions (unless in booking flow)
                if handle_keyword_questions(text, phone_number, language):
                    return jsonify({"status": "keyword_answered"})
            
            # Handle booking flow - name input
            if session and session.get('step') == 'awaiting_name':
                ask_for_contact(phone_number, text, language)
                return jsonify({"status": "name_received"})
            
            # Handle booking flow - contact input
            elif session and session.get('step') == 'awaiting_contact':
                name = session.get('name', '')
                ask_for_tour_type(phone_number, name, text, language)
                return jsonify({"status": "contact_received"})
            
            # Handle booking flow - adults count input
            elif session and session.get('step') == 'awaiting_adults_count':
                # Validate numeric input (works for both languages)
                if text.isdigit() and int(text) > 0:
                    name = session.get('name', '')
                    contact = session.get('contact', '')
                    tour_type = session.get('tour_type', '')
                    ask_for_children_count(phone_number, name, contact, tour_type, text, language)
                    return jsonify({"status": "adults_count_received"})
                else:
                    if language == 'arabic':
                        send_whatsapp_message(phone_number, "الرجاء إدخال عدد صحيح للبالغين (مثال: 2, 4, 6)")
                    else:
                        send_whatsapp_message(phone_number, "Please enter a valid number of adults (e.g., 2, 4, 6)")
                    return jsonify({"status": "invalid_adults_count"})
            
            # Handle booking flow - children count input
            elif session and session.get('step') == 'awaiting_children_count':
                # Validate numeric input (works for both languages)
                if text.isdigit() and int(text) >= 0:
                    name = session.get('name', '')
                    contact = session.get('contact', '')
                    tour_type = session.get('tour_type', '')
                    adults_count = session.get('adults_count', '')
                    ask_for_date(phone_number, name, contact, tour_type, adults_count, text, language)
                    return jsonify({"status": "children_count_received"})
                else:
                    if language == 'arabic':
                        send_whatsapp_message(phone_number, "الرجاء إدخال عدد صحيح للأطفال (مثال: 0, 1, 2)")
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
                
                ask_for_time(phone_number, name, contact, tour_type, adults_count, children_count, text, language)
                return jsonify({"status": "date_received"})
            
            # If user has a language but no active session, check for keywords
            if session and not session.get('step'):
                if handle_keyword_questions(text, phone_number, language):
                    return jsonify({"status": "keyword_answered"})
            
            # If no specific match and user has language set, send appropriate welcome
            if session and session.get('language'):
                send_welcome_message(phone_number, session.get('language'))
                return jsonify({"status": "fallback_welcome_sent"})
            
            # Final fallback - send language selection
            send_language_selection(phone_number)
            return jsonify({"status": "fallback_language_selection"})
        
        return jsonify({"status": "unhandled_message_type"})
        
    except Exception as e:
        logger.error(f"🚨 Error in webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ==============================
# DASHBOARD API ENDPOINTS - ENHANCED
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
# ENHANCED ADMIN CHAT ENDPOINTS
# ==============================

@app.route("/api/send_message", methods=["POST", "OPTIONS"])
def send_admin_message_endpoint():
    """Send message as admin to specific user - ENHANCED"""
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
                "phone_number": clean_phone,
                "timestamp": datetime.datetime.now().isoformat()
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

@app.route("/api/user_messages/<phone_number>", methods=["GET"])
def get_user_messages_endpoint(phone_number):
    """Get complete chat history for a user - ENHANCED"""
    try:
        # Clean the phone number
        clean_phone = clean_oman_number(phone_number)
        if not clean_phone:
            return jsonify({"error": "Invalid phone number format"}), 400
        
        messages = get_user_messages(clean_phone)
        return jsonify({
            "phone_number": clean_phone,
            "messages": messages,
            "total_messages": len(messages),
            "last_updated": datetime.datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error getting user messages: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/chat_users", methods=["GET"])
def get_chat_users():
    """Get all users with chat history"""
    try:
        users = get_all_chat_users()
        return jsonify({
            "users": users,
            "total_users": len(users)
        })
    except Exception as e:
        logger.error(f"Error getting chat users: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/active_sessions", methods=["GET"])
def get_active_sessions():
    """Get all active booking sessions - ENHANCED"""
    try:
        active_sessions = {}
        for phone, session in booking_sessions.items():
            active_sessions[phone] = {
                'step': session.get('step', 'unknown'),
                'flow': session.get('flow', 'unknown'),
                'name': session.get('name', 'Not provided'),
                'tour_type': session.get('tour_type', 'Not selected'),
                'adults_count': session.get('adults_count', '0'),
                'children_count': session.get('children_count', '0'),
                'total_guests': session.get('total_guests', '0'),
                'booking_date': session.get('booking_date', 'Not selected'),
                'language': session.get('language', 'english'),
                'created_at': session.get('created_at', 'Unknown'),
                'last_activity': datetime.datetime.now().isoformat()
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
        "chat_messages_stored": sum(len(msgs) for msgs in chat_messages.values()),
        "unique_chat_users": len(chat_messages),
        "admin_conversations_tracked": len(admin_message_tracker),
        "version": "11.0 - Admin Conversation Protection & Enhanced Language Support"
    }
    return jsonify(status)

# ==============================
# RUN APPLICATION
# ==============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)