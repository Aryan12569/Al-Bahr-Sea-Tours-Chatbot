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

# Track admin messages to prevent bot responses
admin_message_tracker = set()

# User language preferences
user_languages = {}

# ==============================
# BILINGUAL CONTENT & DATA NORMALIZATION
# ==============================

MESSAGES = {
    'en': {
        'welcome': "🌊 Al Bahr Sea Tours\n\nWelcome to Oman's premier sea adventure company! 🚤\n\nPlease choose your preferred language:",
        'choose_language': "Please choose your preferred language:",
        'main_menu': "Choose your sea adventure: 🗺️",
        'booking_start': "📝 *Let's Book Your Tour!* 🎫\n\nI'll help you book your sea adventure. 🌊\n\nFirst, please send me your:\n\n👤 *Full Name*\n\n*Example:*\nAhmed Al Harthy",
        'ask_contact': "Perfect, {name}! 👋\n\nNow please send me your:\n\n📞 *Phone Number*\n\n*Example:*\n91234567",
        'ask_tour_type': "Great {name}! Which tour would you like to book?",
        'ask_adults_count': "👥 *Number of Adults*\n\nGreat choice! {tour_type} it is! 🎯\n\nHow many *adults* (12 years and above) will be joining?\n\nPlease send the number:\n*Examples:* 2, 4, 6",
        'ask_children_count': "👶 *Number of Children*\n\nAdults: {adults_count}\n\nHow many *children* (below 12 years) will be joining?\n\nPlease send the number:\n*Examples:* 0, 1, 2\n\nIf no children, just send: 0",
        'ask_date': "📅 *Preferred Date*\n\nPerfect! {total_guests} guests total:\n• {adults_count} adults\n• {children_count} children\n\nPlease send your *preferred date*:\n\n📋 *Format Examples:*\n• **Tomorrow**\n• **October 29**\n• **Next Friday**\n• **15 November**\n• **2024-12-25**\n\nWe'll check availability for your chosen date! 📅",
        'ask_time': "🕒 *Preferred Time*\n\nPerfect! {booking_date} for {tour_type}.\n\n{total_guests} guests:\n• {adults_count} adults\n• {children_count} children\n\nChoose your preferred time:",
        'booking_complete': "🎉 *Booking Confirmed!* ✅\n\nThank you {name}! Your tour has been booked successfully. 🐬\n\n📋 *Booking Details:*\n👤 Name: {name}\n📞 Contact: {contact}\n🚤 Tour: {tour_type}\n👥 Guests: {total_guests} total\n   • {adults_count} adults\n   • {children_count} children\n📅 Date: {booking_date}\n🕒 Time: {booking_time}\n\n💰 *Total: {total_price} OMR*\n\nOur team will contact you within 1 hour to confirm details. ⏰\nFor immediate assistance: +968 24 123456 📞\n\nGet ready for an amazing sea adventure! 🌊",
        'tour_dolphin': "🐬 Dolphin Watching Tour 🌊\n\n*Experience the magic of swimming with wild dolphins!*\n\n📅 *Duration:* 2 hours\n💰 *Price:* 25 OMR per adult (50% off for children)\n👥 *Group size:* Small groups (max 8 people)\n\n*What's included:*\n• Expert marine guide 🧭\n• Safety equipment & life jackets 🦺\n• Refreshments & bottled water 🥤\n• Photography opportunities 📸\n\n*Best time:* Morning tours (8AM, 10AM)\n*Success rate:* 95% dolphin sightings!\n\nReady to book? Select 'Book Now'! 📅",
        'tour_snorkeling': "🤿 Snorkeling Adventure 🐠\n\n*Discover Oman's underwater paradise!*\n\n📅 *Duration:* 3 hours\n💰 *Price:* 35 OMR per adult (50% off for children)\n👥 *Group size:* Small groups (max 6 people)\n\n*What's included:*\n• Full snorkeling equipment 🤿\n• Professional guide 🧭\n• Safety equipment 🦺\n• Snacks & refreshments 🍎🥤\n\n*What you'll see:*\n• Vibrant coral gardens 🌸\n• Tropical fish species 🐠\n• Sea turtles (if lucky!) 🐢\n• Crystal clear waters 💎\n\nReady to explore? Select 'Book Now'! 🌊",
        'tour_dhow': "⛵ Traditional Dhow Cruise 🌅\n\n*Sail into the sunset on a traditional Omani boat!*\n\n📅 *Duration:* 2 hours\n💰 *Price:* 40 OMR per adult (50% off for children)\n👥 *Group size:* Intimate groups (max 10 people)\n\n*What's included:*\n• Traditional Omani dhow cruise ⛵\n• Sunset views & photography 🌅\n• Omani dinner & refreshments 🍽️\n• Soft drinks & water 🥤\n\n*Departure times:* 4:00 PM, 6:00 PM\n*Perfect for:* Couples, families, special occasions\n\nReady to sail? Select 'Book Now'! ⛵",
        'tour_fishing': "🎣 Deep Sea Fishing Trip 🐟\n\n*Experience the thrill of deep sea fishing!*\n\n📅 *Duration:* 4 hours\n💰 *Price:* 50 OMR per adult (50% off for children)\n👥 *Group size:* Small groups (max 4 people)\n\n*What's included:*\n• Professional fishing gear 🎣\n• Bait & tackle 🪱\n• Expert fishing guide 🧭\n• Refreshments & snacks 🥤🍎\n• Clean & prepare your catch 🐟\n\n*Suitable for:* Beginners to experienced\n*Includes:* Fishing license\n\nReady to catch the big one? Select 'Book Now'! 🎣"
    },
    'ar': {
        'welcome': "🌊 جولات البحر\n\nمرحباً بكم في شركة عُمان الرائدة في مغامرات البحر! 🚤\n\nالرجاء اختيار اللغة المفضلة:",
        'choose_language': "الرجاء اختيار اللغة المفضلة:",
        'main_menu': "اختر مغامرتك البحرية: 🗺️",
        'booking_start': "📝 *لنحجز جولتك!* 🎫\n\nسأساعدك في حجز مغامرتك البحرية. 🌊\n\nأولاً، الرجاء إرسال:\n\n👤 *الاسم الكامل*\n\n*مثال:*\nأحمد الحارثي",
        'ask_contact': "ممتاز {name}! 👋\n\nالآن الرجاء إرسال:\n\n📞 *رقم الهاتف*\n\n*مثال:*\n91234567",
        'ask_tour_type': "رائع {name}! أي جولة تريد حجزها؟",
        'ask_adults_count': "👥 *عدد البالغين*\n\nاختيار ممتاز! {tour_type} 🎯\n\nكم عدد *البالغين* (12 سنة فما فوق) الذين سينضمون؟\n\nالرجاء إرسال الرقم:\n*أمثلة:* ٢، ٤، ٦",
        'ask_children_count': "👶 *عدد الأطفال*\n\nالبالغين: {adults_count}\n\nكم عدد *الأطفال* (أقل من 12 سنة) الذين سينضمون؟\n\nالرجاء إرسال الرقم:\n*أمثلة:* ٠، ١، ٢\n\nإذا لم يكن هناك أطفال، أرسل فقط: ٠",
        'ask_date': "📅 *التاريخ المفضل*\n\nممتاز! إجمالي {total_guests} ضيف:\n• {adults_count} بالغين\n• {children_count} أطفال\n\nالرجاء إرسال *التاريخ المفضل*:\n\n📋 *أمثلة على التنسيق:*\n• **غداً**\n• **٢٩ أكتوبر**\n• **الجمعة القادمة**\n• **١٥ نوفمبر**\n• **٢٠٢٤-١٢-٢٥**\n\nسنتحقق من التوفر للتاريخ المختار! 📅",
        'ask_time': "🕒 *الوقت المفضل*\n\nممتاز! {booking_date} لجولة {tour_type}.\n\n{total_guests} ضيف:\n• {adults_count} بالغين\n• {children_count} أطفال\n\nاختر الوقت المفضل:",
        'booking_complete': "🎉 *تم تأكيد الحجز!* ✅\n\nشكراً لك {name}! تم حجز جولتك بنجاح. 🐬\n\n📋 *تفاصيل الحجز:*\n👤 الاسم: {name}\n📞 الاتصال: {contact}\n🚤 الجولة: {tour_type}\n👥 الضيوف: {total_guests} إجمالي\n   • {adults_count} بالغين\n   • {children_count} أطفال\n📅 التاريخ: {booking_date}\n🕒 الوقت: {booking_time}\n\n💰 *المجموع: {total_price} ريال عُماني*\n\nسيتصل بك فريقنا خلال ساعة واحدة لتأكيد التفاصيل. ⏰\nللحصول على المساعدة الفورية: ٩٦٨٢٤١٢٣٤٥٦ 📞\n\nاستعد لمغامرة بحرية رائعة! 🌊",
        'tour_dolphin': "🐬 جولة مشاهدة الدلافين 🌊\n\n*اختبر سحر السباحة مع الدلافين البرية!*\n\n📅 *المدة:* ساعتان\n💰 *السعر:* ٢٥ ريال عُماني للبالغ (خصم ٥٠٪ للأطفال)\n👥 *حجم المجموعة:* مجموعات صغيرة (8 أشخاص كحد أقصى)\n\n*ما المدرج:*\n• مرشد بحري خبير 🧭\n• معدات السلامة وسترات النجاة 🦺\n• المرطبات ومياه الشرب 🥤\n• فرص التصوير 📸\n\n*أفضل وقت:* جولات الصباح (8 صباحاً، 10 صباحاً)\n*معدل النجاح:* 95٪ مشاهدات الدلافين!\n\nجاهز للحجز؟ اختر 'احجز الآن'! 📅",
        'tour_snorkeling': "🤿 مغامرة الغوص بالسنوركل 🐠\n\n*اكتشف جنة عُمان تحت الماء!*\n\n📅 *المدة:* ٣ ساعات\n💰 *السعر:* ٣٥ ريال عُماني للبالغ (خصم ٥٠٪ للأطفال)\n👥 *حجم المجموعة:* مجموعات صغيرة (6 أشخاص كحد أقصى)\n\n*ما المدرج:*\n• معدات غوص سنوركل كاملة 🤿\n• مرشد محترف 🧭\n• معدات السلامة 🦺\n• وجبات خفيفة ومرطبات 🍎🥤\n\n*ما ستراه:*\n• حدائق مرجانية نابضة بالحياة 🌸\n• أنواع الأسماك الاستوائية 🐠\n• سلاحف البحر (إذا حالفك الحظ!) 🐢\n• مياه صافية بلورية 💎\n\nجاهز للاستكشاف؟ اختر 'احجز الآن'! 🌊",
        'tour_dhow': "⛵ رحلة سفينة الداو التقليدية 🌅\n\n*أبحر في غروب الشمس على قارب عُماني تقليدي!*\n\n📅 *المدة:* ساعتان\n💰 *السعر:* ٤٠ ريال عُماني للبالغ (خصم ٥٠٪ للأطفال)\n👥 *حجم المجموعة:* مجموعات حميمة (10 أشخاص كحد أقصى)\n\n*ما المدرج:*\n• رحلة سفينة داو عُمانية تقليدية ⛵\n• مناظر غروب الشمس والتصوير 🌅\n• عشاء عُماني ومرطبات 🍽️\n• مشروبات غازية ومياه 🥤\n\n*أوقات المغادرة:* 4 مساءً، 6 مساءً\n*مثالي ل:* الأزواج، العائلات، المناسبات الخاصة\n\nجاهز للإبحار؟ اختر 'احجز الآن'! ⛵",
        'tour_fishing': "🎣 رحلة صيد أعماق البحار 🐟\n\n*اختبر متعة صيد أعماق البحار!*\n\n📅 *المدة:* ٤ ساعات\n💰 *السعر:* ٥٠ ريال عُماني للبالغ (خصم ٥٠٪ للأطفال)\n👥 *حجم المجموعة:* مجموعات صغيرة (4 أشخاص كحد أقصى)\n\n*ما المدرج:*\n• معدات صيد محترفة 🎣\n• طعم وأدوات صيد 🪱\n• مرشد صيد خبير 🧭\n• مرطبات ووجبات خفيفة 🥤🍎\n• تنظيف وتحضير صيدك 🐟\n\n*مناسب ل:* المبتدئين إلى ذوي الخبرة\n*يشمل:* رخصة صيد\n\nجاهز لصيد السمك الكبير؟ اختر 'احجز الآن'! 🎣"
    }
}

