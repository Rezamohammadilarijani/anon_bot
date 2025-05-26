import asyncio
import logging
import os
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler, ConversationHandler
)
import pymongo
import redis
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
import base64
from dotenv import load_dotenv

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

# بارگذاری متغیرهای محیطی
env_path = r"C:\Users\asus\Desktop\HalfBlood75\.env"
logger.info(f"در حال بارگذاری فایل .env از: {env_path}")
load_dotenv(env_path)

# لاگ برای چک کردن محتوای فایل .env
try:
    with open(env_path, 'r', encoding='utf-8') as f:
        logger.info(f"محتوای فایل .env:\n{f.read()}")
except Exception as e:
    logger.error(f"خطا در خواندن فایل .env: {e}")

TOKEN = os.getenv("BOT_TOKEN")
logger.info(f"مقدار BOT_TOKEN: {'[پیدا شد]' if TOKEN else '[پیدا نشد]'}")
if not TOKEN:
    logger.error("BOT_TOKEN در فایل .env پیدا نشد. لطفاً فایل .env را با BOT_TOKEN معتبر در C:\\Users\\asus\\Desktop\\HalfBlood75\\.env بسازید.")
    raise ValueError("BOT_TOKEN باید در فایل .env تعریف شود. از @BotFather توکن بگیرید و در .env قرار دهید.")

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    logger.warning("ENCRYPTION_KEY در .env پیدا نشد. کلید موقت تولید می‌شود.")
    ENCRYPTION_KEY = get_random_bytes(16).hex()
try:
    ENCRYPTION_KEY = ENCRYPTION_KEY.encode()
    if len(ENCRYPTION_KEY) not in [16, 24, 32]:
        raise ValueError("ENCRYPTION_KEY باید 16، 24 یا 32 بایت باشد.")
except Exception as e:
    logger.error(f"خطا در پردازش ENCRYPTION_KEY: {e}")
    raise

# تنظیمات دیتابیس
mongo_client = pymongo.MongoClient("mongodb://localhost:27017/")
db = mongo_client["anonymous_chat"]
users_collection = db["users"]
sessions_collection = db["sessions"]
redis_client = redis.Redis(host="localhost", port=6379, db=0)

ADMINS_PHONES = ["+989114168759", "+989213680228"]
CARD_NUMBER = "5022291300957436"
FREE_CHAT_LIMIT = 4

# مراحل ConversationHandler
ASK_AGE, ASK_GENDER, ASK_PHONE, ASK_NICKNAME, ASK_INTERESTS, ASK_LOCATION, REGISTERED, ASK_PARTNER_GENDER = range(8)

# منوی اصلی
main_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔍 جستجو", callback_data="search"),
     InlineKeyboardButton("✂️ پایان", callback_data="end")],
    [InlineKeyboardButton("🔁 بعدی", callback_data="skip"),
     InlineKeyboardButton("🚫 بلاک", callback_data="block")],
    [InlineKeyboardButton("🚨 ریپورت", callback_data="report"),
     InlineKeyboardButton("⚙️ وضعیت", callback_data="status")],
    [InlineKeyboardButton("✏️ ویرایش پروفایل", callback_data="edit_profile")]
])

phone_keyboard = ReplyKeyboardMarkup(
    [[KeyboardButton("ارسال شماره من", request_contact=True)]],
    one_time_keyboard=True,
    resize_keyboard=True
)

location_keyboard = ReplyKeyboardMarkup(
    [[KeyboardButton("ارسال موقعیت", request_location=True),
      KeyboardButton("رد کردن", request_location=False)]],
    one_time_keyboard=True,
    resize_keyboard=True
)

interests_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("موسیقی 🎵", callback_data="interest_music"),
     InlineKeyboardButton("ورزش 🏀", callback_data="interest_sport")],
    [InlineKeyboardButton("فیلم 🎬", callback_data="interest_movie"),
     InlineKeyboardButton("کتاب 📚", callback_data="interest_book")],
    [InlineKeyboardButton("تکمیل انتخاب", callback_data="interest_done")]
])

def encrypt_phone(phone):
    try:
        cipher = AES.new(ENCRYPTION_KEY, AES.MODE_EAX)
        nonce = cipher.nonce
        ciphertext, tag = cipher.encrypt_and_digest(phone.encode())
        return base64.b64encode(nonce + ciphertext).decode()
    except Exception as e:
        logger.error(f"خطا در رمزنگاری شماره تلفن: {e}")
        raise

