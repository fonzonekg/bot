import telebot
from telebot import types
import json
import hashlib
import requests
from datetime import datetime, timedelta
import time
import threading
import re
import os
import logging

# ===== НАСТРОЙКИ =====
# ⚠️ ВНИМАНИЕ: ЗАМЕНИТЕ ЭТИ ТОКЕНЫ НА СВОИ!
TOKEN = "8397567369:AAFki44pWtxP5M9iPGEn26yvUsu1Fv-9g3o"  # Получите у @BotFather
CRYPTO_BOT_API_KEY = "498509:AABNPgPwTiCU9DdByIgswTvIuSz5VO9neRy"  # Получите в @CryptoBot через /pay
ADMIN_IDS = [7577716374]  # Ваш Telegram ID (замените на свой)
CHANNEL_ID = "@FonZoneKg"  # Канал для публикации объявлений
SUPPORT_CHAT_ID = "@FONZONE_CL"  # Чат для поддержки
MAX_PHOTOS = 4
MIN_PHOTOS = 2

# ===== ЛОГИРОВАНИЕ =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===== CryptoBot API КОНФИГУРАЦИЯ =====
CRYPTO_BOT_API_URL = "https://pay.crypt.bot/api/"
CRYPTO_BOT_HEADERS = {
    "Crypto-Pay-API-Token": CRYPTO_BOT_API_KEY,
    "Content-Type": "application/json"
}

# ===== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ =====
users_data = {}
active_ads = {}
user_states = {}
ad_drafts = {}
message_history = {}
invoices = {}
premium_users = set()
support_messages = {}
user_contacts = {}
broadcast_data = {}

# ===== МОДЕЛИ ТЕЛЕФОНОВ =====
phone_models = [
    {"id": 1, "brand": "Apple", "model": "iPhone 15 Pro", "variants": ["128GB", "256GB", "512GB", "1TB"]},
    {"id": 2, "brand": "Apple", "model": "iPhone 15", "variants": ["128GB", "256GB", "512GB"]},
    {"id": 3, "brand": "Samsung", "model": "Galaxy S24 Ultra", "variants": ["256GB", "512GB", "1TB"]},
    {"id": 4, "brand": "Samsung", "model": "Galaxy Z Fold5", "variants": ["256GB", "512GB", "1TB"]},
    {"id": 5, "brand": "Xiaomi", "model": "14 Pro", "variants": ["256GB", "512GB"]},
    {"id": 6, "brand": "Google", "model": "Pixel 8 Pro", "variants": ["128GB", "256GB", "512GB"]},
    {"id": 7, "brand": "OnePlus", "model": "12", "variants": ["256GB", "512GB"]},
    {"id": 8, "brand": "Nothing", "model": "Phone(2)", "variants": ["128GB", "256GB"]},
    {"id": 9, "brand": "Apple", "model": "iPhone 14 Pro", "variants": ["128GB", "256GB", "512GB"]},
    {"id": 10, "brand": "Samsung", "model": "Galaxy S23", "variants": ["128GB", "256GB"]},
]

# ===== ИНИЦИАЛИЗАЦИЯ БОТА =====
bot = telebot.TeleBot(TOKEN)

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def get_main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(types.KeyboardButton("📱 Создать объявление"))
    keyboard.add(types.KeyboardButton("📋 Мои объявления"))
    keyboard.add(types.KeyboardButton("❓ Помощь"), types.KeyboardButton("💎 Донат"))
    keyboard.add(types.KeyboardButton("📞 Поддержка"))
    return keyboard

def get_cancel_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("❌ Отмена"))
    return keyboard

def get_condition_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton("Новый", callback_data="condition:new"),
        types.InlineKeyboardButton("Как новый", callback_data="condition:like_new"),
        types.InlineKeyboardButton("Среднее", callback_data="condition:good"),
        types.InlineKeyboardButton("Слегка повреждён", callback_data="condition:damaged"),
        types.InlineKeyboardButton("⬅️ Назад", callback_data="back")
    ]
    keyboard.add(*buttons[:2])
    keyboard.add(*buttons[2:4])
    keyboard.add(buttons[4])
    return keyboard

def get_yes_no_keyboard(prefix):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("Да", callback_data=f"{prefix}:yes"),
        types.InlineKeyboardButton("Нет", callback_data=f"{prefix}:no"),
        types.InlineKeyboardButton("⬅️ Назад", callback_data="back")
    )
    return keyboard

def get_models_keyboard(page=0, search=""):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    models_per_page = 8
    
    if search:
        filtered = [m for m in phone_models if search.lower() in f"{m['brand']} {m['model']}".lower()]
    else:
        filtered = phone_models
    
    start = page * models_per_page
    end = start + models_per_page
    page_models = filtered[start:end]
    
    for model in page_models:
        name = f"{model['brand']} {model['model']}"
        keyboard.add(types.InlineKeyboardButton(name, callback_data=f"model:{model['id']}"))
    
    buttons = []
    if page > 0:
        buttons.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"page:{page-1}:{search}"))
    if end < len(filtered):
        buttons.append(types.InlineKeyboardButton("Вперед ➡️", callback_data=f"page:{page+1}:{search}"))
    
    if buttons:
        keyboard.row(*buttons)
    
    if not search:
        keyboard.add(types.InlineKeyboardButton("🔍 Поиск модели", callback_data="search_model"))
    
    keyboard.add(types.InlineKeyboardButton("📝 Другая модель", callback_data="model:other"))
    keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
    
    return keyboard

def cleanup_user_messages(user_id):
    """Очистить все предыдущие сообщения бота у пользователя"""
    if user_id in message_history:
        for msg_id in message_history[user_id]:
            try:
                bot.delete_message(user_id, msg_id)
            except Exception as e:
                logger.debug(f"Не удалось удалить сообщение {msg_id}: {e}")
        message_history[user_id] = []

def save_message_id(user_id, msg_id):
    """Сохранить ID сообщения для последующего удаления"""
    if user_id not in message_history:
        message_history[user_id] = []
    message_history[user_id].append(msg_id)

def validate_price(text):
    try:
        price = int(text.replace(" ", "").replace(",", "").replace(".", ""))
        return 100 <= price <= 1000000, price
    except:
        return False, 0

def generate_ad_id(user_id):
    timestamp = int(datetime.now().timestamp())
    return f"{user_id}_{timestamp}"

def reset_user_state(user_id):
    if user_id in user_states:
        del user_states[user_id]
    if user_id in ad_drafts:
        del ad_drafts[user_id]
    cleanup_user_messages(user_id)

# ===== CryptoBot API ФУНКЦИИ =====
def create_invoice(amount, currency="USDT", description="", payload=""):
    """Создать инвойс для оплаты через CryptoBot API"""
    url = CRYPTO_BOT_API_URL + "createInvoice"
    data = {
        "asset": currency,
        "amount": str(amount),
        "description": description,
        "hidden_message": "Оплата через CryptoBot",
        "paid_btn_name": "viewItem",
        "paid_btn_url": "https://t.me/yourbot",
        "payload": payload
    }
    
    try:
        response = requests.post(url, headers=CRYPTO_BOT_HEADERS, json=data, timeout=10)
        result = response.json()
        
        if result.get("ok"):
            invoice_data = result["result"]
            invoice_id = invoice_data["invoice_id"]
            
            invoices[invoice_id] = {
                "user_id": payload,
                "amount": amount,
                "currency": currency,
                "status": "active",
                "created_at": datetime.now().isoformat(),
                "pay_url": invoice_data["pay_url"],
                "invoice_data": invoice_data
            }
            logger.info(f"Инвойс создан: {invoice_id} для пользователя {payload}")
            return invoice_data
        else:
            logger.error(f"CryptoBot API Error: {result}")
            return None
    except Exception as e:
        logger.error(f"CryptoBot API Error: {e}")
        return None

def get_invoice_status(invoice_id):
    """Получить статус инвойса через CryptoBot API"""
    url = CRYPTO_BOT_API_URL + "getInvoices"
    data = {
        "invoice_ids": [invoice_id]
    }
    
    try:
        response = requests.post(url, headers=CRYPTO_BOT_HEADERS, json=data, timeout=10)
        result = response.json()
        
        if result.get("ok") and result["result"]["items"]:
            invoice = result["result"]["items"][0]
            return invoice.get("status", "active")
    except Exception as e:
        logger.error(f"CryptoBot API Error: {e}")
    
    return None