# ==============================
# DATA NORMALIZATION FUNCTIONS
# ==============================

def normalize_name(arabic_name):
    """Convert Arabic name to standardized English format for storage"""
    # Common Arabic to English name mappings
    name_mapping = {
        'أحمد': 'Ahmed',
        'محمد': 'Mohammed', 
        'محمود': 'Mahmoud',
        'خالد': 'Khalid',
        'علي': 'Ali',
        'عمر': 'Omar',
        'حسن': 'Hassan',
        'حسين': 'Hussein',
        'إبراهيم': 'Ibrahim',
        'يوسف': 'Youssef',
        'مصطفى': 'Mustafa',
        'عبدالله': 'Abdullah',
        'سعيد': 'Saeed',
        'راشد': 'Rashid',
        'سالم': 'Salem',
        'الخارثي': 'Al Harthy',
        'البوسعيدي': 'Al Busaidi',
        'السيابي': 'Al Siyabi',
        'البلوشي': 'Al Balushi'
    }
    
    # If name is already in English/Latin script, return as is
    if re.match(r'^[A-Za-z\s]+$', arabic_name):
        return arabic_name.title()
    
    # Convert common Arabic names to English
    normalized = arabic_name
    for arabic, english in name_mapping.items():
        normalized = normalized.replace(arabic, english)
    
    return normalized