def decrypt_phone(encrypted_phone):
    try:
        data = base64.b64decode(encrypted_phone)
        nonce, ciphertext = data[:16], data[16:]
        cipher = AES.new(ENCRYPTION_KEY, AES.MODE_EAX, nonce=nonce)
        return cipher.decrypt(ciphertext).decode()
    except Exception as e:
        logger.error(f"خطا در رمزگشایی شماره تلفن: {e}")
        raise

def has_valid_subscription(user_id):
    user = users_collection.find_one({"telegram_id": user_id})
    if user and user.get("is_admin"):
        return True
    expiry = user.get("subscription_expiry")
    if expiry and expiry > datetime.now():
        return True
    return False

async def prompt_for_payment(user_id, context):
    await context.bot.send_message(
        user_id,
        f"💰 برای ادامه استفاده از ربات، لطفاً مبلغ ۵۰ هزار تومان به شماره کارت زیر واریز کنید:\n\n"
        f"💳 شماره کارت: {CARD_NUMBER}\n\n"
        "پس از واریز، رسید را برای ادمین‌ها ارسال کنید تا اشتراک شما فعال شود."
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users_collection.find_one({"telegram_id": user_id})
    if user and user.get("registered", False):
        await update.message.reply_text(
            "👋 خوش آمدید!\nبرای شروع چت ناشناس دکمه‌ها را استفاده کنید.",
            reply_markup=main_keyboard
        )
        return REGISTERED
    else:
        await update.message.reply_text(
            "👋 سلام!\nلطفاً سن خود را وارد کنید (عدد بین 10 تا 99).",
            reply_markup=ReplyKeyboardRemove()
        )
        return ASK_AGE

async def ask_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    if not text.isdigit() or not (10 <= int(text) <= 99):
        await update.message.reply_text("لطفاً سن را عددی بین 10 تا 99 وارد کنید.")
        return ASK_AGE
    context.user_data["age"] = int(text)
    users_collection.update_one(
        {"telegram_id": user_id},
        {"$set": {"profile.age": int(text)}},
        upsert=True
    )
    await update.message.reply_text(
        "جنسیت خود را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("مرد", callback_data="gender_male"),
             InlineKeyboardButton("زن", callback_data="gender_female")]
        ])
    )
    return ASK_GENDER

async def ask_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    gender = query.data.split("_")[1]  # gender_male یا gender_female
    context.user_data["gender"] = gender

    # ذخیره در دیتابیس
    users_collection.update_one(
        {"telegram_id": query.from_user.id},
        {"$set": {"profile.gender": gender}},
        upsert=True
    )

    # ارسال پیام جدید به‌جای ویرایش
    await query.message.reply_text(
        "لطفاً شماره تلفن خود را با دکمه زیر ارسال کنید:",
        reply_markup=phone_keyboard
    )

    return ASK_PHONE

async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        text = update.message.text
        if text and text.startswith("+") and text[1:].isdigit():
            phone = text
        else:
            await update.message.reply_text(
                "لطفاً شماره تلفن معتبر با فرمت +98XXXXXXXXXX ارسال کنید یا از دکمه ارسال شماره استفاده کنید.",
                reply_markup=phone_keyboard
            )
            return ASK_PHONE

    encrypted_phone = encrypt_phone(phone)
    users_collection.update_one(
        {"telegram_id": user_id},
        {"$set": {
            "phone": encrypted_phone,
            "is_admin": phone in ADMINS_PHONES,
            "chat_count": 0,
            "blocked_users": [],
            "reports": 0
        }}
    )
    await update.message.reply_text(
        "لطفاً یک نام مستعار (Nickname) وارد کنید (حداکثر 20 کاراکتر):",
        reply_markup=ReplyKeyboardRemove()
    )
    return ASK_NICKNAME

async def ask_nickname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nickname = update.message.text.strip()
    if len(nickname) > 20:
        await update.message.reply_text("نام مستعار باید حداکثر 20 کاراکتر باشد.")
        return ASK_NICKNAME
    users_collection.update_one(
        {"telegram_id": user_id},
        {"$set": {"profile.nickname": nickname}}
    )
    await update.message.reply_text(
        "علایق خود را انتخاب کنید (می‌توانید چند گزینه را انتخاب کنید و در آخر 'تکمیل انتخاب' را بزنید):",
        reply_markup=interests_keyboard
    )
    users_collection.update_one(
        {"telegram_id": user_id},
        {"$set": {"profile.interests": []}}
    )
    return ASK_INTERESTS