def send_to_channel(ad):
    """Отправить объявление в канал"""
    try:
        premium_badge = "💎 ПРЕМИУМ ОБЪЯВЛЕНИЕ\n\n" if ad.get('is_premium') else ""
        
        ad_text = f"""
{premium_badge}📱 {ad.get('model', 'Не указано')}
📊 Состояние: {ad.get('condition', 'Не указано')}
💾 Память: {ad.get('memory', 'Не указана')}
🎨 Цвет: {ad.get('color', 'Не указан')}
📦 Коробка: {'Да' if ad.get('has_box') else 'Нет'}
📄 Документы: {'Да' if ad.get('has_docs') else 'Нет'}
🔧 Комплектация: {ad.get('accessories', 'Не указана')}
💰 Цена: {ad.get('price', 0)} сом
📍 {ad.get('city', 'Не указан')} {f'({ad.get("metro")})' if ad.get('metro') else ''}
📅 Опубликовано: {datetime.fromisoformat(ad['created_at']).strftime('%d.%m.%Y')}
👁 Просмотры: {ad.get('views', 0)}

📞 Для связи оставьте свой номер телефона или нажмите кнопку ниже:
"""
        
        photos = ad.get('photos', [])
        if photos:
            if len(photos) == 1:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(
                    types.InlineKeyboardButton("📞 Связаться", callback_data=f"contact:{ad['id']}:{ad['user_id']}"),
                    types.InlineKeyboardButton("📲 Поделиться контактом", callback_data=f"share_contact:{ad['id']}")
                )
                keyboard.add(types.InlineKeyboardButton("⚠️ Пожаловаться", callback_data=f"report:{ad['id']}"))
                
                bot.send_photo(
                    CHANNEL_ID,
                    photos[0],
                    caption=ad_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            else:
                media = []
                for i, photo in enumerate(photos):
                    if i == 0:
                        media.append(types.InputMediaPhoto(photo, caption=ad_text, parse_mode="HTML"))
                    else:
                        media.append(types.InputMediaPhoto(photo))
                
                bot.send_media_group(CHANNEL_ID, media)
                
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(
                    types.InlineKeyboardButton("📞 Связаться", callback_data=f"contact:{ad['id']}:{ad['user_id']}"),
                    types.InlineKeyboardButton("📲 Поделиться контактом", callback_data=f"share_contact:{ad['id']}")
                )
                keyboard.add(types.InlineKeyboardButton("⚠️ Пожаловаться", callback_data=f"report:{ad['id']}"))
                
                bot.send_message(CHANNEL_ID, "Выберите действие:", reply_markup=keyboard)
        else:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("📞 Связаться", callback_data=f"contact:{ad['id']}:{ad['user_id']}"),
                types.InlineKeyboardButton("📲 Поделиться контактом", callback_data=f"share_contact:{ad['id']}")
            )
            keyboard.add(types.InlineKeyboardButton("⚠️ Пожаловаться", callback_data=f"report:{ad['id']}"))
            
            bot.send_message(CHANNEL_ID, ad_text, reply_markup=keyboard, parse_mode="HTML")
        
        logger.info(f"Объявление {ad['id']} опубликовано в канале")
        return True
    except Exception as e:
        logger.error(f"Error sending to channel: {e}")
        return False

# ===== ФУНКЦИИ РАССЫЛКИ =====
def broadcast_to_all_users(message_text, message_type='text', photo=None, admin_id=None):
    """Рассылка всем пользователям"""
    total_users = len(users_data)
    successful = 0
    failed = 0
    
    if total_users == 0:
        return 0, 0, "Нет пользователей для рассылки"
    
    progress_msg = None
    if admin_id:
        progress_msg = bot.send_message(admin_id, f"🔄 Начинаю рассылку для {total_users} пользователей...")
    
    for i, (user_id, user_data) in enumerate(users_data.items(), 1):
        try:
            if message_type == 'photo' and photo:
                bot.send_photo(user_id, photo, caption=message_text, parse_mode="HTML")
            else:
                bot.send_message(user_id, message_text, parse_mode="HTML")
            
            successful += 1
            
            if admin_id and i % 10 == 0:
                try:
                    bot.edit_message_text(
                        chat_id=admin_id,
                        message_id=progress_msg.message_id,
                        text=f"🔄 Рассылка: {i}/{total_users} пользователей\n✅ Успешно: {successful}\n❌ Ошибок: {failed}"
                    )
                except:
                    pass
            
            time.sleep(0.1)
            
        except Exception as e:
            failed += 1
            logger.error(f"Ошибка рассылки пользователю {user_id}: {e}")
    
    if admin_id and progress_msg:
        try:
            bot.edit_message_text(
                chat_id=admin_id,
                message_id=progress_msg.message_id,
                text=f"✅ Рассылка завершена!\n📊 Статистика:\n• Всего пользователей: {total_users}\n• Успешно отправлено: {successful}\n• Ошибок: {failed}"
            )
        except:
            pass
    
    return successful, failed, "Рассылка завершена"

def broadcast_to_user(user_id, message_text, message_type='text', photo=None):
    """Рассылка конкретному пользователю"""
    try:
        if message_type == 'photo' and photo:
            bot.send_photo(user_id, photo, caption=message_text, parse_mode="HTML")
        else:
            bot.send_message(user_id, message_text, parse_mode="HTML")
        return True, "Сообщение отправлено"
    except Exception as e:
        return False, f"Ошибка: {e}"

def broadcast_to_list(user_ids, message_text, message_type='text', photo=None, admin_id=None):
    """Рассылка списку пользователей"""
    total_users = len(user_ids)
    successful = 0
    failed = 0
    failed_list = []
    
    if total_users == 0:
        return 0, 0, [], "Нет пользователей для рассылки"
    
    progress_msg = None
    if admin_id:
        progress_msg = bot.send_message(admin_id, f"🔄 Начинаю рассылку для {total_users} пользователей...")
    
    for i, user_id in enumerate(user_ids, 1):
        try:
            user_id_int = int(user_id.strip())
            if message_type == 'photo' and photo:
                bot.send_photo(user_id_int, photo, caption=message_text, parse_mode="HTML")
            else:
                bot.send_message(user_id_int, message_text, parse_mode="HTML")
            
            successful += 1
            
            if admin_id and i % 5 == 0:
                try:
                    bot.edit_message_text(
                        chat_id=admin_id,
                        message_id=progress_msg.message_id,
                        text=f"🔄 Рассылка: {i}/{total_users} пользователей\n✅ Успешно: {successful}\n❌ Ошибок: {failed}"
                    )
                except:
                    pass
            
            time.sleep(0.2)
            
        except Exception as e:
            failed += 1
            failed_list.append(str(user_id))
            logger.error(f"Ошибка рассылки пользователю {user_id}: {e}")
    
    if admin_id and progress_msg:
        result_text = f"✅ Рассылка завершена!\n📊 Статистика:\n• Всего пользователей: {total_users}\n• Успешно отправлено: {successful}\n• Ошибок: {failed}"
        
        if failed_list:
            result_text += f"\n\n❌ Ошибки у пользователей: {', '.join(failed_list[:10])}"
            if len(failed_list) > 10:
                result_text += f" и еще {len(failed_list) - 10}..."
        
        try:
            bot.edit_message_text(
                chat_id=admin_id,
                message_id=progress_msg.message_id,
                text=result_text
            )
        except:
            pass
    
    return successful, failed, failed_list, "Рассылка завершена"

# ===== ФОНОВАЯ ПРОВЕРКА ПЛАТЕЖЕЙ =====
def check_payments_loop():
    """Фоновая проверка статуса платежей"""
    while True:
        try:
            for invoice_id, invoice_data in list(invoices.items()):
                if invoice_data["status"] == "active":
                    status = get_invoice_status(invoice_id)
                    if status:
                        invoices[invoice_id]["status"] = status
                        
                        if status == "paid":
                            user_id = invoice_data.get("user_id")
                            if user_id:
                                premium_users.add(user_id)
                                if user_id in users_data:
                                    users_data[user_id]["is_premium"] = True
                                    users_data[user_id]["premium_until"] = (datetime.now() + timedelta(days=30)).isoformat()
                                
                                for ad_id, ad in active_ads.items():
                                    if ad.get('user_id') == user_id:
                                        ad['is_premium'] = True
                                
                                try:
                                    bot.send_message(user_id, "✅ Ваш PREMIUM статус активирован! Теперь все ваши объявления будут выделяться.")
                                    logger.info(f"Premium активирован для пользователя {user_id}")
                                except:
                                    pass
            time.sleep(30)
        except Exception as e:
            logger.error(f"Payment checker error: {e}")
            time.sleep(60)

threading.Thread(target=check_payments_loop, daemon=True).start()

# ===== ОСНОВНЫЕ КОМАНДЫ =====
@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    
    cleanup_user_messages(user_id)
    
    if user_id not in users_data:
        users_data[user_id] = {
            "username": message.from_user.username,
            "is_premium": user_id in premium_users,
            "created_at": datetime.now().isoformat(),
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name
        }
        logger.info(f"Новый пользователь: {user_id}")
    
    welcome_text = """
🤖 Добро пожаловать в бот для продажи телефонов!

📌 Основные правила:
• Запрещены мошеннические объявления
• Фото должны быть качественными
• Указывайте реальные цены
• Будьте вежливы с покупателями

Начните с кнопки "Создать объявление" ниже 👇
"""
    msg = bot.send_message(user_id, welcome_text, reply_markup=get_main_keyboard())
    save_message_id(user_id, msg.message_id)
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("📱 Создать объявление", callback_data="create_ad"),
        types.InlineKeyboardButton("📖 FAQ/Правила", callback_data="faq")
    )
    msg2 = bot.send_message(user_id, "Выберите действие:", reply_markup=keyboard)
    save_message_id(user_id, msg2.message_id)