def normalize_tour_type(arabic_tour_type):
    """Convert Arabic tour type to English for consistent storage"""
    tour_mapping = {
        'مشاهدة الدلافين': 'Dolphin Watching',
        'جولة مشاهدة الدلافين': 'Dolphin Watching',
        'الغوص بالسنوركل': 'Snorkeling',
        'مغامرة الغوص بالسنوركل': 'Snorkeling',
        'رحلة سفينة الداو': 'Dhow Cruise',
        'سفينة الداو التقليدية': 'Dhow Cruise',
        'صيد السمك': 'Fishing Trip',
        'رحلة صيد': 'Fishing Trip',
        'صيد أعماق البحار': 'Fishing Trip'
    }
    
    return tour_mapping.get(arabic_tour_type, arabic_tour_type)

def normalize_date(arabic_date):
    """Convert Arabic date expressions to English format"""
    date_mapping = {
        'غداً': 'Tomorrow',
        'بعد غد': 'Day after tomorrow',
        'اليوم': 'Today',
        'الاثنين': 'Monday',
        'الثلاثاء': 'Tuesday', 
        'الأربعاء': 'Wednesday',
        'الخميس': 'Thursday',
        'الجمعة': 'Friday',
        'السبت': 'Saturday',
        'الأحد': 'Sunday'
    }
    
    normalized = arabic_date
    for arabic, english in date_mapping.items():
        normalized = normalized.replace(arabic, english)
    
    return normalized

def normalize_numbers(arabic_text):
    """Convert Arabic numbers to English numbers"""
    arabic_to_english = {
        '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
        '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9'
    }
    
    normalized = arabic_text
    for arabic, english in arabic_to_english.items():
        normalized = normalized.replace(arabic, english)
    
    return normalized

def get_user_language(phone_number):
    """Get user's preferred language"""
    return user_languages.get(phone_number, 'en')

def set_user_language(phone_number, language):
    """Set user's preferred language"""
    user_languages[phone_number] = language
    logger.info(f"🌐 Set language for {phone_number}: {language}")

# ==============================
# MESSAGE STORAGE FUNCTIONS
# ==============================

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
            'id': len(chat_messages[clean_phone]) + 1
        }
            
        chat_messages[clean_phone].append(message_entry)
        
        # Keep only last 200 messages per user
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
        messages.sort(key=lambda x: x['timestamp'])
        return messages
        
    except Exception as e:
        logger.error(f"❌ Error getting user messages: {str(e)}")
        return []