async def ask_interests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    if query.data == "interest_done":
        await query.message.reply_text(
            "لطفاً موقعیت مکانی خود را ارسال کنید یا رد کنید:",
            reply_markup=location_keyboard
        )
        return ASK_LOCATION
    elif query.data.startswith("interest_"):
        interest = query.data.replace("interest_", "")
        interests_map = {
            "music": "موسیقی",
            "sport": "ورزش",
            "movie": "فیلم",
            "book": "کتاب"
        }
        if interest in interests_map:
            users_collection.update_one(
                {"telegram_id": user_id},
                {"$addToSet": {"profile.interests": interests_map[interest]}}
            )
            await query.message.reply_text(
                f"علاقه '{interests_map[interest]}' اضافه شد. ادامه دهید یا 'تکمیل انتخاب' را بزنید:",
                reply_markup=interests_keyboard
            )
        return ASK_INTERESTS
    else:
        await query.message.reply_text("لطفاً یکی از گزینه‌ها را انتخاب کنید.")
        return ASK_INTERESTS

async def ask_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    location = update.message.location
    text = update.message.text
    if text and text == "رد کردن":
        users_collection.update_one(
            {"telegram_id": user_id},
            {"$set": {"profile.location": None}}
        )
    elif location:
        users_collection.update_one(
            {"telegram_id": user_id},
            {"$set": {"profile.location": {
                "latitude": location.latitude,
                "longitude": location.longitude
            }}}
        )
    else:
        await update.message.reply_text(
            "لطفاً موقعیت ارسال کنید یا 'رد کردن' را انتخاب کنید.",
            reply_markup=location_keyboard
        )
        return ASK_LOCATION

    users_collection.update_one(
        {"telegram_id": user_id},
        {"$set": {"registered": True}}
    )

    user = users_collection.find_one({"telegram_id": user_id})
    gender_value = user["profile"]["gender"]
    await update.message.reply_text(
        f"✅ ثبت‌نام انجام شد.\n"
        f"سن: {user['profile']['age']}\n"
        f"جنسیت: {'مرد' if gender_value == 'male' else 'زن'}\n"
        f"نام مستعار: {user['profile']['nickname']}\n"
        f"علایق: {', '.join(user['profile']['interests']) if user['profile']['interests'] else 'هیچ'}\n"
        f"موقعیت: {'ارسال شده' if user['profile']['location'] else 'ارسال نشده'}\n"
        f"{'شما ادمین هستید.' if user.get('is_admin') else 'کاربر عادی هستید.'}\n"
        "برای شروع جستجو دکمه‌ها را استفاده کنید.",
        reply_markup=main_keyboard
    )
    return REGISTERED

async def edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.callback_query.from_user.id
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "کدام بخش پروفایل را می‌خواهید ویرایش کنید؟",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("سن", callback_data="edit_age"),
             InlineKeyboardButton("جنسیت", callback_data="edit_gender")],
            [InlineKeyboardButton("نام مستعار", callback_data="edit_nickname"),
             InlineKeyboardButton("علایق", callback_data="edit_interests")],
            [InlineKeyboardButton("موقعیت", callback_data="edit_location")]
        ])
    )
    return REGISTERED

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    logger.debug(f"Button pressed by {user_id}: {data}")
    if not users_collection.find_one({"telegram_id": user_id}):
        await query.message.reply_text("❌ لطفاً ابتدا /start را بزنید و ثبت نام کنید.")
        return
    if data == "search":
        await query.message.reply_text(
            "جنسیت شریک مورد نظر خود را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("مرد", callback_data="partner_male"),
                 InlineKeyboardButton("زن", callback_data="partner_female")]
            ])
        )
        return ASK_PARTNER_GENDER
    elif data == "end":
        await end_chat(user_id, context)
    elif data == "skip":
        await skip_chat(user_id, context)
    elif data == "block":
        await block_partner(user_id, context)
    elif data == "report":
        await report_partner(user_id, context)
    elif data == "status":
        await send_status(user_id, context)
    elif data == "edit_profile":
        await edit_profile(update, context)
    elif data.startswith("edit_"):
        if data == "edit_age":
            await query.message.reply_text("لطفاً سن جدید را وارد کنید (عدد بین 10 تا 99):")
            context.user_data["edit_field"] = "age"
            return REGISTERED
        elif data == "edit_gender":
            await query.message.reply_text(
                "جنسیت جدید را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("مرد", callback_data="gender_male"),
                     InlineKeyboardButton("زن", callback_data="gender_female")]
                ])
            )
            return ASK_GENDER
        elif data == "edit_nickname":
            await query.message.reply_text("لطفاً نام مستعار جدید را وارد کنید (حداکثر 20 کاراکتر):")
            context.user_data["edit_field"] = "nickname"
            return REGISTERED
        elif data == "edit_interests":
            users_collection.update_one(
                {"telegram_id": user_id},
                {"$set": {"profile.interests": []}}
            )
            await query.message.reply_text(
                "علایق جدید را انتخاب کنید (می‌توانید چند گزینه را انتخاب کنید و در آخر 'تکمیل انتخاب' را بزنید):",
                reply_markup=interests_keyboard
            )
            return ASK_INTERESTS
        elif data == "edit_location":
            await query.message.reply_text(
                "لطفاً موقعیت مکانی جدید را ارسال کنید یا رد کنید:",
                reply_markup=location_keyboard
            )
            return ASK_LOCATION