@bot.message_handler(commands=['help'])
@bot.message_handler(func=lambda m: m.text == "❓ Помощь")
def cmd_help(message):
    user_id = message.from_user.id
    cleanup_user_messages(user_id)
    
    help_text = """
🆘 Помощь по боту:

📱 Создание объявления:
1. Нажмите "Создать объявление"
2. Выберите модель телефона
3. Укажите характеристики
4. Загрузите 2-4 фотографии
5. Подтвердите публикацию

💰 Донат через CryptoBot:
• Поддержите развитие бота криптовалютой
• Получите премиум-статус
• Выделение ваших объявлений

📞 Поддержка:
• Нажмите кнопку "Поддержка"
• Опишите вашу проблему
• Наш менеджер ответит вам
"""
    msg = bot.send_message(user_id, help_text, reply_markup=get_main_keyboard())
    save_message_id(user_id, msg.message_id)

@bot.message_handler(func=lambda m: m.text == "💎 Донат")
def cmd_donate(message):
    user_id = message.from_user.id
    cleanup_user_messages(user_id)
    
    donate_text = """
💎 Поддержите развитие бота через CryptoBot!

Ваша поддержка помогает:
• Развивать новые функции
• Улучшать стабильность работы
• Добавлять новые возможности

Премиум-статус включает:
✅ Выделение объявлений цветом
✅ Топ-позиция в поиске
✅ Приоритетная поддержка
✅ Аналитика просмотров

💰 299 сом/месяц (примерно 3 USDT)
"""
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("💳 Купить PREMIUM", callback_data="buy_premium"))
    keyboard.add(types.InlineKeyboardButton("🎁 Просто поддержать", callback_data="simple_donate"))
    keyboard.add(types.InlineKeyboardButton("🔄 Проверить оплату", callback_data="check_payment"))
    
    msg = bot.send_message(user_id, donate_text, reply_markup=keyboard)
    save_message_id(user_id, msg.message_id)

@bot.message_handler(func=lambda m: m.text == "📞 Поддержка")
def cmd_support(message):
    user_id = message.from_user.id
    cleanup_user_messages(user_id)
    
    support_text = """
📞 Техническая поддержка

Опишите вашу проблему или вопрос:
• Проблемы с созданием объявления
• Вопросы по оплате
• Жалобы на пользователей
• Предложения по улучшению

Наш менеджер ответит вам в течение 24 часов.
"""
    msg = bot.send_message(user_id, support_text, reply_markup=get_cancel_keyboard())
    save_message_id(user_id, msg.message_id)
    
    user_states[user_id] = "waiting_support"

@bot.message_handler(commands=['myads'])
@bot.message_handler(func=lambda m: m.text == "📋 Мои объявления")
def cmd_my_ads(message):
    user_id = message.from_user.id
    cleanup_user_messages(user_id)
    
    user_ads = []
    for ad_id, ad in active_ads.items():
        if ad.get('user_id') == user_id:
            user_ads.append(ad)
    
    if not user_ads:
        msg = bot.send_message(user_id, "У вас пока нет активных объявлений", 
                              reply_markup=get_main_keyboard())
        save_message_id(user_id, msg.message_id)
        return
    
    for ad in user_ads[:5]:
        is_premium = ad.get('is_premium', False)
        premium_badge = "💎 ПРЕМИУМ\n" if is_premium else ""
        
        ad_text = f"""
📱 {ad.get('model', 'Не указано')}
💵 Цена: {ad.get('price', 0)} сом
📍 {ad.get('city', 'Не указан')} {f'({ad.get("metro")})' if ad.get('metro') else ''}
📅 Опубликовано: {datetime.fromisoformat(ad['created_at']).strftime('%d.%m.%Y')}
👁 Просмотры: {ad.get('views', 0)}
{premium_badge}
"""
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_ad:{ad['id']}"),
            types.InlineKeyboardButton("❌ Удалить", callback_data=f"delete_ad:{ad['id']}")
        )
        keyboard.add(types.InlineKeyboardButton("📊 Статистика", callback_data=f"stats:{ad['id']}"))
        
        if ad.get('photos') and len(ad['photos']) > 0:
            try:
                if len(ad['photos']) == 1:
                    msg = bot.send_photo(user_id, ad['photos'][0], caption=ad_text, reply_markup=keyboard)
                else:
                    media = []
                    for i, photo in enumerate(ad['photos']):
                        if i == 0:
                            media.append(types.InputMediaPhoto(photo, caption=ad_text))
                        else:
                            media.append(types.InputMediaPhoto(photo))
                    
                    bot.send_media_group(user_id, media)
                    msg = bot.send_message(user_id, "Действия с объявлением:", reply_markup=keyboard)
                
                save_message_id(user_id, msg.message_id)
            except Exception as e:
                logger.error(f"Ошибка отправки фото: {e}")
                msg = bot.send_message(user_id, ad_text, reply_markup=keyboard)
                save_message_id(user_id, msg.message_id)
        else:
            msg = bot.send_message(user_id, ad_text, reply_markup=keyboard)
            save_message_id(user_id, msg.message_id)

# ===== СОЗДАНИЕ ОБЪЯВЛЕНИЯ =====
@bot.callback_query_handler(func=lambda call: call.data == "create_ad")
@bot.message_handler(func=lambda m: m.text == "📱 Создать объявление")
def start_create_ad(update):
    if hasattr(update, 'message'):
        user_id = update.from_user.id
        message = update.message
    else:
        user_id = update.from_user.id
        message = update
    
    user_states[user_id] = {
        "current": "select_model",
        "previous": []
    }
    ad_drafts[user_id] = {
        "user_id": user_id,
        "photos": []
    }
    
    cleanup_user_messages(user_id)
    
    msg = bot.send_message(user_id, "📱 Выберите модель телефона:", 
                          reply_markup=get_models_keyboard())
    save_message_id(user_id, msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('page:'))
def process_pagination(call):
    user_id = call.from_user.id
    if user_id not in user_states or user_states[user_id]["current"] != "select_model":
        bot.answer_callback_query(call.id, "Сессия устарела")
        return
    
    parts = call.data.split(':')
    page = int(parts[1])
    search = parts[2] if len(parts) > 2 else ""
    
    try:
        bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=get_models_keyboard(page, search)
        )
    except Exception as e:
        logger.error(f"Ошибка обновления пагинации: {e}")
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "search_model")
def search_model(call):
    user_id = call.from_user.id
    if user_id not in user_states:
        return
    
    user_states[user_id]["previous"].append(user_states[user_id]["current"])
    user_states[user_id]["current"] = "search_model"
    
    cleanup_user_messages(user_id)
    
    msg = bot.send_message(user_id, "🔍 Введите название модели для поиска:", 
                          reply_markup=get_cancel_keyboard())
    save_message_id(user_id, msg.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('model:'))
def select_model(call):
    user_id = call.from_user.id
    if user_id not in user_states:
        return
    
    model_id = call.data.split(':')[1]
    
    if model_id == 'other':
        user_states[user_id]["previous"].append(user_states[user_id]["current"])
        user_states[user_id]["current"] = "input_model"
        cleanup_user_messages(user_id)
        
        msg = bot.send_message(user_id, "📝 Введите модель телефона вручную:", 
                              reply_markup=get_cancel_keyboard())
        save_message_id(user_id, msg.message_id)
        bot.answer_callback_query(call.id)
        return
    
    model = None
    for m in phone_models:
        if str(m['id']) == model_id:
            model = m
            break
    
    if not model:
        bot.answer_callback_query(call.id, "Модель не найдена", show_alert=True)
        return
    
    ad_drafts[user_id]['model'] = f"{model['brand']} {model['model']}"
    user_states[user_id]["previous"].append(user_states[user_id]["current"])
    user_states[user_id]["current"] = "select_condition"
    
    cleanup_user_messages(user_id)
    
    msg = bot.send_message(user_id, "📊 Выберите состояние телефона:", 
                          reply_markup=get_condition_keyboard())
    save_message_id(user_id, msg.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('condition:'))