# ==============================
# ADMIN MESSAGE DETECTION
# ==============================

def is_admin_message(phone_number, message_text):
    """Detect if a message came from admin dashboard"""
    try:
        clean_phone = clean_oman_number(phone_number)
        if not clean_phone:
            return False
            
        message_id = f"{clean_phone}_{hash(message_text)}_{int(time.time())}"
        
        if message_id in admin_message_tracker:
            logger.info(f"🛑 Identified admin message from {clean_phone}: {message_text[:50]}...")
            admin_message_tracker.discard(message_id)
            return True
            
        return False
        
    except Exception as e:
        logger.error(f"Error checking admin message: {str(e)}")
        return False

def track_admin_message(phone_number, message_text):
    """Track an admin message so we can identify it when it comes back via webhook"""
    try:
        clean_phone = clean_oman_number(phone_number)
        if not clean_phone:
            return False
            
        message_id = f"{clean_phone}_{hash(message_text)}_{int(time.time())}"
        admin_message_tracker.add(message_id)
        
        # Clean up old tracked messages (older than 2 minutes)
        current_time = int(time.time())
        global admin_message_tracker
        admin_message_tracker = {msg_id for msg_id in admin_message_tracker 
                               if current_time - int(msg_id.split('_')[-1]) < 120}
        
        logger.info(f"📝 Tracking admin message to {clean_phone}: {message_text[:50]}...")
        return True
        
    except Exception as e:
        logger.error(f"Error tracking admin message: {str(e)}")
        return False

# ==============================
# CORE BOT FUNCTIONS - BILINGUAL
# ==============================