async def handle_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    edit_field = context.user_data.get("edit_field")
    if edit_field == "age":
        text = update.message.text
        if not text.isdigit() or not (10 <= int(text) <= 99):
            await update.message.reply_text("لطفاً سن را عددی بین 10 تا 99 وارد کنید.")
            return REGISTERED
        users_collection.update_one(
            {"telegram_id": user_id},
            {"$set": {"profile.age": int(text)}}
        )
        await update.message.reply_text("سن به‌روزرسانی شد.", reply_markup=main_keyboard)
    elif edit_field == "nickname":
        nickname = update.message.text.strip()
        if len(nickname) > 20:
            await update.message.reply_text("نام مستعار باید حداکثر 20 کاراکتر باشد.")
            return REGISTERED
        users_collection.update_one(
            {"telegram_id": user_id},
            {"$set": {"profile.nickname": nickname}}
        )
        await update.message.reply_text("نام مستعار به‌روزرسانی شد.", reply_markup=main_keyboard)
    return REGISTERED

async def partner_gender_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    data = query.data
    logger.debug(f"Partner gender selected by {user_id}: {data}")
    if query.data not in ["partner_male", "partner_female"]:
        await query.message.reply_text("لطفاً یکی از گزینه‌ها را انتخاب کنید.")
        return ASK_PARTNER_GENDER

    partner_gender = "male" if query.data == "partner_male" else "female"
    context.user_data["partner_gender"] = partner_gender
    await query.message.reply_text("در حال جستجو برای شریک شما ...")
    await search_chat(user_id, context)
    return REGISTERED