def process_condition(call):
    user_id = call.from_user.id
    if user_id not in user_states or user_states[user_id]["current"] != "select_condition":
        bot.answer_callback_query(call.id, "Сессия устарела")
        return
    
    condition = call.data.split(':')[1]
    conditions_map = {
        'new': 'Новый',
        'like_new': 'Как новый', 
        'good': 'Среднее',
        'damaged': 'Слегка повреждён'
    }
    
    if condition in conditions_map:
        ad_drafts[user_id]['condition'] = conditions_map[condition]
        user_states[user_id]["previous"].append("select_condition")
        user_states[user_id]["current"] = "select_memory"
        
        cleanup_user_messages(user_id)
        
        model_name = ad_drafts[user_id].get('model', '')
        variants = []
        for m in phone_models:
            if f"{m['brand']} {m['model']}" == model_name:
                variants = m['variants']
                break
        
        if variants:
            keyboard = types.InlineKeyboardMarkup(row_width=2)
            for variant in variants:
                keyboard.add(types.InlineKeyboardButton(variant, callback_data=f"memory:{variant}"))
            keyboard.add(types.InlineKeyboardButton("📝 Другой объем", callback_data="memory:other"))
            keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
            msg = bot.send_message(user_id, "💾 Выберите объем памяти:", reply_markup=keyboard)
        else:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
            msg = bot.send_message(user_id, "💾 Введите объем памяти (например, 128GB):", reply_markup=keyboard)
        
        save_message_id(user_id, msg.message_id)
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('memory:'))
def process_memory(call):
    user_id = call.from_user.id
    if user_id not in user_states or user_states[user_id]["current"] != "select_memory":
        bot.answer_callback_query(call.id, "Сессия устарела")
        return
    
    memory = call.data.split(':')[1]
    
    if memory == 'other':
        user_states[user_id]["previous"].append("select_memory")
        user_states[user_id]["current"] = "input_memory"
        cleanup_user_messages(user_id)
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
        msg = bot.send_message(user_id, "💾 Введите объем памяти (например, 128GB):", 
                              reply_markup=keyboard)
        save_message_id(user_id, msg.message_id)
        bot.answer_callback_query(call.id)
        return
    
    ad_drafts[user_id]['memory'] = memory
    user_states[user_id]["previous"].append("select_memory")
    user_states[user_id]["current"] = "input_color"
    
    cleanup_user_messages(user_id)
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
    msg = bot.send_message(user_id, "🎨 Введите цвет телефона:", 
                          reply_markup=keyboard)
    save_message_id(user_id, msg.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('box:'))
def process_box(call):
    user_id = call.from_user.id
    if user_id not in user_states:
        bot.answer_callback_query(call.id, "Сессия устарела")
        return
    
    has_box = call.data.split(':')[1] == 'yes'
    ad_drafts[user_id]['has_box'] = has_box
    
    user_states[user_id]["previous"].append("select_box")
    user_states[user_id]["current"] = "select_docs"
    
    cleanup_user_messages(user_id)
    
    msg = bot.send_message(user_id, "📄 Есть ли оригинальные документы?", 
                          reply_markup=get_yes_no_keyboard("docs"))
    save_message_id(user_id, msg.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('docs:'))
def process_docs(call):
    user_id = call.from_user.id
    if user_id not in user_states:
        bot.answer_callback_query(call.id, "Сессия устарела")
        return
    
    has_docs = call.data.split(':')[1] == 'yes'
    ad_drafts[user_id]['has_docs'] = has_docs
    
    user_states[user_id]["previous"].append("select_docs")
    user_states[user_id]["current"] = "select_accessories"
    
    cleanup_user_messages(user_id)
    
    msg = bot.send_message(user_id, "🔧 Есть ли дополнительные аксессуары (наушники, зарядка и т.д.)?", 
                          reply_markup=get_yes_no_keyboard("accessories"))
    save_message_id(user_id, msg.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('accessories:'))
def process_accessories(call):
    user_id = call.from_user.id
    if user_id not in user_states:
        bot.answer_callback_query(call.id, "Сессия устарела")
        return
    
    answer = call.data.split(':')[1]
    
    if answer == 'yes':
        user_states[user_id]["previous"].append("select_accessories")
        user_states[user_id]["current"] = "input_accessories"
        
        cleanup_user_messages(user_id)
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
        msg = bot.send_message(user_id, "🔧 Опишите комплектацию (например, наушники, зарядка, кабель):", 
                              reply_markup=keyboard)
        save_message_id(user_id, msg.message_id)
    else:
        ad_drafts[user_id]['accessories'] = "Нет"
        user_states[user_id]["previous"].append("select_accessories")
        user_states[user_id]["current"] = "input_price"
        
        cleanup_user_messages(user_id)
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
        msg = bot.send_message(user_id, "💰 Введите цену в сомах (только цифры):", 
                              reply_markup=keyboard)
        save_message_id(user_id, msg.message_id)
    
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=['photo'], 
                     func=lambda m: user_states.get(m.from_user.id, {}).get("current") == "upload_photos")
def handle_photos(message):
    user_id = message.from_user.id
    
    if user_id not in ad_drafts:
        return
    
    try:
        bot.delete_message(user_id, message.message_id)
    except:
        pass
    
    photo_id = message.photo[-1].file_id
    
    if 'photos' not in ad_drafts[user_id]:
        ad_drafts[user_id]['photos'] = []
    
    ad_drafts[user_id]['photos'].append(photo_id)
    
    cleanup_user_messages(user_id)
    
    photo_count = len(ad_drafts[user_id]['photos'])
    
    if photo_count >= MIN_PHOTOS:
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("✅ Достаточно, продолжить", callback_data="photos_done"),
            types.InlineKeyboardButton("➕ Добавить еще фото", callback_data="add_more_photos")
        )
        msg = bot.send_message(
            user_id,
            f"📸 Загружено {photo_count} фото (минимум {MIN_PHOTOS}).\n"
            f"Максимум можно загрузить {MAX_PHOTOS} фото.\n\n"
            "Хотите добавить еще фото или продолжить?",
            reply_markup=keyboard
        )
    else:
        remaining = MIN_PHOTOS - photo_count
        msg = bot.send_message(
            user_id,
            f"📸 Загружено {photo_count} фото. Нужно еще минимум {remaining} фото.\n"
            f"Отправьте следующее фото:",
            reply_markup=get_cancel_keyboard()
        )
    
    save_message_id(user_id, msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "photos_done")
def process_photos_done(call):
    user_id = call.from_user.id
    if user_id not in user_states:
        bot.answer_callback_query(call.id, "Сессия устарела")
        return
    
    photo_count = len(ad_drafts[user_id].get('photos', []))
    
    if photo_count < MIN_PHOTOS:
        bot.answer_callback_query(call.id, f"Нужно минимум {MIN_PHOTOS} фото", show_alert=True)
        return
    
    user_states[user_id]["previous"].append("upload_photos")
    user_states[user_id]["current"] = "confirm_ad"
    
    cleanup_user_messages(user_id)
    
    show_ad_preview(user_id)
    bot.answer_callback_query(call.id)

def show_ad_preview(user_id):
    """Показать превью объявления перед публикацией"""
    ad = ad_drafts.get(user_id)
    if not ad:
        return
    
    preview_text = f"""
📋 ПРЕВЬЮ ОБЪЯВЛЕНИЯ:

📱 Модель: {ad.get('model', 'Не указано')}
📊 Состояние: {ad.get('condition', 'Не указано')}
💾 Память: {ad.get('memory', 'Не указана')}
🎨 Цвет: {ad.get('color', 'Не указан')}
📦 Коробка: {'Да' if ad.get('has_box') else 'Нет'}
📄 Документы: {'Да' if ad.get('has_docs') else 'Нет'}
🔧 Комплектация: {ad.get('accessories', 'Не указана')}
💰 Цена: {ad.get('price', 0)} сом
📍 Город: {ad.get('city', 'Не указан')} {f'({ad.get("metro")})' if ad.get('metro') else ''}
📸 Фото: {len(ad.get('photos', []))} шт.
"""
    
    photos = ad.get('photos', [])
    if photos:
        if len(photos) == 1:
            msg = bot.send_photo(user_id, photos[0], caption=preview_text)
        else:
            media = []
            for i, photo in enumerate(photos):
                if i == 0:
                    media.append(types.InputMediaPhoto(photo, caption=preview_text))
                else:
                    media.append(types.InputMediaPhoto(photo))
            bot.send_media_group(user_id, media)
            msg = bot.send_message(user_id, "Предпросмотр объявления:")
        save_message_id(user_id, msg.message_id)
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✅ Опубликовать", callback_data="publish_ad"),
        types.InlineKeyboardButton("✏️ Редактировать", callback_data="edit_ad_draft"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad")
    )
    
    msg = bot.send_message(user_id, "Всё верно? Опубликовать объявление?", reply_markup=keyboard)
    save_message_id(user_id, msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "publish_ad")