def send_welcome_message(to):
    """Send language selection message"""
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "🌊 Al Bahr Sea Tours / جولات البحر"
        },
        "body": {
            "text": MESSAGES['en']['welcome']  # Show English version for language selection
        },
        "action": {
            "button": "🌍 Choose Language / اختر اللغة",
            "sections": [
                {
                    "title": "Select Language / اختر اللغة",
                    "rows": [
                        {
                            "id": "lang_en",
                            "title": "🇺🇸 English",
                            "description": "Continue in English"
                        },
                        {
                            "id": "lang_ar", 
                            "title": "🇴🇲 العربية",
                            "description": "المتابعة باللغة العربية"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def send_main_options_list(to, language='en'):
    """Send main menu in selected language"""
    interactive_data = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "🌊 Al Bahr Sea Tours" if language == 'en' else "🌊 جولات البحر"
        },
        "body": {
            "text": MESSAGES[language]['main_menu']
        },
        "action": {
            "button": "🌊 View Tours / عرض الجولات",
            "sections": [
                {
                    "title": "🚤 Popular Tours / الجولات الشعبية",
                    "rows": [
                        {
                            "id": "dolphin_tour",
                            "title": "🐬 Dolphin Watching / مشاهدة الدلافين",
                            "description": "Swim with dolphins / السباحة مع الدلافين"
                        },
                        {
                            "id": "snorkeling", 
                            "title": "🤿 Snorkeling / الغوص بالسنوركل",
                            "description": "Explore coral reefs / استكشاف الشعب المرجانية"
                        },
                        {
                            "id": "dhow_cruise",
                            "title": "⛵ Dhow Cruise / رحلة الداو", 
                            "description": "Traditional boat sunset / غروب الشمس بالقارب التقليدي"
                        },
                        {
                            "id": "fishing",
                            "title": "🎣 Fishing Trip / رحلة صيد",
                            "description": "Deep sea fishing / صيد أعماق البحار"
                        }
                    ]
                },
                {
                    "title": "ℹ️ Information & Booking / معلومات والحجز",
                    "rows": [
                        {
                            "id": "pricing",
                            "title": "💰 Pricing / الأسعار",
                            "description": "Tour prices and packages / أسعار الجولات والباقات"
                        },
                        {
                            "id": "location",
                            "title": "📍 Location / الموقع",
                            "description": "Our marina address / عنوان المارينا"
                        },
                        {
                            "id": "schedule",
                            "title": "🕒 Schedule / الجدول",
                            "description": "Tour timings and availability / أوقات الجولات والتوفر"
                        },
                        {
                            "id": "contact",
                            "title": "📞 Contact / اتصل بنا",
                            "description": "Get in touch with our team / تواصل مع فريقنا"
                        },
                        {
                            "id": "book_now",
                            "title": "📅 Book Now / احجز الآن", 
                            "description": "Reserve your sea adventure / احجز مغامرتك البحرية"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def start_booking_flow(to, language='en'):
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
    
    send_whatsapp_message(to, MESSAGES[language]['booking_start'])

def ask_for_contact(to, name, language='en'):
    """Ask for contact after getting name"""
    # Update session with name
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_contact',
            'name': name
        })
    
    message = MESSAGES[language]['ask_contact'].format(name=name)
    send_whatsapp_message(to, message)

def ask_for_tour_type(to, name, contact, language='en'):
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
            "text": "🚤 Choose Your Tour / اختر جولتك"
        },
        "body": {
            "text": MESSAGES[language]['ask_tour_type'].format(name=name)
        },
        "action": {
            "button": "Select Tour / اختر جولة",
            "sections": [
                {
                    "title": "Available Tours / الجولات المتاحة",
                    "rows": [
                        {
                            "id": f"book_dolphin|{name}|{contact}|{language}",
                            "title": "🐬 Dolphin Watching / مشاهدة الدلافين",
                            "description": "2 hours • 25 OMR / ساعتان • ٢٥ ريال"
                        },
                        {
                            "id": f"book_snorkeling|{name}|{contact}|{language}", 
                            "title": "🤿 Snorkeling / الغوص بالسنوركل",
                            "description": "3 hours • 35 OMR / ٣ ساعات • ٣٥ ريال"
                        },
                        {
                            "id": f"book_dhow|{name}|{contact}|{language}",
                            "title": "⛵ Dhow Cruise / رحلة الداو", 
                            "description": "2 hours • 40 OMR / ساعتان • ٤٠ ريال"
                        },
                        {
                            "id": f"book_fishing|{name}|{contact}|{language}",
                            "title": "🎣 Fishing Trip / رحلة صيد",
                            "description": "4 hours • 50 OMR / ٤ ساعات • ٥٠ ريال"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def ask_for_adults_count(to, name, contact, tour_type, language='en'):
    """Ask for number of adults"""
    # Update session with tour type
    if to in booking_sessions:
        booking_sessions[to].update({
            'step': 'awaiting_adults_count',
            'name': name,
            'contact': contact,
            'tour_type': tour_type
        })
    
    message = MESSAGES[language]['ask_adults_count'].format(
        tour_type=tour_type, 
        name=name
    )
    send_whatsapp_message(to, message)

def ask_for_children_count(to, name, contact, tour_type, adults_count, language='en'):
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
    
    message = MESSAGES[language]['ask_children_count'].format(adults_count=adults_count)
    send_whatsapp_message(to, message)

def ask_for_date(to, name, contact, tour_type, adults_count, children_count, language='en'):
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
    
    message = MESSAGES[language]['ask_date'].format(
        total_guests=total_guests,
        adults_count=adults_count,
        children_count=children_count
    )
    send_whatsapp_message(to, message)

def ask_for_time(to, name, contact, tour_type, adults_count, children_count, booking_date, language='en'):
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
            "text": "🕒 Preferred Time / الوقت المفضل"
        },
        "body": {
            "text": MESSAGES[language]['ask_time'].format(
                booking_date=booking_date,
                tour_type=tour_type,
                total_guests=total_guests,
                adults_count=adults_count,
                children_count=children_count
            )
        },
        "action": {
            "button": "Select Time / اختر الوقت",
            "sections": [
                {
                    "title": "Morning Sessions / جولات الصباح",
                    "rows": [
                        {
                            "id": f"time_8am|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}|{language}",
                            "title": "🌅 8:00 AM / ٨:٠٠ صباحاً",
                            "description": "Early morning adventure / مغامرة الصباح الباكر"
                        },
                        {
                            "id": f"time_9am|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}|{language}", 
                            "title": "☀️ 9:00 AM / ٩:٠٠ صباحاً",
                            "description": "Morning session / جولة الصباح"
                        },
                        {
                            "id": f"time_10am|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}|{language}",
                            "title": "🌞 10:00 AM / ١٠:٠٠ صباحاً", 
                            "description": "Late morning / أواخر الصباح"
                        }
                    ]
                },
                {
                    "title": "Afternoon Sessions / جولات بعد الظهر",
                    "rows": [
                        {
                            "id": f"time_2pm|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}|{language}",
                            "title": "🌇 2:00 PM / ٢:٠٠ مساءً",
                            "description": "Afternoon adventure / مغامرة بعد الظهر"
                        },
                        {
                            "id": f"time_4pm|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}|{language}",
                            "title": "🌅 4:00 PM / ٤:٠٠ مساءً",
                            "description": "Late afternoon / أواخر بعد الظهر"
                        },
                        {
                            "id": f"time_6pm|{name}|{contact}|{tour_type}|{adults_count}|{children_count}|{booking_date}|{language}",
                            "title": "🌆 6:00 PM / ٦:٠٠ مساءً",
                            "description": "Evening session / جولة المساء"
                        }
                    ]
                }
            ]
        }
    }
    
    send_whatsapp_message(to, "", interactive_data)

def complete_booking(to, name, contact, tour_type, adults_count, children_count, booking_date, booking_time, language='en'):
    """Complete the booking and save to sheet"""
    total_guests = int(adults_count) + int(children_count)
    
    # NORMALIZE DATA FOR STORAGE IN ENGLISH
    normalized_name = normalize_name(name)
    normalized_tour_type = normalize_tour_type(tour_type)
    normalized_date = normalize_date(booking_date)
    normalized_contact = normalize_numbers(contact)
    
    # Save to Google Sheets - ALL DATA IN ENGLISH
    success = add_lead_to_sheet(
        name=normalized_name,
        contact=normalized_contact,
        intent="Book Tour",
        whatsapp_id=to,
        tour_type=normalized_tour_type,
        booking_date=normalized_date,
        booking_time=booking_time,
        adults_count=adults_count,
        children_count=children_count,
        total_guests=str(total_guests),
        language=language.upper()
    )
    
    # Clear the session
    if to in booking_sessions:
        del booking_sessions[to]
    
    # Calculate price
    total_price = calculate_price(normalized_tour_type, adults_count, children_count)
    
    # Send confirmation message in user's language
    message = MESSAGES[language]['booking_complete'].format(
        name=name,
        contact=contact,
        tour_type=tour_type,
        total_guests=total_guests,
        adults_count=adults_count,
        children_count=children_count,
        booking_date=booking_date,
        booking_time=booking_time,
        total_price=total_price
    )
    
    send_whatsapp_message(to, message)

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
    children_total = children * (base_price * 0.5)
    
    total_price = adult_total + children_total
    
    # Apply group discount for 4+ total guests
    if (adults + children) >= 4:
        total_price = total_price * 0.9  # 10% discount
    
    return f"{total_price:.2f}"

def handle_keyword_questions(text, phone_number, language='en'):
    """Handle direct keyword questions without menu"""
    text_lower = text.lower()
    
    # Location questions
    if any(word in text_lower for word in ['where', 'location', 'address', 'located', 'map', 'اين', 'موقع', 'عنوان']):
        if language == 'en':
            response = """📍 *Our Location:* 🌊

🏖️ *Al Bahr Sea Tours*
Marina Bandar Al Rowdha
Muscat, Oman

🗺️ *Google Maps:* 
https://maps.app.goo.gl/albahrseatours

🚗 *Parking:* Available at marina
⏰ *Opening Hours:* 7:00 AM - 7:00 PM Daily

We're located at the beautiful Bandar Al Rowdha Marina! 🚤"""
        else:
            response = """📍 *موقعنا:* 🌊

🏖️ *جولات البحر*
مارينا بندر الروضة
مسقط، عُمان

🗺️ *خرائط جوجل:* 
https://maps.app.goo.gl/albahrseatours

🚗 *مواقف سيارات:* متوفرة في المارينا
⏰ *ساعات العمل:* 7 صباحاً - 7 مساءً يومياً

نحن موجودون في مارينا بندر الروضة الجميلة! 🚤"""
        
        send_whatsapp_message(phone_number, response)
        return True
    
    # Price questions
    elif any(word in text_lower for word in ['price', 'cost', 'how much', 'fee', 'charge', 'سعر', 'تكلفة', 'كم', 'ثمن']):
        if language == 'en':
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
        else:
            response = """💰 *أسعار الجولات والباقات:* 💵

🐬 *جولة مشاهدة الدلافين:*
• ساعتان • ٢٥ ريال للبالغ
• الأطفال تحت ١٢ سنة: خصم ٥٠٪
• يشمل: مرشد، معدات السلامة، مرطبات

🤿 *مغامرة الغوص بالسنوركل:*
• ٣ ساعات • ٣٥ ريال للبالغ
• الأطفال تحت ١٢ سنة: خصم ٥٠٪  
• يشمل: المعدات، مرشد، وجبات خفيفة ومشروبات

⛵ *رحلة سفينة الداو:*
• ساعتان • ٤٠ ريال للبالغ
• الأطفال تحت ١٢ سنة: خصم ٥٠٪
• يشمل: عشاء عُماني تقليدي، مشروبات

🎣 *رحلة صيد السمك:*
• ٤ ساعات • ٥٠ ريال للبالغ
• الأطفال تحت ١٢ سنة: خصم ٥٠٪
• يشمل: معدات الصيد، طعم، مرطبات

👨‍👩‍👧‍👦 *عروض خاصة:*
• مجموعة ٤+ أشخاص: خصم ١٠٪
• باقات عائلية متوفرة!"""
        
        send_whatsapp_message(phone_number, response)
        return True
    
    return False

def handle_interaction(interaction_id, phone_number):
    """Handle list and button interactions"""
    logger.info(f"Handling interaction: {interaction_id} for {phone_number}")
    
    # Get user language
    language = get_user_language(phone_number)
    
    # Handle language selection
    if interaction_id in ['lang_en', 'lang_ar']:
        selected_language = 'en' if interaction_id == 'lang_en' else 'ar'
        set_user_language(phone_number, selected_language)
        send_main_options_list(phone_number, selected_language)
        return True
    
    # Check if it's a booking flow interaction
    if '|' in interaction_id:
        parts = interaction_id.split('|')
        action = parts[0]
        
        if action.startswith('book_') and len(parts) >= 4:
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
            user_lang = parts[3]
            
            # Convert tour type to Arabic if needed
            if user_lang == 'ar':
                tour_type_ar = {
                    'Dolphin Watching': 'مشاهدة الدلافين',
                    'Snorkeling': 'الغوص بالسنوركل',
                    'Dhow Cruise': 'رحلة الداو',
                    'Fishing Trip': 'رحلة صيد'
                }.get(tour_type, tour_type)
                tour_type = tour_type_ar
            
            ask_for_adults_count(phone_number, name, contact, tour_type, user_lang)
            return True
            
        elif action.startswith('time_') and len(parts) >= 8:
            # Time selection - complete booking
            time_map = {
                'time_8am': '8:00 AM',
                'time_9am': '9:00 AM',
                'time_10am': '10:00 AM',
                'time_2pm': '2:00 PM',
                'time_4pm': '4:00 PM',
                'time_6pm': '6:00 PM'
            }
            
            time_map_ar = {
                'time_8am': '٨:٠٠ صباحاً',
                'time_9am': '٩:٠٠ صباحاً',
                'time_10am': '١٠:٠٠ صباحاً',
                'time_2pm': '٢:٠٠ مساءً',
                'time_4pm': '٤:٠٠ مساءً',
                'time_6pm': '٦:٠٠ مساءً'
            }
            
            user_lang = parts[7]
            booking_time = time_map.get(action, 'Not specified')
            if user_lang == 'ar':
                booking_time = time_map_ar.get(action, booking_time)
                
            name = parts[1]
            contact = parts[2]
            tour_type = parts[3]
            adults_count = parts[4]
            children_count = parts[5]
            booking_date = parts[6]
            
            complete_booking(phone_number, name, contact, tour_type, adults_count, children_count, booking_date, booking_time, user_lang)
            return True
    
    # Regular menu interactions
    responses = {
        'en': {
            "view_options": lambda: send_main_options_list(phone_number, 'en'),
            "dolphin_tour": MESSAGES['en']['tour_dolphin'],
            "snorkeling": MESSAGES['en']['tour_snorkeling'],
            "dhow_cruise": MESSAGES['en']['tour_dhow'],
            "fishing": MESSAGES['en']['tour_fishing'],
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

🌅 *Morning Sessions:*
• 8:00 AM - Dolphin Watching 🐬
• 9:00 AM - Snorkeling 🤿
• 10:00 AM - Dolphin Watching 🐬
• 11:00 AM - Snorkeling 🤿

🌇 *Afternoon Sessions:*
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
            "book_now": lambda: start_booking_flow(phone_number, 'en')
        },
        'ar': {
            "view_options": lambda: send_main_options_list(phone_number, 'ar'),
            "dolphin_tour": MESSAGES['ar']['tour_dolphin'],
            "snorkeling": MESSAGES['ar']['tour_snorkeling'],
            "dhow_cruise": MESSAGES['ar']['tour_dhow'],
            "fishing": MESSAGES['ar']['tour_fishing'],
            "pricing": """💰 *أسعار الجولات والباقات* 💵

*جميع الأسعار تشمل معدات السلامة والمرشدين*
*الأطفال تحت ١٢ سنة يحصلون على خصم ٥٠٪!*

🐬 *مشاهدة الدلافين:* ٢٥ ريال للبالغ
• ساعتان • مجموعات صغيرة • مرطبات مدرجة

🤿 *مغامرة الغوص بالسنوركل:* ٣٥ ريال للبالغ  
• ٣ ساعات • معدات كاملة • وجبات خفيفة ومشروبات

⛵ *رحلة الداو:* ٤٠ ريال للبالغ
• ساعتان • قارب تقليدي • عشاء مدرج

🎣 *رحلة صيد السمك:* ٥٠ ريال للبالغ
• ٤ ساعات • معدات محترفة • مرطبات

👨‍👩‍👧‍👦 *عروض خاصة:*
• مجموعة ٤+ أشخاص: خصم ١٠٪
• باقات عائلية متوفرة

احجز مغامرتك اليوم! 📅""",
            "location": """📍 *موقعنا وتوجيهات* 🗺️

🏖️ *جولات البحر*
مارينا بندر الروضة
مسقط، سلطنة عُمان

🗺️ *خرائط جوجل:*
https://maps.app.goo.gl/albahrseatours

🚗 *كيف تصل إلينا:*
• من مركز مسقط: ١٥ دقيقة
• من مطار السيب: ٢٥ دقيقة  
• من الموج: ١٠ دقائق

🅿️ *مواقف سيارات:* مواقف واسعة متوفرة في المارينا

⏰ *ساعات العمل:*
٧ صباحاً - ٧ مساءً يومياً

من السهل العثور علينا في مارينا بندر الروضة! 🚤""",
            "schedule": """🕒 *جدول الجولات والتوفر* 📅

*أوقات المغادرة اليومية:*

🌅 *جولات الصباح:*
• ٨:٠٠ ص - مشاهدة الدلافين 🐬
• ٩:٠٠ ص - الغوص بالسنوركل 🤿
• ١٠:٠٠ ص - مشاهدة الدلافين 🐬
• ١١:٠٠ ص - الغوص بالسنوركل 🤿

🌇 *جولات بعد الظهر:*
• ٢:٠٠ م - رحلة صيد 🎣
• ٤:٠٠ م - رحلة الداو ⛵
• ٥:٠٠ م - مشاهدة الدلافين عند الغروب 🐬

🌅 *سحر المساء:*
• ٦:٠٠ م - رحلة الداو ⛵
• ٦:٣٠ م - رحلة الغروب 🌅

📅 *يوصى بالحجز المسبق*
⏰ *التسجيل:* ٣٠ دقيقة قبل المغادرة""",
            "contact": """📞 *اتصل بجولات البحر* 📱

*نحن هنا لمساعدتك في تخطيط المغامرة البحرية المثالية!* 🌊

📞 *هاتف:* ٩٦٨٢٤١٢٣٤٥٦+
📱 *واتساب:* ٩٦٨٩١٢٣٤٥٦٧+
📧 *بريد إلكتروني:* info@albahrseatours.com

🌐 *موقع الويب:* www.albahrseatours.com

⏰ *ساعات خدمة العملاء:*
٧ صباحاً - ٧ مساءً يومياً

📍 *زورونا:*
مارينا بندر الروضة
مسقط، عُمان""",
            "book_now": lambda: start_booking_flow(phone_number, 'ar')
        }
    }
    
    lang_responses = responses.get(language, responses['en'])
    response = lang_responses.get(interaction_id)
    
    if callable(response):
        response()
        return True
    elif response:
        send_whatsapp_message(phone_number, response)
        return True
    else:
        error_msg = "Sorry, I didn't understand that option. Please select from the menu. 📋" if language == 'en' else "عذراً، لم أفهم هذا الخيار. الرجاء الاختيار من القائمة. 📋"
        send_whatsapp_message(phone_number, error_msg)
        return False

# ==============================
# ADMIN CHAT INTERVENTION FUNCTIONS
# ==============================

def send_admin_message(phone_number, message):
    """Send message as admin to specific user"""
    try:
        success = send_whatsapp_message(phone_number, message)
        
        if success:
            # Track this admin message to prevent bot response
            track_admin_message(phone_number, message)
            # Store the admin message in chat history
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
            'language': session.get('language', 'en'),
            'created_at': session.get('created_at', 'Unknown')
        }
    else:
        return {'has_session': False}

# ==============================
# HELPER FUNCTIONS
# ==============================

def add_lead_to_sheet(name, contact, intent, whatsapp_id, tour_type="Not specified", booking_date="Not specified", booking_time="Not specified", adults_count="0", children_count="0", total_guests="0", language="EN"):
    """Add user entry to Google Sheet - ALL DATA STORED IN ENGLISH"""
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p")
        sheet.append_row([timestamp, name, contact, whatsapp_id, intent, tour_type, booking_date, booking_time, adults_count, children_count, total_guests, language])
        logger.info(f"✅ Added lead to sheet: {name}, {contact}, {intent}, Adults: {adults_count}, Children: {children_count}, Language: {language}")
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
            
            # CHECK FOR ADMIN MESSAGE FIRST
            if is_admin_message(phone_number, user_message):
                logger.info(f"🛑 Ignoring admin message from {phone_number}")
                return jsonify({"status": "admin_message_ignored"})
        
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
                    send_main_options_list(phone_number, language)
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
            if not session and handle_keyword_questions(text, phone_number, language):
                return jsonify({"status": "keyword_answered"})
            
            # Check for greeting
            greeting_words_en = ["hi", "hello", "hey", "start", "menu"]
            greeting_words_ar = ["مرحبا", "السلام", "اهلا", "اهلاً", "اهلا وسهلا", "بداية", "قائمة"]
            
            if not session and (text.lower() in greeting_words_en or text in greeting_words_ar):
                send_welcome_message(phone_number)
                return jsonify({"status": "welcome_sent"})
            
            # Handle booking flow - name input
            if session and session.get('step') == 'awaiting_name':
                # Normalize name for storage but keep original for communication
                original_name = text
                ask_for_contact(phone_number, original_name, session.get('language', 'en'))
                return jsonify({"status": "name_received"})
            
            # Handle booking flow - contact input
            elif session and session.get('step') == 'awaiting_contact':
                name = session.get('name', '')
                # Normalize contact numbers (convert Arabic numerals to English)
                normalized_contact = normalize_numbers(text)
                ask_for_tour_type(phone_number, name, normalized_contact, session.get('language', 'en'))
                return jsonify({"status": "contact_received"})
            
            # Handle booking flow - adults count input
            elif session and session.get('step') == 'awaiting_adults_count':
                # Validate numeric input (handle both English and Arabic numbers)
                normalized_text = normalize_numbers(text)
                if normalized_text.isdigit() and int(normalized_text) > 0:
                    name = session.get('name', '')
                    contact = session.get('contact', '')
                    tour_type = session.get('tour_type', '')
                    user_lang = session.get('language', 'en')
                    ask_for_children_count(phone_number, name, contact, tour_type, normalized_text, user_lang)
                    return jsonify({"status": "adults_count_received"})
                else:
                    error_msg = "Please enter a valid number of adults (e.g., 2, 4, 6)" if session.get('language') == 'en' else "الرجاء إدخال عدد صحيح للبالغين (مثال: ٢، ٤، ٦)"
                    send_whatsapp_message(phone_number, error_msg)
                    return jsonify({"status": "invalid_adults_count"})
            
            # Handle booking flow - children count input
            elif session and session.get('step') == 'awaiting_children_count':
                # Validate numeric input (handle both English and Arabic numbers)
                normalized_text = normalize_numbers(text)
                if normalized_text.isdigit() and int(normalized_text) >= 0:
                    name = session.get('name', '')
                    contact = session.get('contact', '')
                    tour_type = session.get('tour_type', '')
                    adults_count = session.get('adults_count', '')
                    user_lang = session.get('language', 'en')
                    ask_for_date(phone_number, name, contact, tour_type, adults_count, normalized_text, user_lang)
                    return jsonify({"status": "children_count_received"})
                else:
                    error_msg = "Please enter a valid number of children (e.g., 0, 1, 2)" if session.get('language') == 'en' else "الرجاء إدخال عدد صحيح للأطفال (مثال: ٠، ١، ٢)"
                    send_whatsapp_message(phone_number, error_msg)
                    return jsonify({"status": "invalid_children_count"})
            
            # Handle booking flow - date input
            elif session and session.get('step') == 'awaiting_date':
                name = session.get('name', '')
                contact = session.get('contact', '')
                tour_type = session.get('tour_type', '')
                adults_count = session.get('adults_count', '')
                children_count = session.get('children_count', '')
                user_lang = session.get('language', 'en')
                
                # Normalize date for storage but keep original for communication
                original_date = text
                ask_for_time(phone_number, name, contact, tour_type, adults_count, children_count, original_date, user_lang)
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
                'language': session.get('language', 'en'),
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
        "user_languages": len(user_languages),
        "version": "10.0 - Bilingual Arabic/English with Data Normalization"
    }
    return jsonify(status)

# ==============================
# RUN APPLICATION
# ==============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)