async def search_chat(user_id, context):
    user = users_collection.find_one({"telegram_id": user_id})
    if not user:
        await context.bot.send_message(user_id, "لطفاً ابتدا ثبت‌نام کنید.")
        return
    logger.debug(f"User {user_id} starting search. Age: {user['profile']['age']}, Gender: {user['profile']['gender']}")
    
    if has_valid_subscription(user_id):
        can_chat = True
    else:
        if user.get("chat_count", 0) >= FREE_CHAT_LIMIT:
            await prompt_for_payment(user_id, context)
            return
        can_chat = True

    if redis_client.sismember("active_chats", user_id):
        await context.bot.send_message(user_id, "❗ شما در حال چت هستید. برای پایان دادن از دکمه پایان استفاده کنید.")
        return
    if redis_client.sismember("waiting_users", user_id):
        await context.bot.send_message(user_id, "⌛ در صف انتظار هستید...")
        return

    user_age = user["profile"]["age"]
    partner_gender = context.user_data.get("partner_gender", "female" if user["profile"]["gender"] == "male" else "male")
    logger.debug(f"Searching for partner. Target gender: {partner_gender}, Age: {user_age}")

    partner_id = None
    for candidate_id in redis_client.smembers("waiting_users"):
        candidate_id = int(candidate_id.decode())
        if candidate_id == user_id:
            continue
        candidate = users_collection.find_one({"telegram_id": candidate_id})
        if not candidate:
            continue
        logger.debug(f"Checking candidate {candidate_id}. Gender: {candidate['profile']['gender']}, Age: {candidate['profile']['age']}")
        if candidate["profile"]["gender"] != partner_gender:
            continue
        age_diff = abs(candidate["profile"]["age"] - user_age)
        if age_diff > 10:
            continue
        if users_collection.find_one({"telegram_id": user_id, "blocked_users": candidate_id}):
            continue
        if users_collection.find_one({"telegram_id": candidate_id, "blocked_users": user_id}):
            continue
        if redis_client.sismember("active_chats", candidate_id):
            continue
        partner_id = candidate_id
        break

    if partner_id:
        logger.debug(f"Match found! Pairing {user_id} with {partner_id}")
        redis_client.srem("waiting_users", partner_id)
        redis_client.sadd("active_chats", user_id)
        redis_client.sadd("active_chats", partner_id)
        sessions_collection.insert_one({
            "user1": user_id,
            "user2": partner_id,
            "start_time": datetime.now()
        })
        users_collection.update_one({"telegram_id": user_id}, {"$inc": {"chat_count": 1}})
        users_collection.update_one({"telegram_id": partner_id}, {"$inc": {"chat_count": 1}})

        await context.bot.send_message(user_id, "✅ شما به یک شریک متصل شدید. شروع گفتگو کنید.")
        await context.bot.send_message(partner_id, "✅ شما به یک شریک متصل شدید. شروع گفتگو کنید.")
    else:
        logger.debug(f"No match for {user_id}. Adding to waiting_users.")
        redis_client.sadd("waiting_users", user_id)
        await context.bot.send_message(user_id, "⌛ در حال جستجو برای شریک مناسب... لطفاً کمی صبر کنید.")

async def end_chat(user_id, context):
    session = sessions_collection.find_one({"$or": [{"user1": user_id}, {"user2": user_id}]})
    if not session:
        await context.bot.send_message(user_id, "شما در حال حاضر در چتی نیستید.")
        return
    partner_id = session["user2"] if session["user1"] == user_id else session["user1"]
    redis_client.srem("active_chats", user_id)
    redis_client.srem("active_chats", partner_id)
    redis_client.sadd("waiting_users", partner_id)
    sessions_collection.delete_one({"_id": session["_id"]})
    await context.bot.send_message(user_id, "💔 چت پایان یافت.")
    await context.bot.send_message(partner_id, "💔 شریک شما چت را پایان داد.")

async def skip_chat(user_id, context):
    await end_chat(user_id, context)
    await search_chat(user_id, context)

async def block_partner(user_id, context):
    session = sessions_collection.find_one({"$or": [{"user1": user_id}, {"user2": user_id}]})
    if not session:
        await context.bot.send_message(user_id, "شما در چت نیستید تا بتوانید بلاک کنید.")
        return
    partner_id = session["user2"] if session["user1"] == user_id else session["user1"]
    users_collection.update_one(
        {"telegram_id": user_id},
        {"$addToSet": {"blocked_users": partner_id}}
    )
    await end_chat(user_id, context)
    await context.bot.send_message(user_id, "شریک چت بلاک شد.")

async def report_partner(user_id, context):
    session = sessions_collection.find_one({"$or": [{"user1": user_id}, {"user2": user_id}]})
    if not session:
        await context.bot.send_message(user_id, "شما در چت نیستید تا بتوانید ریپورت کنید.")
        return
    partner_id = session["user2"] if session["user1"] == user_id else session["user1"]
    users_collection.update_one(
        {"telegram_id": partner_id},
        {"$inc": {"reports": 1}}
    )
    await context.bot.send_message(user_id, "شریک چت ریپورت شد.")
    await end_chat(user_id, context)

async def send_status(user_id, context):
    user = users_collection.find_one({"telegram_id": user_id})
    if not user:
        await context.bot.send_message(user_id, "شما ثبت نام نکرده‌اید.")
        return
    chats_done = user.get("chat_count", 0)
    subs = user.get("subscription_expiry")
    subs_text = f"اشتراک تا {subs.strftime('%Y-%m-%d %H:%M:%S')}" if subs else "اشتراک فعال نیست"
    interests = ', '.join(user['profile']['interests']) if user['profile']['interests'] else 'هیچ'
    location = 'ارسال شده' if user['profile']['location'] else 'ارسال نشده'
    await context.bot.send_message(
        user_id,
        f"سن: {user['profile']['age']}\n"
        f"جنسیت: {'مرد' if user['profile']['gender'] == 'male' else 'زن'}\n"
        f"نام مستعار: {user['profile']['nickname']}\n"
        f"علایق: {interests}\n"
        f"موقعیت: {location}\n"
        f"تعداد چت‌های انجام شده: {chats_done}\n"
        f"{subs_text}"
    )