def process_publish_ad(call):
    user_id = call.from_user.id
    if user_id not in ad_drafts:
        bot.answer_callback_query(call.id, "Черновик не найден")
        return
    
    required_fields = ['model', 'condition', 'memory', 'color', 'price', 'city', 'photos']
    ad = ad_drafts[user_id]
    
    missing_fields = []
    for field in required_fields:
        if field not in ad or not ad[field]:
            missing_fields.append(field)
    
    if missing_fields:
        bot.answer_callback_query(call.id, f"Заполните: {', '.join(missing_fields)}", show_alert=True)
        return
    
    if len(ad['photos']) < MIN_PHOTOS:
        bot.answer_callback_query(call.id, f"Нужно минимум {MIN_PHOTOS} фото", show_alert=True)
        return
    
    ad_id = generate_ad_id(user_id)
    ad['id'] = ad_id
    ad['user_id'] = user_id
    ad['created_at'] = datetime.now().isoformat()
    ad['views'] = 0
    ad['is_premium'] = (user_id in premium_users)
    
    active_ads[ad_id] = ad.copy()
    
    success = send_to_channel(ad)
    
    cleanup_user_messages(user_id)
    
    if success:
        del ad_drafts[user_id]
        if user_id in user_states:
            del user_states[user_id]
        
        bot.answer_callback_query(call.id, "✅ Объявление опубликовано!")
        
        msg = bot.send_message(
            user_id,
            f"✅ Ваше объявление успешно опубликовано!\n\n"
            f"ID объявления: {ad_id}\n"
            f"Просмотры: 0\n\n"
            f"Вы можете управлять объявлением через меню 'Мои объявления'.",
            reply_markup=get_main_keyboard()
        )
    else:
        bot.answer_callback_query(call.id, "❌ Ошибка публикации", show_alert=True)
        msg = bot.send_message(user_id, "❌ Ошибка при публикации объявления. Попробуйте позже.")
    
    save_message_id(user_id, msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "cancel_ad")
def process_cancel_ad(call):
    user_id = call.from_user.id
    reset_user_state(user_id)
    bot.answer_callback_query(call.id, "Создание отменено")
    
    msg = bot.send_message(user_id, "❌ Создание объявления отменено.", 
                          reply_markup=get_main_keyboard())
    save_message_id(user_id, msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "add_more_photos")
def process_add_more_photos(call):
    user_id = call.from_user.id
    if user_id not in user_states:
        bot.answer_callback_query(call.id, "Сессия устарела")
        return
    
    photo_count = len(ad_drafts[user_id].get('photos', []))
    
    if photo_count >= MAX_PHOTOS:
        bot.answer_callback_query(call.id, f"Максимум {MAX_PHOTOS} фото", show_alert=True)
        return
    
    msg = bot.send_message(
        user_id,
        f"📸 Отправьте следующее фото (загружено {photo_count} из {MAX_PHOTOS}):",
        reply_markup=get_cancel_keyboard()
    )
    save_message_id(user_id, msg.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "back")
def process_back(call):
    user_id = call.from_user.id
    if user_id not in user_states:
        bot.answer_callback_query(call.id, "Сессия устарела")
        return
    
    state = user_states[user_id]
    
    if state["previous"]:
        previous_state = state["previous"].pop()
        state["current"] = previous_state
        
        cleanup_user_messages(user_id)
        
        if previous_state == "select_model":
            msg = bot.send_message(user_id, "📱 Выберите модель телефона:", 
                                  reply_markup=get_models_keyboard())
        elif previous_state == "select_condition":
            msg = bot.send_message(user_id, "📊 Выберите состояние телефона:", 
                                  reply_markup=get_condition_keyboard())
        elif previous_state == "select_memory":
            model_name = ad_drafts[user_id].get('model', '')
            variants = []
            for m in phone_models:
                if f"{m['brand']} {m['model']}" == model_name:
                    variants = m['variants']
                    break
            
            if variants:
                keyboard = types.InlineKeyboardMarkup(row_width=2)
                for variant in variants:
                    keyboard.add(types.InlineKeyboardButton(variant, callback_data=f"memory:{variant}"))
                keyboard.add(types.InlineKeyboardButton("📝 Другой объем", callback_data="memory:other"))
                keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
                msg = bot.send_message(user_id, "💾 Выберите объем памяти:", reply_markup=keyboard)
            else:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
                msg = bot.send_message(user_id, "💾 Введите объем памяти (например, 128GB):", reply_markup=keyboard)
        elif previous_state == "input_color":
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
            msg = bot.send_message(user_id, "🎨 Введите цвет телефона:", 
                                  reply_markup=keyboard)
        elif previous_state == "select_box":
            msg = bot.send_message(user_id, "📦 Есть ли оригинальная коробка?", 
                                  reply_markup=get_yes_no_keyboard("box"))
        elif previous_state == "select_docs":
            msg = bot.send_message(user_id, "📄 Есть ли оригинальные документы?", 
                                  reply_markup=get_yes_no_keyboard("docs"))
        elif previous_state == "select_accessories":
            msg = bot.send_message(user_id, "🔧 Есть ли дополнительные аксессуары (наушники, зарядка и т.д.)?", 
                                  reply_markup=get_yes_no_keyboard("accessories"))
        elif previous_state == "input_accessories":
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
            msg = bot.send_message(user_id, "🔧 Опишите комплектацию (например, наушники, зарядка, кабель):", 
                                  reply_markup=keyboard)
        elif previous_state == "input_price":
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
            msg = bot.send_message(user_id, "💰 Введите цену в сомах (только цифры):", 
                                  reply_markup=keyboard)
        elif previous_state == "input_city":
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
            msg = bot.send_message(user_id, "📍 Введите город:", 
                                  reply_markup=keyboard)
        elif previous_state == "input_metro":
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
            msg = bot.send_message(user_id, "🚇 Введите станцию метро (или 'нет'):", 
                                  reply_markup=keyboard)
        elif previous_state == "upload_photos":
            photo_count = len(ad_drafts[user_id].get('photos', []))
            msg = bot.send_message(
                user_id,
                f"📸 Загружено {photo_count} фото. Отправьте следующее фото (минимум {MIN_PHOTOS}):",
                reply_markup=get_cancel_keyboard()
            )
        
        save_message_id(user_id, msg.message_id)
    
    bot.answer_callback_query(call.id)

# ===== ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ =====
@bot.message_handler(content_types=['text'])
def handle_text(message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    try:
        bot.delete_message(user_id, message.message_id)
    except:
        pass
    
    if user_states.get(user_id) == "waiting_support":
        support_msg = f"""
📩 Новое сообщение от пользователя:
ID: {user_id}
Username: @{message.from_user.username}
Имя: {message.from_user.first_name}

Сообщение:
{text}
"""
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("📝 Ответить", callback_data=f"reply_to:{user_id}"))
        
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, support_msg, reply_markup=keyboard)
            except:
                pass
        
        support_messages[user_id] = text
        
        msg = bot.send_message(user_id, "✅ Ваше сообщение отправлено в поддержку. Ожидайте ответа в течение 24 часов.", 
                              reply_markup=get_main_keyboard())
        save_message_id(user_id, msg.message_id)
        user_states[user_id] = None
        return
    
    elif user_states.get(user_id, {}).get("current") == "admin_reply":
        target_user = user_states[user_id].get("target_user")
        if target_user:
            try:
                bot.send_message(
                    target_user,
                    f"📩 Ответ от поддержки:\n\n{text}\n\n— Администратор"
                )
                msg = bot.send_message(user_id, f"✅ Ответ отправлен пользователю {target_user}")
            except Exception as e:
                msg = bot.send_message(user_id, f"❌ Ошибка отправки: {e}")
            
            save_message_id(user_id, msg.message_id)
            del user_states[user_id]
            return
    
    if user_id not in user_states:
        return
    
    current_state = user_states[user_id]["current"]
    
    if text == "❌ Отмена":
        reset_user_state(user_id)
        msg = bot.send_message(user_id, "Создание объявления отменено", 
                              reply_markup=get_main_keyboard())
        save_message_id(user_id, msg.message_id)
        return
    
    if current_state == "search_model":
        user_states[user_id]["previous"].append(user_states[user_id]["current"])
        user_states[user_id]["current"] = "select_model"
        cleanup_user_messages(user_id)
        
        msg = bot.send_message(user_id, f"🔍 Результаты поиска по '{text}':", 
                              reply_markup=get_models_keyboard(0, text))
        save_message_id(user_id, msg.message_id)
        return
    
    if current_state == "input_model":
        ad_drafts[user_id]['model'] = text
        if user_states[user_id]["previous"]:
            user_states[user_id]["current"] = user_states[user_id]["previous"].pop()
        else:
            user_states[user_id]["current"] = "select_condition"
        
        cleanup_user_messages(user_id)
        
        msg = bot.send_message(user_id, "📊 Выберите состояние телефона:", 
                              reply_markup=get_condition_keyboard())
        save_message_id(user_id, msg.message_id)
        return
    
    if current_state == "input_memory":
        ad_drafts[user_id]['memory'] = text
        if user_states[user_id]["previous"]:
            user_states[user_id]["current"] = user_states[user_id]["previous"].pop()
        else:
            user_states[user_id]["current"] = "input_color"
        
        cleanup_user_messages(user_id)
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
        msg = bot.send_message(user_id, "🎨 Введите цвет телефона:", 
                              reply_markup=keyboard)
        save_message_id(user_id, msg.message_id)
        return
    
    if current_state == "input_color":
        ad_drafts[user_id]['color'] = text
        user_states[user_id]["previous"].append(user_states[user_id]["current"])
        user_states[user_id]["current"] = "select_box"
        
        cleanup_user_messages(user_id)
        
        msg = bot.send_message(user_id, "📦 Есть ли оригинальная коробка?", 
                              reply_markup=get_yes_no_keyboard("box"))
        save_message_id(user_id, msg.message_id)
        return
    
    if current_state == "input_accessories":
        ad_drafts[user_id]['accessories'] = text
        user_states[user_id]["previous"].append(user_states[user_id]["current"])
        user_states[user_id]["current"] = "input_price"
        
        cleanup_user_messages(user_id)
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
        msg = bot.send_message(user_id, "💰 Введите цену в сомах (только цифры):", 
                              reply_markup=keyboard)
        save_message_id(user_id, msg.message_id)
        return
    
    if current_state == "input_price":
        is_valid, price = validate_price(text)
        if not is_valid:
            msg = bot.send_message(user_id, "❌ Неверный формат! Введите только цифры (от 100 до 1 000 000 сом):", 
                                  reply_markup=get_cancel_keyboard())
            save_message_id(user_id, msg.message_id)
            return
        
        ad_drafts[user_id]['price'] = price
        user_states[user_id]["previous"].append(user_states[user_id]["current"])
        user_states[user_id]["current"] = "input_city"
        
        cleanup_user_messages(user_id)
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
        msg = bot.send_message(user_id, "📍 Введите город:", 
                              reply_markup=keyboard)
        save_message_id(user_id, msg.message_id)
        return
    
    if current_state == "input_city":
        ad_drafts[user_id]['city'] = text
        user_states[user_id]["previous"].append(user_states[user_id]["current"])
        user_states[user_id]["current"] = "input_metro"
        
        cleanup_user_messages(user_id)
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
        msg = bot.send_message(user_id, "🚇 Введите станцию метро (или 'нет'):", 
                              reply_markup=keyboard)
        save_message_id(user_id, msg.message_id)
        return
    
    if current_state == "input_metro":
        metro = None if text.lower() == 'нет' else text
        ad_drafts[user_id]['metro'] = metro
        user_states[user_id]["previous"].append(user_states[user_id]["current"])
        user_states[user_id]["current"] = "upload_photos"
        
        cleanup_user_messages(user_id)
        
        msg = bot.send_message(
            user_id,
            f"📸 Теперь загрузите {MIN_PHOTOS}-{MAX_PHOTOS} фотографий:\n"
            f"• Сначала фото спереди и сзади\n"
            f"• Затем фото с дефектами (если есть)\n"
            f"• Максимум {MAX_PHOTOS} фото\n\n"
            f"Отправляйте фото по одному.",
            reply_markup=get_cancel_keyboard()
        )
        save_message_id(user_id, msg.message_id)
        return

# ===== ОБРАБОТЧИК ОТВЕТА АДМИНИСТРАТОРА =====
@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_to:'))
def reply_to_user(call):
    admin_id = call.from_user.id
    if admin_id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "Доступ запрещен")
        return
    
    target_user_id = call.data.split(':')[1]
    
    user_states[admin_id] = {
        "current": "admin_reply",
        "target_user": target_user_id
    }
    
    bot.answer_callback_query(call.id)
    
    msg = bot.send_message(
        admin_id,
        f"✍️ Введите ответ для пользователя {target_user_id}:",
        reply_markup=get_cancel_keyboard()
    )
    save_message_id(admin_id, msg.message_id)

# ===== РАССЫЛКА ДЛЯ АДМИНОВ =====
@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        bot.send_message(user_id, "Доступ запрещен")
        return
    
    cleanup_user_messages(user_id)
    
    broadcast_text = """
📢 Панель рассылки сообщений

Выберите тип рассылки:
• /broadcast_all - всем пользователям
• /broadcast_user - конкретному пользователю
• /broadcast_list - списку пользователей
• /broadcast_preview - предпросмотр сообщения

Для отправки фото с текстом:
1. Сначала отправьте фото с подписью
2. Затем используйте команду рассылки
"""
    msg = bot.send_message(user_id, broadcast_text)
    save_message_id(user_id, msg.message_id)