async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = sessions_collection.find_one({"$or": [{"user1": user_id}, {"user2": user_id}]})
    if not session:
        await update.message.reply_text("❌ شما به هیچ شریکی متصل نیستید.")
        return
    partner_id = session["user2"] if session["user1"] == user_id else session["user1"]
    if update.message.text:
        await context.bot.send_message(partner_id, update.message.text)
    elif update.message.photo:
        await context.bot.send_photo(partner_id, update.message.photo[-1].file_id)
    elif update.message.video:
        await context.bot.send_video(partner_id, update.message.video.file_id)
    elif update.message.sticker:
        await context.bot.send_sticker(partner_id, update.message.sticker.file_id)
    elif update.message.animation:
        await context.bot.send_animation(partner_id, update.message.animation.file_id)
    else:
        await update.message.reply_text("نوع پیام پشتیبانی نمی‌شود.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 سلام! به ربات چت ناشناس خوش آمدید.\n\n"
        "دکمه‌ها و دستورها:\n"
        "🔍 جستجو: شروع جستجو برای شریک چت\n"
        "✂️ پایان: پایان دادن به چت فعلی\n"
        "🔁 بعدی: رد کردن شریک فعلی و جستجوی شریک جدید\n"
        "🚫 بلاک: بلاک کردن شریک فعلی\n"
        "🚨 ریپورت: گزارش دادن شریک چت\n"
        "⚙️ وضعیت: نمایش وضعیت حساب و اشتراک\n"
        "✏️ ویرایش پروفایل: تغییر اطلاعات پروفایل\n\n"
        "برای ثبت‌نام ابتدا /start را بزنید.",
        reply_markup=main_keyboard
    )

async def periodic_matchmaking(context: ContextTypes.DEFAULT_TYPE):
    logger.debug("Starting periodic matchmaking...")
    waiting_users = redis_client.smembers("waiting_users")
    logger.debug(f"Periodic matchmaking: {len(waiting_users)} users in queue")
    for user_id in waiting_users:
        user_id = int(user_id.decode())
        if not redis_client.sismember("active_chats", user_id):
            logger.debug(f"Attempting to match user {user_id}")
            await search_chat(user_id, context)

async def main():
    try:
        application = ApplicationBuilder().token(TOKEN).build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                ASK_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_age)],
                ASK_GENDER: [CallbackQueryHandler(ask_gender, pattern="^gender_.*$")],
                ASK_PHONE: [
                    MessageHandler(filters.CONTACT, ask_phone),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)
                ],
                ASK_NICKNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_nickname)],
                ASK_INTERESTS: [CallbackQueryHandler(ask_interests, pattern="^interest_.*$")],
                ASK_LOCATION: [
                    MessageHandler(filters.LOCATION, ask_location),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, ask_location)
                ],
                REGISTERED: [
                    CallbackQueryHandler(button_handler),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_field),
                    MessageHandler(filters.PHOTO, forward_message),
                    MessageHandler(filters.VIDEO, forward_message),
                    MessageHandler(filters.ANIMATION, forward_message),  # اضافه کردن مدیریت انیمیشن
                    MessageHandler(filters.Sticker.ALL, forward_message),
                ],
                ASK_PARTNER_GENDER: [
                    CallbackQueryHandler(partner_gender_handler, pattern="^partner_.*$")
                ]
            },
            fallbacks=[CommandHandler("help", help_command)],
            per_message=False
        )

        application.add_handler(conv_handler)
        application.add_handler(CommandHandler("help", help_command))

        # ایجاد ایندکس‌ها برای عملکرد بهتر
        users_collection.create_index("telegram_id")
        sessions_collection.create_index([("user1", 1), ("user2", 1)])

        logger.info("ربات در حال اجرا است...")
        await application.initialize()
        await application.start()
        application.job_queue.run_repeating(periodic_matchmaking, interval=5, first=0)

        await application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        await asyncio.Event().wait()
    except Exception as e:
        logger.error(f"خطا در اجرای ربات: {e}")
        raise
    finally:
        if application.updater.running:
            await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"خطا در راه‌اندازی حلقه: {e}")