@bot.message_handler(commands=['broadcast_all'])
def cmd_broadcast_all(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    cleanup_user_messages(user_id)
    
    broadcast_data[user_id] = {
        "type": "all",
        "step": "waiting_message"
    }
    
    instruction = """
📢 Рассылка всем пользователям

Отправьте сообщение для рассылки:
• Текст
• Фото с подписью
• Видео с подписью
• Документ с подписью

После отправки сообщения начнется рассылка.
"""
    msg = bot.send_message(user_id, instruction, reply_markup=get_cancel_keyboard())
    save_message_id(user_id, msg.message_id)

@bot.message_handler(commands=['broadcast_user'])
def cmd_broadcast_user(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    cleanup_user_messages(user_id)
    
    broadcast_data[user_id] = {
        "type": "user",
        "step": "waiting_user_id"
    }
    
    instruction = """
👤 Рассылка конкретному пользователю

Шаг 1: Введите ID пользователя
(можно узнать через /admin_users)

Пример: 123456789
"""
    msg = bot.send_message(user_id, instruction, reply_markup=get_cancel_keyboard())
    save_message_id(user_id, msg.message_id)

@bot.message_handler(commands=['broadcast_list'])
def cmd_broadcast_list(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    cleanup_user_messages(user_id)
    
    broadcast_data[user_id] = {
        "type": "list",
        "step": "waiting_user_list"
    }
    
    instruction = """
👥 Рассылка списку пользователей

Шаг 1: Введите список ID пользователей через запятую

Пример:
123456789, 987654321, 555555555

Максимум: 100 пользователей за раз
"""
    msg = bot.send_message(user_id, instruction, reply_markup=get_cancel_keyboard())
    save_message_id(user_id, msg.message_id)

@bot.message_handler(commands=['broadcast_preview'])
def cmd_broadcast_preview(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    cleanup_user_messages(user_id)
    
    instruction = """
👁 Предпросмотр рассылки

Отправьте сообщение для предпросмотра:
Вы увидите, как оно будет выглядеть у пользователей.
"""
    msg = bot.send_message(user_id, instruction, reply_markup=get_cancel_keyboard())
    save_message_id(user_id, msg.message_id)
    
    broadcast_data[user_id] = {
        "type": "preview",
        "step": "waiting_message"
    }

@bot.message_handler(content_types=['text', 'photo', 'video', 'document'], 
                    func=lambda m: m.from_user.id in ADMIN_IDS and broadcast_data.get(m.from_user.id))
def handle_broadcast_message(message):
    user_id = message.from_user.id
    data = broadcast_data.get(user_id)
    
    if not data:
        return
    
    try:
        bot.delete_message(user_id, message.message_id)
    except:
        pass
    
    if data["step"] == "waiting_user_id":
        try:
            target_user_id = int(message.text.strip())
            data["target_user_id"] = target_user_id
            data["step"] = "waiting_message"
            
            msg = bot.send_message(user_id, f"✅ ID пользователя сохранен: {target_user_id}\n\nТеперь отправьте сообщение для рассылки:")
            save_message_id(user_id, msg.message_id)
        except:
            msg = bot.send_message(user_id, "❌ Неверный формат ID. Введите числовой ID пользователя.")
            save_message_id(user_id, msg.message_id)
    
    elif data["step"] == "waiting_user_list":
        try:
            user_ids_text = message.text.strip()
            user_ids = [uid.strip() for uid in user_ids_text.split(',') if uid.strip()]
            
            if len(user_ids) > 100:
                msg = bot.send_message(user_id, "❌ Слишком много пользователей. Максимум 100.")
                save_message_id(user_id, msg.message_id)
                return
            
            data["user_ids"] = user_ids
            data["step"] = "waiting_message"
            
            msg = bot.send_message(user_id, f"✅ Список пользователей сохранен: {len(user_ids)} пользователей\n\nТеперь отправьте сообщение для рассылки:")
            save_message_id(user_id, msg.message_id)
        except Exception as e:
            msg = bot.send_message(user_id, f"❌ Ошибка обработки списка: {e}")
            save_message_id(user_id, msg.message_id)
    
    elif data["step"] == "waiting_message":
        message_type = 'text'
        photo_id = None
        message_text = ""
        
        if message.content_type == 'text':
            message_text = message.text
            data["message_text"] = message_text
            data["message_type"] = 'text'
        
        elif message.content_type == 'photo':
            photo_id = message.photo[-1].file_id
            message_text = message.caption if message.caption else ""
            data["photo_id"] = photo_id
            data["message_text"] = message_text
            data["message_type"] = 'photo'
        
        elif message.content_type == 'video':
            video_id = message.video.file_id
            message_text = message.caption if message.caption else ""
            data["video_id"] = video_id
            data["message_text"] = message_text
            data["message_type"] = 'video'
        
        elif message.content_type == 'document':
            document_id = message.document.file_id
            message_text = message.caption if message.caption else ""
            data["document_id"] = document_id
            data["message_text"] = message_text
            data["message_type"] = 'document'
        
        preview_text = f"""
✅ Сообщение сохранено для рассылки

Тип: {message.content_type}
Текст: {message_text[:100]}{'...' if len(message_text) > 100 else ''}

Статистика:
"""
        
        if data["type"] == "all":
            total_users = len(users_data)
            preview_text += f"• Получателей: {total_users} пользователей\n\n"
            
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("✅ Начать рассылку", callback_data="broadcast_start:all"),
                types.InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel")
            )
            
            msg = bot.send_message(user_id, preview_text, reply_markup=keyboard)
            save_message_id(user_id, msg.message_id)
        
        elif data["type"] == "user":
            preview_text += f"• Получатель: ID {data['target_user_id']}\n\n"
            
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("✅ Отправить пользователю", callback_data="broadcast_start:user"),
                types.InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel")
            )
            
            msg = bot.send_message(user_id, preview_text, reply_markup=keyboard)
            save_message_id(user_id, msg.message_id)
        
        elif data["type"] == "list":
            preview_text += f"• Получателей: {len(data['user_ids'])} пользователей\n\n"
            
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("✅ Начать рассылку", callback_data="broadcast_start:list"),
                types.InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel")
            )
            
            msg = bot.send_message(user_id, preview_text, reply_markup=keyboard)
            save_message_id(user_id, msg.message_id)
        
        elif data["type"] == "preview":
            preview_text = "👁 ПРЕДПРОСМОТР СООБЩЕНИЯ:\n\n"
            
            if message.content_type == 'text':
                preview_text += message.text
                bot.send_message(user_id, preview_text)
            
            elif message.content_type == 'photo':
                preview_text += f"Фото с подписью:\n{message.caption if message.caption else 'Без подписи'}"
                bot.send_photo(user_id, message.photo[-1].file_id, caption=preview_text)
            
            elif message.content_type == 'video':
                preview_text += f"Видео с подписью:\n{message.caption if message.caption else 'Без подписи'}"
                bot.send_video(user_id, message.video.file_id, caption=preview_text)
            
            elif message.content_type == 'document':
                preview_text += f"Документ с подписью:\n{message.caption if message.caption else 'Без подписи'}"
                bot.send_document(user_id, message.document.file_id, caption=preview_text)
            
            if user_id in broadcast_data:
                del broadcast_data[user_id]

@bot.callback_query_handler(func=lambda call: call.data.startswith('broadcast_start:'))
def broadcast_start(call):
    user_id = call.from_user.id
    broadcast_type = call.data.split(':')[1]
    
    if user_id not in ADMIN_IDS or user_id not in broadcast_data:
        bot.answer_callback_query(call.id, "Ошибка данных")
        return
    
    data = broadcast_data[user_id]
    
    message_text = data.get("message_text", "")
    message_type = data.get("message_type", "text")
    photo_id = data.get("photo_id")
    
    if broadcast_type == "all":
        successful, failed, result_message = broadcast_to_all_users(
            message_text, message_type, photo_id, user_id
        )
        
        del broadcast_data[user_id]
        
        bot.answer_callback_query(call.id, f"Рассылка завершена: {successful} успешно, {failed} ошибок")
    
    elif broadcast_type == "user":
        target_user_id = data.get("target_user_id")
        
        if not target_user_id:
            bot.answer_callback_query(call.id, "Ошибка: нет ID пользователя")
            return
        
        success, result_message = broadcast_to_user(
            target_user_id, message_text, message_type, photo_id
        )
        
        del broadcast_data[user_id]
        
        if success:
            bot.answer_callback_query(call.id, "Сообщение отправлено")
            bot.send_message(user_id, f"✅ Сообщение отправлено пользователю {target_user_id}")
        else:
            bot.answer_callback_query(call.id, "Ошибка отправки")
            bot.send_message(user_id, f"❌ Ошибка: {result_message}")
    
    elif broadcast_type == "list":
        user_ids = data.get("user_ids", [])
        
        if not user_ids:
            bot.answer_callback_query(call.id, "Ошибка: нет списка пользователей")
            return
        
        successful, failed, failed_list, result_message = broadcast_to_list(
            user_ids, message_text, message_type, photo_id, user_id
        )
        
        del broadcast_data[user_id]
        
        bot.answer_callback_query(call.id, f"Рассылка завершена: {successful} успешно, {failed} ошибок")

@bot.callback_query_handler(func=lambda call: call.data == "broadcast_cancel")
def broadcast_cancel(call):
    user_id = call.from_user.id
    
    if user_id in broadcast_data:
        del broadcast_data[user_id]
    
    bot.answer_callback_query(call.id, "Рассылка отменена")
    
    msg = bot.send_message(user_id, "❌ Рассылка отменена", reply_markup=get_main_keyboard())
    save_message_id(user_id, msg.message_id)

# ===== АДМИН КОМАНДЫ =====
@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        bot.send_message(user_id, "Доступ запрещен")
        return
    
    cleanup_user_messages(user_id)
    
    admin_text = f"""
⚙️ Админ панель

Статистика:
• Пользователей: {len(users_data)}
• Объявлений: {len(active_ads)}
• PREMIUM пользователей: {len(premium_users)}
• Инвойсов: {len(invoices)}

📢 Команды рассылки:
• /broadcast - панель рассылки
• /broadcast_all - всем пользователям
• /broadcast_user - конкретному пользователю
• /broadcast_list - списку пользователей
• /broadcast_preview - предпросмотр

📊 Команды статистики:
• /admin_stats - подробная статистика
• /admin_users - список пользователей
• /admin_clear - очистить данные
"""
    msg = bot.send_message(user_id, admin_text)
    save_message_id(user_id, msg.message_id)

@bot.message_handler(commands=['admin_stats'])
def cmd_admin_stats(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    total_price = sum(ad.get('price', 0) for ad in active_ads.values())
    paid_invoices = sum(1 for i in invoices.values() if i.get("status") == "paid")
    total_amount = sum(float(i.get("amount", 0)) for i in invoices.values() if i.get("status") == "paid")
    
    today = datetime.now().date()
    week_ago = today - timedelta(days=7)
    
    users_last_week = 0
    for uid, data in users_data.items():
        user_date = datetime.fromisoformat(data.get("created_at", datetime.now().isoformat())).date()
        if user_date >= week_ago:
            users_last_week += 1
    
    stats_text = f"""
📊 Подробная статистика:

👥 Пользователи:
• Всего: {len(users_data)}
• За последнюю неделю: {users_last_week}
• PREMIUM: {len(premium_users)}

📢 Объявления:
• Активных: {len(active_ads)}
• Общая сумма: {total_price:,} сом

💰 Платежи CryptoBot:
• Всего инвойсов: {len(invoices)}
• Оплачено: {paid_invoices}
• Общая сумма: {total_amount} USDT

⚙️ Система:
• Сессий: {len(user_states)}
• Черновиков: {len(ad_drafts)}
• Контактов: {len(user_contacts)}
"""
    bot.send_message(user_id, stats_text)

@bot.message_handler(commands=['admin_users'])
def cmd_admin_users(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    users_text = "👥 Список пользователей:\n\n"
    
    users_list = sorted(users_data.items(), 
                       key=lambda x: datetime.fromisoformat(x[1].get("created_at", datetime.now().isoformat())), 
                       reverse=True)[:20]
    
    for uid, data in users_list:
        username = data.get("username", "Нет username")
        first_name = data.get("first_name", "")
        last_name = data.get("last_name", "")
        is_premium = "💎" if data.get("is_premium") else "🔹"
        created = datetime.fromisoformat(data.get("created_at", datetime.now().isoformat())).strftime('%d.%m.%Y')
        
        full_name = f"{first_name} {last_name}".strip()
        if full_name:
            users_text += f"{is_premium} {uid} - {full_name} (@{username}) - {created}\n"
        else:
            users_text += f"{is_premium} {uid} - @{username} - {created}\n"
    
    if len(users_data) > 20:
        users_text += f"\n... и еще {len(users_data) - 20} пользователей"
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("📥 Экспорт в CSV", callback_data="export_users"))
    
    bot.send_message(user_id, users_text, reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data == "export_users")
def export_users(call):
    user_id = call.from_user.id
    
    if user_id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "Доступ запрещен")
        return
    
    csv_data = "ID;Username;Имя;Фамилия;PREMIUM;Дата регистрации\n"
    
    for uid, data in users_data.items():
        username = data.get("username", "")
        first_name = data.get("first_name", "")
        last_name = data.get("last_name", "")
        is_premium = "Да" if data.get("is_premium") else "Нет"
        created = datetime.fromisoformat(data.get("created_at", datetime.now().isoformat())).strftime('%d.%m.%Y %H:%M')
        
        csv_data += f"{uid};{username};{first_name};{last_name};{is_premium};{created}\n"
    
    filename = f"users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    try:
        with open(filename, 'w', encoding='utf-8-sig') as f:
            f.write(csv_data)
        
        with open(filename, 'rb') as f:
            bot.send_document(user_id, f, caption="📊 Экспорт пользователей")
        
        os.remove(filename)
    except Exception as e:
        logger.error(f"Ошибка экспорта: {e}")
        bot.send_message(user_id, f"❌ Ошибка экспорта: {e}")
    
    bot.answer_callback_query(call.id, "Экспорт завершен")

@bot.message_handler(commands=['admin_clear'])
def cmd_admin_clear(message):
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✅ Да, очистить всё", callback_data="clear_all_confirm"),
        types.InlineKeyboardButton("❌ Нет, отмена", callback_data="clear_cancel")
    )
    
    bot.send_message(user_id, 
                    "⚠️ ВНИМАНИЕ! Вы собираетесь очистить ВСЕ данные бота:\n\n"
                    "• Всех пользователей\n"
                    "• Все объявления\n"
                    "• Все платежи\n"
                    "• Все сессии\n\n"
                    "Это действие НЕЛЬЗЯ отменить!\n\n"
                    "Вы уверены?", 
                    reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data == "clear_all_confirm")
def clear_all_confirm(call):
    user_id = call.from_user.id
    
    if user_id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "Доступ запрещен")
        return
    
    global users_data, active_ads, user_states, ad_drafts, message_history
    global invoices, premium_users, support_messages, user_contacts, broadcast_data
    
    users_data = {}
    active_ads = {}
    user_states = {}
    ad_drafts = {}
    message_history = {}
    invoices = {}
    premium_users = set()
    support_messages = {}
    user_contacts = {}
    broadcast_data = {}
    
    bot.answer_callback_query(call.id, "✅ Все данные очищены")
    
    bot.send_message(user_id, "✅ Все данные успешно очищены!")

@bot.callback_query_handler(func=lambda call: call.data == "clear_cancel")
def clear_cancel(call):
    user_id = call.from_user.id
    bot.answer_callback_query(call.id, "Очистка отменена")
    bot.send_message(user_id, "❌ Очистка данных отменена")

# ===== ДОПОЛНИТЕЛЬНЫЕ ОБРАБОТЧИКИ =====
@bot.callback_query_handler(func=lambda call: call.data == "faq")
def process_faq(call):
    user_id = call.from_user.id
    
    faq_text = """
📖 FAQ / Правила

❓ Как создать объявление?
1. Нажмите "Создать объявление"
2. Выберите модель телефона
3. Заполните все характеристики
4. Загрузите 2-4 фотографии
5. Подтвердите публикацию

❓ Сколько стоит размещение?
• Обычное объявление: бесплатно
• Премиум объявление: 299 сом/месяц

❓ Как связаться с продавцом?
• Нажмите кнопку "Связаться" под объявлением
• Отправьте свой номер телефона или контакт

⚠️ Правила:
1. Запрещен обман и мошенничество
2. Фото должны быть реальными
3. Цена должна соответствовать рыночной
4. Уважайте других пользователей

❗️ Нарушители правил блокируются!
"""
    
    bot.send_message(user_id, faq_text)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "buy_premium")
def process_buy_premium(call):
    user_id = call.from_user.id
    
    invoice = create_invoice(3, "USDT", "PREMIUM статус на 30 дней", str(user_id))
    
    if invoice:
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("💳 Оплатить", url=invoice["pay_url"]))
        keyboard.add(types.InlineKeyboardButton("🔄 Проверить оплату", callback_data="check_payment"))
        
        bot.send_message(
            user_id,
            f"💎 Оплатите {invoice['amount']} {invoice['asset']} для активации PREMIUM статуса на 30 дней\n\n"
            f"Ссылка для оплаты действительна 30 минут.",
            reply_markup=keyboard
        )
    else:
        bot.send_message(user_id, "❌ Ошибка создания счета. Попробуйте позже.")
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "check_payment")
def process_check_payment(call):
    user_id = call.from_user.id
    
    if user_id in premium_users:
        bot.answer_callback_query(call.id, "✅ У вас уже активирован PREMIUM статус!", show_alert=True)
        return
    
    bot.answer_callback_query(call.id, "Проверка платежей выполняется автоматически каждые 30 секунд", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('contact:'))
def process_contact(call):
    parts = call.data.split(':')
    ad_id = parts[1]
    seller_id = parts[2]
    
    if call.from_user.id == int(seller_id):
        bot.answer_callback_query(call.id, "Это ваше собственное объявление", show_alert=True)
        return
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("📱 Отправить контакт", callback_data=f"send_contact:{ad_id}"))
    
    bot.send_message(
        call.from_user.id,
        f"📞 Чтобы связаться с продавцом:\n\n"
        f"1. Нажмите кнопку ниже, чтобы поделиться контактом\n"
        f"2. Или напишите свой номер телефона вручную\n\n"
        f"Продавец получит ваши контактные данные.",
        reply_markup=keyboard
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('send_contact:'))
def process_send_contact(call):
    ad_id = call.data.split(':')[1]
    ad = active_ads.get(ad_id)
    
    if not ad:
        bot.answer_callback_query(call.id, "Объявление не найдено", show_alert=True)
        return
    
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add(types.KeyboardButton("📱 Поделиться контактом", request_contact=True))
    keyboard.add(types.KeyboardButton("❌ Отмена"))
    
    bot.send_message(
        call.from_user.id,
        "Нажмите кнопку ниже, чтобы поделиться контактом:",
        reply_markup=keyboard
    )
    
    user_states[call.from_user.id] = {
        "current": "sending_contact",
        "ad_id": ad_id,
        "seller_id": ad['user_id']
    }
    
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    user_id = message.from_user.id
    
    if user_states.get(user_id, {}).get("current") == "sending_contact":
        ad_id = user_states[user_id]["ad_id"]
        seller_id = user_states[user_id]["seller_id"]
        ad = active_ads.get(ad_id)
        
        if ad:
            contact_info = f"""
📞 Новый запрос на контакт:

Объявление: {ad.get('model', 'Не указано')}
Цена: {ad.get('price', 0)} сом
ID объявления: {ad_id}

Покупатель:
Имя: {message.contact.first_name}
Фамилия: {message.contact.last_name if message.contact.last_name else 'Не указана'}
Телефон: {message.contact.phone_number}
Username: @{message.from_user.username if message.from_user.username else 'Не указан'}
ID: {user_id}
"""
            
            try:
                bot.send_message(seller_id, contact_info)
                bot.send_message(user_id, "✅ Ваш контакт отправлен продавцу. Ожидайте звонка!")
                logger.info(f"Контакт отправлен от {user_id} продавцу {seller_id} для объявления {ad_id}")
            except Exception as e:
                bot.send_message(user_id, "❌ Ошибка отправки контакта. Попробуйте позже.")
                logger.error(f"Ошибка отправки контакта: {e}")
        
        reset_user_state(user_id)

# ===== ЗАПУСК БОТА =====
if __name__ == '__main__':
    print("=" * 50)
    print("🤖 БОТ ДЛЯ ОБЪЯВЛЕНИЙ О ТЕЛЕФОНАХ")
    print("=" * 50)
    print(f"Telegram Bot Token: {'✅ Установлен' if TOKEN != 'ВАШ_ТОКЕН_БОТА' else '❌ НЕ УСТАНОВЛЕН'}")
    print(f"CryptoBot API Key: {'✅ Установлен' if CRYPTO_BOT_API_KEY != 'ВАШ_КЛЮЧ_CRYPTOBOT' else '❌ НЕ УСТАНОВЛЕН'}")
    print(f"Администраторы: {ADMIN_IDS}")
    print(f"Моделей телефонов: {len(phone_models)}")
    print(f"Канал для публикаций: {CHANNEL_ID}")
    print(f"Чат поддержки: {SUPPORT_CHAT_ID}")
    print("=" * 50)
    print("📢 Доступны команды рассылки для администраторов:")
    print("• /broadcast - панель рассылки")
    print("• /broadcast_all - рассылка всем")
    print("• /broadcast_user - рассылка по ID")
    print("• /broadcast_list - рассылка списку")
    print("=" * 50)
    print("🔄 Запуск бота...")
    print("Логи записываются в bot.log")
    print("=" * 50)
    
    try:
        bot.polling(none_stop=True, interval=1, timeout=60)
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
        print(f"Критическая ошибка: {e}")
        time.sleep(5)