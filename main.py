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
import traceback
from collections import OrderedDict

# ===== НАСТРОЙКИ ЛОГИРОВАНИЯ =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===== КОНСТАНТЫ =====
MAX_PHOTOS = 4
MIN_PHOTOS = 2
PREMIUM_PRICE = 299  # сом
PREMIUM_DURATION_DAYS = 30
PAYMENT_CHECK_INTERVAL = 30  # секунд

# ===== СТРУКТУРЫ ДАННЫХ =====
class DataStorage:
    """Управление всеми данными бота"""
    def __init__(self):
        self.users = OrderedDict()  # user_id -> user_data
        self.ads = OrderedDict()    # ad_id -> ad_data
        self.states = OrderedDict() # user_id -> state_data
        self.drafts = OrderedDict() # user_id -> draft_data
        self.invoices = OrderedDict() # invoice_id -> invoice_data
        self.premium_users = set()  # user_id
        self.support_messages = OrderedDict() # user_id -> message
        self.contacts = OrderedDict() # user_id -> contact_info
        self.message_cache = OrderedDict() # (user_id, message_id) -> message_data
        
    def cleanup_old_data(self, max_age_hours=24):
        """Очистка старых данных"""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        keys_to_remove = []
        
        for user_id, state in list(self.states.items()):
            if state.get('last_activity', datetime.min) < cutoff:
                keys_to_remove.append(('states', user_id))
        
        for user_id, draft in list(self.drafts.items()):
            if draft.get('created_at', datetime.min) < cutoff:
                keys_to_remove.append(('drafts', user_id))
                
        # Ограничиваем размер кэша сообщений
        if len(self.message_cache) > 1000:
            excess = len(self.message_cache) - 800
            for _ in range(excess):
                if self.message_cache:
                    self.message_cache.popitem(last=False)

storage = DataStorage()

# ===== КЛАВИАТУРЫ =====
def get_main_keyboard():
    """Основная клавиатура, которая ВСЕГДА отображается"""
    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2,
        one_time_keyboard=False  # Важно: не скрывать после нажатия!
    )
    keyboard.add(
        types.KeyboardButton("📱 Создать объявление"),
        types.KeyboardButton("📋 Мои объявления")
    )
    keyboard.add(
        types.KeyboardButton("❓ Помощь"),
        types.KeyboardButton("💎 Донат")
    )
    keyboard.add(types.KeyboardButton("📞 Поддержка"))
    return keyboard

def get_cancel_keyboard():
    """Клавиатура с кнопкой отмены"""
    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=False
    )
    keyboard.add(types.KeyboardButton("❌ Отмена"))
    return keyboard

def get_condition_keyboard():
    """Inline-клавиатура для выбора состояния"""
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        ("Новый", "condition:new"),
        ("Как новый", "condition:like_new"),
        ("Среднее", "condition:good"),
        ("Слегка повреждён", "condition:damaged")
    ]
    for text, data in buttons:
        keyboard.add(types.InlineKeyboardButton(text, callback_data=data))
    keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
    return keyboard

def get_yes_no_keyboard(prefix):
    """Inline-клавиатура Да/Нет"""
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✅ Да", callback_data=f"{prefix}:yes"),
        types.InlineKeyboardButton("❌ Нет", callback_data=f"{prefix}:no")
    )
    keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
    return keyboard

# ===== МОДЕЛИ ТЕЛЕФОНОВ =====
PHONE_MODELS = [
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

def get_models_keyboard(page=0, search_query=""):
    """Клавиатура выбора модели с пагинацией"""
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    # Фильтрация моделей
    if search_query:
        filtered = [
            m for m in PHONE_MODELS 
            if search_query.lower() in f"{m['brand']} {m['model']}".lower()
        ]
    else:
        filtered = PHONE_MODELS
    
    # Пагинация
    per_page = 8
    start_idx = page * per_page
    end_idx = start_idx + per_page
    page_models = filtered[start_idx:end_idx]
    
    # Кнопки моделей
    for model in page_models:
        text = f"{model['brand']} {model['model']}"
        keyboard.add(types.InlineKeyboardButton(text, callback_data=f"model:{model['id']}"))
    
    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ Назад", 
                     callback_data=f"models_page:{page-1}:{search_query}"))
    if end_idx < len(filtered):
        nav_buttons.append(types.InlineKeyboardButton("Вперёд ➡️", 
                     callback_data=f"models_page:{page+1}:{search_query}"))
    
    if nav_buttons:
        keyboard.row(*nav_buttons)
    
    # Дополнительные кнопки
    if not search_query:
        keyboard.add(types.InlineKeyboardButton("🔍 Поиск модели", 
                     callback_data="search_model"))
    
    keyboard.add(
        types.InlineKeyboardButton("📝 Другая модель", callback_data="model:custom"),
        types.InlineKeyboardButton("⬅️ Назад", callback_data="back")
    )
    
    return keyboard

# ===== ИНИЦИАЛИЗАЦИЯ БОТА =====
try:
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8397567369:AAFki44pWtxP5M9iPGEn26yvUsu1Fv-9g3o")
    CRYPTO_BOT_API_KEY = os.getenv("CRYPTO_BOT_API_KEY", "498509:AABNPgPwTiCU9DdByIgswTvIuSz5VO9neRy")
    ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "7577716374").split(",")]
    CHANNEL_ID = os.getenv("CHANNEL_ID", "@FonZoneKg")
    SUPPORT_CHAT_ID = os.getenv("SUPPORT_CHAT_ID", "@FONZONE_CL")
    
    bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
    
    # Конфигурация CryptoBot
    CRYPTO_BOT_API_URL = "https://pay.crypt.bot/api/"
    CRYPTO_BOT_HEADERS = {
        "Crypto-Pay-API-Token": CRYPTO_BOT_API_KEY,
        "Content-Type": "application/json"
    }
    
except Exception as e:
    logger.error(f"Ошибка инициализации бота: {e}")
    raise

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def safe_send_message(user_id, text, **kwargs):
    """Безопасная отправка сообщения с обработкой ошибок"""
    try:
        # Гарантируем наличие основной клавиатуры, если не указано иное
        if 'reply_markup' not in kwargs:
            kwargs['reply_markup'] = get_main_keyboard()
        
        # Ограничиваем длину текста для Telegram
        if len(text) > 4096:
            parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
            messages = []
            for part in parts:
                msg = bot.send_message(user_id, part, **kwargs)
                messages.append(msg)
            return messages
        else:
            return bot.send_message(user_id, text, **kwargs)
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
        return None

def safe_edit_message(chat_id, message_id, text, **kwargs):
    """Безопасное редактирование сообщения"""
    try:
        return bot.edit_message_text(text, chat_id, message_id, **kwargs)
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" in str(e):
            return None  # Сообщение не изменилось - это не ошибка
        elif "message to edit not found" in str(e):
            logger.warning(f"Сообщение {message_id} не найдено для редактирования")
            return None
        else:
            logger.error(f"Ошибка редактирования сообщения: {e}")
            return None

def safe_delete_message(chat_id, message_id):
    """Безопасное удаление сообщения"""
    try:
        bot.delete_message(chat_id, message_id)
        return True
    except:
        return False

def validate_price(price_str):
    """Валидация цены"""
    try:
        # Убираем пробелы и запятые
        clean_price = price_str.replace(" ", "").replace(",", "").replace(".", "")
        price = int(clean_price)
        
        if 100 <= price <= 1000000:
            return True, price
        else:
            return False, None
    except:
        return False, None

def generate_ad_id(user_id):
    """Генерация уникального ID объявления"""
    timestamp = int(datetime.now().timestamp())
    random_part = hashlib.md5(f"{user_id}_{timestamp}".encode()).hexdigest()[:8]
    return f"{user_id}_{timestamp}_{random_part}"

def reset_user_state(user_id):
    """Сброс состояния пользователя с сохранением черновика"""
    if user_id in storage.states:
        # Если есть черновик, сохраняем его
        if user_id in storage.drafts:
            draft = storage.drafts[user_id]
            # Можно сохранить черновик в отдельное хранилище или оставить как есть
            pass
        
        # Очищаем состояние, но оставляем черновик для возможности продолжения
        if user_id in storage.states:
            del storage.states[user_id]
        
        # Отправляем основное меню
        safe_send_message(user_id, "Сессия сброшена. Возвращаю в главное меню.")
        return True
    return False

def ensure_main_keyboard(user_id):
    """Гарантированное отображение основной клавиатуры"""
    try:
        # Отправляем пустое сообщение с клавиатурой
        bot.send_chat_action(user_id, 'typing')
        msg = safe_send_message(user_id, " ", reply_markup=get_main_keyboard())
        
        # Сохраняем в кэш
        if msg:
            if isinstance(msg, list):
                for m in msg:
                    storage.message_cache[(user_id, m.message_id)] = {
                        'type': 'keyboard_refresh',
                        'timestamp': datetime.now()
                    }
            else:
                storage.message_cache[(user_id, msg.message_id)] = {
                    'type': 'keyboard_refresh',
                    'timestamp': datetime.now()
                }
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки основной клавиатуры: {e}")
        return False

# ===== СИСТЕМА СОСТОЯНИЙ =====
class UserState:
    """Управление состоянием пользователя"""
    
    @staticmethod
    def set_state(user_id, state_name, data=None):
        """Установка состояния пользователя"""
        storage.states[user_id] = {
            'state': state_name,
            'data': data or {},
            'timestamp': datetime.now(),
            'history': storage.states.get(user_id, {}).get('history', [])
        }
        logger.info(f"Установлено состояние {state_name} для пользователя {user_id}")
    
    @staticmethod
    def get_state(user_id):
        """Получение состояния пользователя"""
        return storage.states.get(user_id, {}).get('state')
    
    @staticmethod
    def get_data(user_id, key=None):
        """Получение данных состояния"""
        state = storage.states.get(user_id, {})
        if key:
            return state.get('data', {}).get(key)
        return state.get('data', {})
    
    @staticmethod
    def update_data(user_id, key, value):
        """Обновление данных состояния"""
        if user_id in storage.states:
            if 'data' not in storage.states[user_id]:
                storage.states[user_id]['data'] = {}
            storage.states[user_id]['data'][key] = value
            return True
        return False
    
    @staticmethod
    def push_history(user_id, state_name):
        """Добавление состояния в историю"""
        if user_id in storage.states:
            if 'history' not in storage.states[user_id]:
                storage.states[user_id]['history'] = []
            storage.states[user_id]['history'].append(state_name)
    
    @staticmethod
    def pop_history(user_id):
        """Восстановление предыдущего состояния"""
        if user_id in storage.states:
            history = storage.states[user_id].get('history', [])
            if history:
                prev_state = history.pop()
                storage.states[user_id]['state'] = prev_state
                storage.states[user_id]['history'] = history
                return prev_state
        return None

# ===== ОБРАБОТКА ЧЕРНОВИКОВ =====
class AdDraftManager:
    """Управление черновиками объявлений"""
    
    @staticmethod
    def create_draft(user_id):
        """Создание нового черновика"""
        storage.drafts[user_id] = {
            'user_id': user_id,
            'photos': [],
            'created_at': datetime.now(),
            'last_modified': datetime.now(),
            'step': 0,
            'completed_steps': set()
        }
        return storage.drafts[user_id]
    
    @staticmethod
    def get_draft(user_id):
        """Получение черновика"""
        return storage.drafts.get(user_id)
    
    @staticmethod
    def update_draft(user_id, field, value):
        """Обновление поля черновика"""
        if user_id in storage.drafts:
            storage.drafts[user_id][field] = value
            storage.drafts[user_id]['last_modified'] = datetime.now()
            return True
        return False
    
    @staticmethod
    def add_photo(user_id, photo_id):
        """Добавление фото в черновик"""
        if user_id in storage.drafts:
            if 'photos' not in storage.drafts[user_id]:
                storage.drafts[user_id]['photos'] = []
            
            photos = storage.drafts[user_id]['photos']
            if len(photos) < MAX_PHOTOS:
                photos.append(photo_id)
                storage.drafts[user_id]['last_modified'] = datetime.now()
                return True
        return False
    
    @staticmethod
    def remove_photo(user_id, index):
        """Удаление фото из черновика"""
        if user_id in storage.drafts:
            photos = storage.drafts[user_id].get('photos', [])
            if 0 <= index < len(photos):
                photos.pop(index)
                storage.drafts[user_id]['last_modified'] = datetime.now()
                return True
        return False
    
    @staticmethod
    def validate_draft(user_id):
        """Проверка готовности черновика к публикации"""
        draft = storage.drafts.get(user_id)
        if not draft:
            return False, "Черновик не найден"
        
        required_fields = ['model', 'condition', 'memory', 'color', 'price', 'city']
        missing_fields = []
        
        for field in required_fields:
            if field not in draft or not draft[field]:
                missing_fields.append(field)
        
        if missing_fields:
            return False, f"Заполните поля: {', '.join(missing_fields)}"
        
        photos = draft.get('photos', [])
        if len(photos) < MIN_PHOTOS:
            return False, f"Добавьте минимум {MIN_PHOTOS} фотографии"
        
        if len(photos) > MAX_PHOTOS:
            return False, f"Максимум {MAX_PHOTOS} фотографий"
        
        return True, "Черновик готов к публикации"

# ===== CRYPTOBOT API =====
class CryptoBotAPI:
    """Интерфейс для работы с CryptoBot API"""
    
    @staticmethod
    def create_invoice(amount, currency="USDT", description="", payload=""):
        """Создание инвойса"""
        try:
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
            
            response = requests.post(url, headers=CRYPTO_BOT_HEADERS, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if result.get("ok"):
                invoice = result["result"]
                storage.invoices[invoice["invoice_id"]] = {
                    "user_id": payload,
                    "amount": amount,
                    "currency": currency,
                    "status": "active",
                    "created_at": datetime.now(),
                    "pay_url": invoice["pay_url"],
                    "invoice_data": invoice
                }
                logger.info(f"Создан инвойс {invoice['invoice_id']} для пользователя {payload}")
                return invoice
            else:
                logger.error(f"CryptoBot API ошибка: {result}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка сети CryptoBot: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка создания инвойса: {e}")
            return None
    
    @staticmethod
    def get_invoice_status(invoice_id):
        """Получение статуса инвойса"""
        try:
            url = CRYPTO_BOT_API_URL + "getInvoices"
            data = {"invoice_ids": [invoice_id]}
            
            response = requests.post(url, headers=CRYPTO_BOT_HEADERS, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if result.get("ok") and result["result"]["items"]:
                return result["result"]["items"][0].get("status", "active")
                
        except Exception as e:
            logger.error(f"Ошибка проверки статуса инвойса: {e}")
        
        return None

# ===== ПРОВЕРКА ПЛАТЕЖЕЙ В ФОНОВОМ РЕЖИМЕ =====
def payment_checker_loop():
    """Фоновая проверка статуса платежей"""
    logger.info("Запущен фоновый процесс проверки платежей")
    
    while True:
        try:
            current_time = datetime.now()
            
            # Проверяем каждый инвойс
            for invoice_id, invoice_data in list(storage.invoices.items()):
                try:
                    # Пропускаем старые инвойсы (старше 24 часов)
                    if (current_time - invoice_data.get("created_at", current_time)).total_seconds() > 86400:
                        continue
                    
                    # Проверяем только активные инвойсы
                    if invoice_data.get("status") == "active":
                        status = CryptoBotAPI.get_invoice_status(invoice_id)
                        
                        if status:
                            invoice_data["status"] = status
                            
                            # Обработка оплаченного инвойса
                            if status == "paid":
                                user_id = invoice_data.get("user_id")
                                if user_id:
                                    # Активируем премиум
                                    storage.premium_users.add(user_id)
                                    
                                    # Обновляем данные пользователя
                                    if user_id in storage.users:
                                        storage.users[user_id]["is_premium"] = True
                                        storage.users[user_id]["premium_until"] = (
                                            datetime.now() + timedelta(days=PREMIUM_DURATION_DAYS)
                                        ).isoformat()
                                    
                                    # Обновляем все объявления пользователя
                                    for ad in storage.ads.values():
                                        if ad.get('user_id') == user_id:
                                            ad['is_premium'] = True
                                    
                                    # Уведомляем пользователя
                                    try:
                                        bot.send_message(
                                            user_id,
                                            "🎉 <b>Поздравляем!</b>\n\n"
                                            "Ваш PREMIUM статус успешно активирован!\n"
                                            "Теперь все ваши объявления будут выделяться в канале.",
                                            reply_markup=get_main_keyboard()
                                        )
                                        logger.info(f"Активирован PREMIUM для пользователя {user_id}")
                                    except Exception as e:
                                        logger.error(f"Ошибка уведомления о премиуме: {e}")
                                    
                                    # Обновляем статус инвойса
                                    invoice_data["paid_at"] = datetime.now()
                
                except Exception as e:
                    logger.error(f"Ошибка проверки инвойса {invoice_id}: {e}")
            
            # Пауза между проверками
            time.sleep(PAYMENT_CHECK_INTERVAL)
            
        except Exception as e:
            logger.error(f"Критическая ошибка в проверке платежей: {e}")
            time.sleep(60)

# Запускаем фоновую проверку
payment_thread = threading.Thread(target=payment_checker_loop, daemon=True)
payment_thread.start()

# ===== ОСНОВНЫЕ КОМАНДЫ =====
@bot.message_handler(commands=['start'])
def start_command(message):
    """Обработка команды /start"""
    user_id = message.from_user.id
    user_name = message.from_user.username or message.from_user.first_name
    
    # Регистрируем/обновляем пользователя
    if user_id not in storage.users:
        storage.users[user_id] = {
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "created_at": datetime.now().isoformat(),
            "is_premium": user_id in storage.premium_users,
            "premium_until": None,
            "ads_count": 0
        }
        logger.info(f"Новый пользователь: {user_id} ({user_name})")
    
    # Гарантируем основную клавиатуру
    welcome_text = """
🤖 <b>Добро пожаловать в бот для продажи телефонов!</b>

📌 <b>Основные правила:</b>
• Запрещены мошеннические объявления
• Фото должны быть качественными
• Указывайте реальные цены
• Будьте вежливы с покупателями

Выберите действие с помощью кнопок ниже 👇
"""
    
    # Отправляем основное сообщение с клавиатурой
    safe_send_message(user_id, welcome_text)
    
    # Дополнительное меню с inline-кнопками
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("📱 Создать объявление", callback_data="create_ad"),
        types.InlineKeyboardButton("📖 FAQ/Правила", callback_data="faq")
    )
    
    bot.send_message(user_id, "Быстрые действия:", reply_markup=keyboard)

@bot.message_handler(func=lambda m: m.text == "❓ Помощь")
@bot.message_handler(commands=['help'])
def help_command(message):
    """Обработка команды помощи"""
    user_id = message.from_user.id
    
    help_text = """
🆘 <b>Помощь по боту</b>

📱 <b>Создание объявления:</b>
1. Нажмите "Создать объявление"
2. Выберите модель телефона
3. Укажите характеристики
4. Загрузите 2-4 фотографии
5. Подтвердите публикацию

💰 <b>Донат через CryptoBot:</b>
• Поддержите развитие бота криптовалютой
• Получите премиум-статус
• Выделение ваших объявлений

📞 <b>Поддержка:</b>
• Нажмите кнопку "Поддержка"
• Опишите вашу проблему
• Наш менеджер ответит вам

🔧 <b>Основные команды:</b>
/start - Перезапуск бота
/help - Эта справка
/myads - Мои объявления
"""
    
    safe_send_message(user_id, help_text)

@bot.message_handler(func=lambda m: m.text == "💎 Донат")
def donate_command(message):
    """Обработка команды доната"""
    user_id = message.from_user.id
    
    donate_text = """
💎 <b>Поддержите развитие бота через CryptoBot!</b>

Ваша поддержка помогает:
• Развивать новые функции
• Улучшать стабильность работы
• Добавлять новые возможности

<b>Премиум-статус включает:</b>
✅ Выделение объявлений цветом
✅ Топ-позиция в поиске
✅ Приоритетная поддержка
✅ Аналитика просмотров

💰 <b>299 сом/месяц</b> (примерно 3 USDT)
"""
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("💳 Купить PREMIUM", callback_data="buy_premium"),
        types.InlineKeyboardButton("🎁 Просто поддержать", callback_data="simple_donate")
    )
    keyboard.add(
        types.InlineKeyboardButton("🔄 Проверить оплату", callback_data="check_payment"),
        types.InlineKeyboardButton("📊 Мои платежи", callback_data="my_payments")
    )
    
    safe_send_message(user_id, donate_text, reply_markup=keyboard)

@bot.message_handler(func=lambda m: m.text == "📞 Поддержка")
def support_command(message):
    """Обработка команды поддержки"""
    user_id = message.from_user.id
    
    support_text = """
📞 <b>Техническая поддержка</b>

Опишите вашу проблему или вопрос:
• Проблемы с созданием объявления
• Вопросы по оплате
• Жалобы на пользователей
• Предложения по улучшению

Наш менеджер ответит вам в течение 24 часов.

<b>Отправьте ваше сообщение ниже:</b>
"""
    
    UserState.set_state(user_id, "waiting_support")
    safe_send_message(user_id, support_text, reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda m: m.text == "📋 Мои объявления")
@bot.message_handler(commands=['myads'])
def my_ads_command(message):
    """Показать объявления пользователя"""
    user_id = message.from_user.id
    
    # Получаем объявления пользователя
    user_ads = []
    for ad_id, ad in storage.ads.items():
        if ad.get('user_id') == user_id:
            user_ads.append((ad_id, ad))
    
    if not user_ads:
        safe_send_message(user_id, "📭 У вас пока нет активных объявлений.")
        return
    
    # Сортируем по дате создания (новые сначала)
    user_ads.sort(key=lambda x: x[1].get('created_at', ''), reverse=True)
    
    # Ограничиваем количество
    user_ads = user_ads[:10]
    
    # Отправляем список объявлений
    for ad_id, ad in user_ads:
        ad_text = format_ad_preview(ad, for_owner=True)
        
        # Создаем inline-клавиатуру для управления
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_ad:{ad_id}"),
            types.InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_ad:{ad_id}")
        )
        keyboard.add(
            types.InlineKeyboardButton("📊 Статистика", callback_data=f"stats_ad:{ad_id}"),
            types.InlineKeyboardButton("🔄 Обновить", callback_data=f"refresh_ad:{ad_id}")
        )
        
        # Пытаемся отправить фото, если есть
        photos = ad.get('photos', [])
        if photos:
            try:
                if len(photos) == 1:
                    bot.send_photo(user_id, photos[0], caption=ad_text, reply_markup=keyboard)
                else:
                    media = []
                    for i, photo in enumerate(photos[:10]):  # Ограничиваем количество
                        if i == 0:
                            media.append(types.InputMediaPhoto(photo, caption=ad_text))
                        else:
                            media.append(types.InputMediaPhoto(photo))
                    bot.send_media_group(user_id, media)
                    bot.send_message(user_id, "Управление объявлением:", reply_markup=keyboard)
            except Exception as e:
                logger.error(f"Ошибка отправки фото объявления: {e}")
                safe_send_message(user_id, ad_text, reply_markup=keyboard)
        else:
            safe_send_message(user_id, ad_text, reply_markup=keyboard)

# ===== ФОРМАТИРОВАНИЕ ОБЪЯВЛЕНИЙ =====
def format_ad_preview(ad, for_owner=False):
    """Форматирование превью объявления"""
    premium_badge = "💎 <b>ПРЕМИУМ ОБЪЯВЛЕНИЕ</b>\n\n" if ad.get('is_premium') else ""
    
    lines = [
        f"{premium_badge}📱 <b>Модель:</b> {ad.get('model', 'Не указано')}",
        f"📊 <b>Состояние:</b> {ad.get('condition', 'Не указано')}",
        f"💾 <b>Память:</b> {ad.get('memory', 'Не указана')}",
        f"🎨 <b>Цвет:</b> {ad.get('color', 'Не указан')}",
        f"📦 <b>Коробка:</b> {'✅ Да' if ad.get('has_box') else '❌ Нет'}",
        f"📄 <b>Документы:</b> {'✅ Да' if ad.get('has_docs') else '❌ Нет'}",
        f"🔧 <b>Комплектация:</b> {ad.get('accessories', 'Не указана')}",
        f"💰 <b>Цена:</b> {ad.get('price', 0):,} сом",
        f"📍 <b>Местоположение:</b> {ad.get('city', 'Не указан')}"
    ]
    
    if ad.get('metro'):
        lines.append(f"🚇 <b>Метро:</b> {ad.get('metro')}")
    
    if for_owner:
        lines.append(f"📅 <b>Опубликовано:</b> {datetime.fromisoformat(ad['created_at']).strftime('%d.%m.%Y %H:%M')}")
        lines.append(f"👁 <b>Просмотры:</b> {ad.get('views', 0)}")
        lines.append(f"🆔 <b>ID объявления:</b> <code>{ad.get('id', 'N/A')}</code>")
    else:
        lines.append("\n📞 <b>Для связи с продавцом используйте кнопку ниже:</b>")
    
    return "\n".join(lines)

def format_ad_for_channel(ad):
    """Форматирование объявления для канала"""
    premium_badge = "💎 <b>ПРЕМИУМ ОБЪЯВЛЕНИЕ</b>\n\n" if ad.get('is_premium') else ""
    
    text = f"""
{premium_badge}📱 <b>Модель:</b> {ad.get('model', 'Не указано')}
📊 <b>Состояние:</b> {ad.get('condition', 'Не указано')}
💾 <b>Память:</b> {ad.get('memory', 'Не указана')}
🎨 <b>Цвет:</b> {ad.get('color', 'Не указан')}
📦 <b>Коробка:</b> {'✅ Да' if ad.get('has_box') else '❌ Нет'}
📄 <b>Документы:</b> {'✅ Да' if ad.get('has_docs') else '❌ Нет'}
🔧 <b>Комплектация:</b> {ad.get('accessories', 'Не указана')}
💰 <b>Цена:</b> {ad.get('price', 0):,} сом
📍 <b>Местоположение:</b> {ad.get('city', 'Не указан')} {f'({ad.get("metro")})' if ad.get('metro') else ''}
📅 <b>Опубликовано:</b> {datetime.fromisoformat(ad['created_at']).strftime('%d.%m.%Y')}
👁 <b>Просмотры:</b> {ad.get('views', 0)}

<b>Для связи с продавцом нажмите кнопку ниже:</b>
"""
    
    # Создаем inline-клавиатуру
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("📞 Связаться", callback_data=f"contact_seller:{ad['id']}"),
        types.InlineKeyboardButton("📱 Поделиться контактом", callback_data=f"share_contact:{ad['id']}")
    )
    keyboard.add(
        types.InlineKeyboardButton("⚠️ Пожаловаться", callback_data=f"report_ad:{ad['id']}"),
        types.InlineKeyboardButton("💾 Сохранить", callback_data=f"save_ad:{ad['id']}")
    )
    
    return text, keyboard

# ===== СОЗДАНИЕ ОБЪЯВЛЕНИЯ =====
@bot.message_handler(func=lambda m: m.text == "📱 Создать объявление")
@bot.callback_query_handler(func=lambda call: call.data == "create_ad")
def start_ad_creation(update):
    """Начало создания объявления"""
    if hasattr(update, 'message'):
        user_id = update.from_user.id
    else:
        user_id = update.from_user.id
    
    # Проверяем, есть ли незавершенный черновик
    draft = AdDraftManager.get_draft(user_id)
    if draft:
        # Предлагаем продолжить или начать заново
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("↪️ Продолжить", callback_data="continue_draft"),
            types.InlineKeyboardButton("🔄 Начать заново", callback_data="restart_draft")
        )
        keyboard.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel_draft"))
        
        safe_send_message(user_id, 
            "📝 <b>Найден незавершенный черновик!</b>\n\n"
            "Хотите продолжить создание объявления или начать заново?",
            reply_markup=keyboard
        )
        return
    
    # Создаем новый черновик
    AdDraftManager.create_draft(user_id)
    UserState.set_state(user_id, "select_model")
    
    # Начинаем процесс создания
    safe_send_message(user_id, 
        "📱 <b>Выберите модель телефона:</b>\n\n"
        "Вы можете выбрать из списка или найти конкретную модель.",
        reply_markup=get_cancel_keyboard()
    )
    
    # Показываем клавиатуру с моделями
    bot.send_message(user_id, "Доступные модели:", reply_markup=get_models_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith('models_page:'))
def handle_models_pagination(call):
    """Обработка пагинации моделей"""
    user_id = call.from_user.id
    parts = call.data.split(':')
    page = int(parts[1])
    search_query = parts[2] if len(parts) > 2 else ""
    
    try:
        bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=get_models_keyboard(page, search_query)
        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        # Если сообщение устарело, отправляем новое
        logger.warning(f"Ошибка редактирования пагинации: {e}")
        bot.send_message(user_id, "Доступные модели:", reply_markup=get_models_keyboard(page, search_query))
        bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "search_model")
def search_model_handler(call):
    """Обработка поиска модели"""
    user_id = call.from_user.id
    UserState.set_state(user_id, "searching_model")
    
    bot.send_message(
        user_id,
        "🔍 <b>Поиск модели</b>\n\n"
        "Введите название модели или бренда для поиска.\n"
        "Например: <code>iPhone 15</code> или <code>Samsung Galaxy</code>",
        reply_markup=get_cancel_keyboard()
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('model:'))
def select_model_handler(call):
    """Обработка выбора модели"""
    user_id = call.from_user.id
    model_id = call.data.split(':')[1]
    
    if model_id == 'custom':
        UserState.set_state(user_id, "entering_custom_model")
        
        bot.send_message(
            user_id,
            "✏️ <b>Введите модель телефона вручную:</b>\n\n"
            "Например: <code>iPhone 15 Pro Max 256GB</code>",
            reply_markup=get_cancel_keyboard()
        )
        bot.answer_callback_query(call.id)
        return
    
    # Поиск модели в списке
    model = None
    for m in PHONE_MODELS:
        if str(m['id']) == model_id:
            model = m
            break
    
    if not model:
        bot.answer_callback_query(call.id, "❌ Модель не найдена", show_alert=True)
        return
    
    # Сохраняем модель в черновик
    model_name = f"{model['brand']} {model['model']}"
    AdDraftManager.update_draft(user_id, 'model', model_name)
    
    # Переходим к выбору состояния
    UserState.set_state(user_id, "select_condition")
    
    bot.send_message(
        user_id,
        f"📱 <b>Выбрана модель:</b> {model_name}\n\n"
        "📊 <b>Теперь выберите состояние телефона:</b>",
        reply_markup=get_cancel_keyboard()
    )
    
    bot.send_message(user_id, "Выберите состояние:", reply_markup=get_condition_keyboard())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('condition:'))
def select_condition_handler(call):
    """Обработка выбора состояния"""
    user_id = call.from_user.id
    condition = call.data.split(':')[1]
    
    # Маппинг состояний
    conditions = {
        'new': 'Новый',
        'like_new': 'Как новый',
        'good': 'Среднее',
        'damaged': 'Слегка повреждён'
    }
    
    if condition in conditions:
        AdDraftManager.update_draft(user_id, 'condition', conditions[condition])
        
        # Получаем модель для определения вариантов памяти
        draft = AdDraftManager.get_draft(user_id)
        model_name = draft.get('model', '')
        
        # Ищем модель в списке для получения вариантов памяти
        variants = []
        for m in PHONE_MODELS:
            if f"{m['brand']} {m['model']}" == model_name:
                variants = m['variants']
                break
        
        UserState.set_state(user_id, "select_memory")
        
        if variants:
            # Показываем варианты памяти
            keyboard = types.InlineKeyboardMarkup(row_width=2)
            for variant in variants:
                keyboard.add(types.InlineKeyboardButton(variant, callback_data=f"memory:{variant}"))
            keyboard.add(types.InlineKeyboardButton("📝 Другой объем", callback_data="memory:custom"))
            keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
            
            bot.send_message(
                user_id,
                "💾 <b>Выберите объем памяти:</b>\n\n"
                "Выберите из списка или укажите другой объем.",
                reply_markup=get_cancel_keyboard()
            )
            bot.send_message(user_id, "Доступные варианты:", reply_markup=keyboard)
        else:
            # Запрашиваем ввод памяти
            UserState.set_state(user_id, "entering_memory")
            bot.send_message(
                user_id,
                "💾 <b>Введите объем памяти:</b>\n\n"
                "Например: <code>128GB</code>, <code>256GB</code>, <code>512GB</code>",
                reply_markup=get_cancel_keyboard()
            )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('memory:'))
def select_memory_handler(call):
    """Обработка выбора памяти"""
    user_id = call.from_user.id
    memory = call.data.split(':')[1]
    
    if memory == 'custom':
        UserState.set_state(user_id, "entering_memory")
        bot.send_message(
            user_id,
            "💾 <b>Введите объем памяти:</b>\n\n"
            "Например: <code>128GB</code>, <code>256GB</code>, <code>512GB</code>",
            reply_markup=get_cancel_keyboard()
        )
    else:
        AdDraftManager.update_draft(user_id, 'memory', memory)
        UserState.set_state(user_id, "entering_color")
        
        bot.send_message(
            user_id,
            f"💾 <b>Выбран объем памяти:</b> {memory}\n\n"
            "🎨 <b>Теперь введите цвет телефона:</b>\n\n"
            "Например: <code>Черный</code>, <code>Белый</code>, <code>Синий</code>",
            reply_markup=get_cancel_keyboard()
        )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('box:'))
def select_box_handler(call):
    """Обработка наличия коробки"""
    user_id = call.from_user.id
    has_box = call.data.split(':')[1] == 'yes'
    
    AdDraftManager.update_draft(user_id, 'has_box', has_box)
    UserState.set_state(user_id, "select_docs")
    
    bot.send_message(
        user_id,
        f"📦 <b>Коробка:</b> {'✅ Да' if has_box else '❌ Нет'}\n\n"
        "📄 <b>Есть ли оригинальные документы?</b>",
        reply_markup=get_cancel_keyboard()
    )
    bot.send_message(user_id, "Выберите вариант:", reply_markup=get_yes_no_keyboard("docs"))
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('docs:'))
def select_docs_handler(call):
    """Обработка наличия документов"""
    user_id = call.from_user.id
    has_docs = call.data.split(':')[1] == 'yes'
    
    AdDraftManager.update_draft(user_id, 'has_docs', has_docs)
    UserState.set_state(user_id, "select_accessories")
    
    bot.send_message(
        user_id,
        f"📄 <b>Документы:</b> {'✅ Да' if has_docs else '❌ Нет'}\n\n"
        "🔧 <b>Есть ли дополнительные аксессуары?</b>\n\n"
        "Например: наушники, зарядка, кабель, чехол и т.д.",
        reply_markup=get_cancel_keyboard()
    )
    bot.send_message(user_id, "Выберите вариант:", reply_markup=get_yes_no_keyboard("accessories"))
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('accessories:'))
def select_accessories_handler(call):
    """Обработка наличия аксессуаров"""
    user_id = call.from_user.id
    has_accessories = call.data.split(':')[1] == 'yes'
    
    if has_accessories:
        UserState.set_state(user_id, "entering_accessories")
        bot.send_message(
            user_id,
            "🔧 <b>Опишите комплектацию:</b>\n\n"
            "Например: <code>Наушники, зарядка 20W, кабель USB-C, чехол</code>",
            reply_markup=get_cancel_keyboard()
        )
    else:
        AdDraftManager.update_draft(user_id, 'accessories', 'Нет')
        UserState.set_state(user_id, "entering_price")
        
        bot.send_message(
            user_id,
            "💰 <b>Введите цену в сомах:</b>\n\n"
            "Укажите только цифры, без пробелов и символов.\n"
            "Например: <code>25000</code>\n\n"
            "💡 <i>Цена должна быть от 100 до 1 000 000 сом</i>",
            reply_markup=get_cancel_keyboard()
        )
    
    bot.answer_callback_query(call.id)

# ===== ОБРАБОТКА ТЕКСТОВЫХ ВВОДОВ =====
@bot.message_handler(content_types=['text'])
def handle_text_input(message):
    """Обработка текстовых сообщений"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Получаем текущее состояние
    current_state = UserState.get_state(user_id)
    
    # Обработка отмены
    if text == "❌ Отмена":
        handle_cancel(user_id)
        return
    
    # Если нет состояния, показываем основное меню
    if not current_state:
        ensure_main_keyboard(user_id)
        return
    
    # Обработка в зависимости от состояния
    if current_state == "searching_model":
        handle_model_search(user_id, text)
    
    elif current_state == "entering_custom_model":
        handle_custom_model(user_id, text)
    
    elif current_state == "entering_memory":
        handle_memory_input(user_id, text)
    
    elif current_state == "entering_color":
        handle_color_input(user_id, text)
    
    elif current_state == "entering_accessories":
        handle_accessories_input(user_id, text)
    
    elif current_state == "entering_price":
        handle_price_input(user_id, text)
    
    elif current_state == "entering_city":
        handle_city_input(user_id, text)
    
    elif current_state == "entering_metro":
        handle_metro_input(user_id, text)
    
    elif current_state == "waiting_support":
        handle_support_message(user_id, text)
    
    else:
        # Неизвестное состояние - возвращаем в главное меню
        safe_send_message(user_id, "⚠️ Неизвестное состояние. Возвращаю в главное меню.")
        UserState.set_state(user_id, None)

def handle_cancel(user_id):
    """Обработка отмены"""
    draft = AdDraftManager.get_draft(user_id)
    
    if draft:
        # Сохраняем черновик для возможности продолжения
        safe_send_message(user_id, 
            "❌ <b>Создание объявления отменено.</b>\n\n"
            "Черновик сохранен. Вы можете продолжить позже, нажав 'Создать объявление'.",
            reply_markup=get_main_keyboard()
        )
    else:
        safe_send_message(user_id, 
            "❌ <b>Действие отменено.</b>\n\n"
            "Возвращаю в главное меню.",
            reply_markup=get_main_keyboard()
        )
    
    UserState.set_state(user_id, None)

def handle_model_search(user_id, query):
    """Обработка поиска модели"""
    if len(query) < 2:
        safe_send_message(user_id, 
            "❌ <b>Слишком короткий запрос.</b>\n\n"
            "Введите минимум 2 символа для поиска.",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Ищем модели
    found_models = []
    for model in PHONE_MODELS:
        full_name = f"{model['brand']} {model['model']}".lower()
        if query.lower() in full_name:
            found_models.append(model)
    
    if found_models:
        # Показываем первую страницу результатов
        bot.send_message(user_id, 
            f"🔍 <b>Результаты поиска по запросу</b> '{query}':",
            reply_markup=get_cancel_keyboard()
        )
        bot.send_message(user_id, "Найденные модели:", reply_markup=get_models_keyboard(0, query))
    else:
        safe_send_message(user_id,
            f"🔍 <b>По запросу '{query}' ничего не найдено.</b>\n\n"
            "Попробуйте другой запрос или выберите модель из списка.",
            reply_markup=get_cancel_keyboard()
        )
        bot.send_message(user_id, "Все модели:", reply_markup=get_models_keyboard())

def handle_custom_model(user_id, model_name):
    """Обработка ввода своей модели"""
    if len(model_name) < 2:
        safe_send_message(user_id,
            "❌ <b>Слишком короткое название модели.</b>\n\n"
            "Введите полное название модели.",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    AdDraftManager.update_draft(user_id, 'model', model_name)
    UserState.set_state(user_id, "select_condition")
    
    safe_send_message(user_id,
        f"📱 <b>Модель сохранена:</b> {model_name}\n\n"
        "📊 <b>Теперь выберите состояние телефона:</b>",
        reply_markup=get_cancel_keyboard()
    )
    bot.send_message(user_id, "Выберите состояние:", reply_markup=get_condition_keyboard())

def handle_memory_input(user_id, memory):
    """Обработка ввода памяти"""
    if len(memory) < 2:
        safe_send_message(user_id,
            "❌ <b>Некорректный объем памяти.</b>\n\n"
            "Введите корректный объем, например: <code>128GB</code>",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    AdDraftManager.update_draft(user_id, 'memory', memory)
    UserState.set_state(user_id, "entering_color")
    
    safe_send_message(user_id,
        f"💾 <b>Объем памяти сохранен:</b> {memory}\n\n"
        "🎨 <b>Теперь введите цвет телефона:</b>\n\n"
        "Например: <code>Черный</code>, <code>Белый</code>, <code>Синий</code>",
        reply_markup=get_cancel_keyboard()
    )

def handle_color_input(user_id, color):
    """Обработка ввода цвета"""
    if len(color) < 2:
        safe_send_message(user_id,
            "❌ <b>Некорректный цвет.</b>\n\n"
            "Введите корректное название цвета.",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    AdDraftManager.update_draft(user_id, 'color', color)
    UserState.set_state(user_id, "select_box")
    
    safe_send_message(user_id,
        f"🎨 <b>Цвет сохранен:</b> {color}\n\n"
        "📦 <b>Есть ли оригинальная коробка?</b>",
        reply_markup=get_cancel_keyboard()
    )
    bot.send_message(user_id, "Выберите вариант:", reply_markup=get_yes_no_keyboard("box"))

def handle_accessories_input(user_id, accessories):
    """Обработка ввода комплектации"""
    if len(accessories) < 2:
        safe_send_message(user_id,
            "❌ <b>Слишком короткое описание.</b>\n\n"
            "Опишите комплектацию подробнее.",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    AdDraftManager.update_draft(user_id, 'accessories', accessories)
    UserState.set_state(user_id, "entering_price")
    
    safe_send_message(user_id,
        f"🔧 <b>Комплектация сохранена:</b>\n{accessories}\n\n"
        "💰 <b>Теперь введите цену в сомах:</b>\n\n"
        "Укажите только цифры, без пробелов и символов.\n"
        "Например: <code>25000</code>\n\n"
        "💡 <i>Цена должна быть от 100 до 1 000 000 сом</i>",
        reply_markup=get_cancel_keyboard()
    )

def handle_price_input(user_id, price_text):
    """Обработка ввода цены"""
    is_valid, price = validate_price(price_text)
    
    if not is_valid:
        safe_send_message(user_id,
            "❌ <b>Некорректная цена!</b>\n\n"
            "Цена должна быть числом от 100 до 1 000 000 сом.\n"
            "Укажите только цифры, без пробелов и символов.\n\n"
            "Примеры:\n"
            "<code>15000</code> - правильно\n"
            "<code>15 000</code> - неправильно\n"
            "<code>15,000</code> - неправильно\n"
            "<code>15.000</code> - неправильно",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    AdDraftManager.update_draft(user_id, 'price', price)
    UserState.set_state(user_id, "entering_city")
    
    safe_send_message(user_id,
        f"💰 <b>Цена сохранена:</b> {price:,} сом\n\n"
        "📍 <b>Теперь введите город:</b>\n\n"
        "Например: <code>Бишкек</code>, <code>Ош</code>",
        reply_markup=get_cancel_keyboard()
    )

def handle_city_input(user_id, city):
    """Обработка ввода города"""
    if len(city) < 2:
        safe_send_message(user_id,
            "❌ <b>Некорректное название города.</b>\n\n"
            "Введите корректное название города.",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    AdDraftManager.update_draft(user_id, 'city', city)
    UserState.set_state(user_id, "entering_metro")
    
    safe_send_message(user_id,
        f"📍 <b>Город сохранен:</b> {city}\n\n"
        "🚇 <b>Укажите станцию метро или ближайший ориентир:</b>\n\n"
        "Например: <code>Аламедин</code> или <code>Южные ворота</code>\n"
        "Или напишите <code>нет</code>, если не важно.",
        reply_markup=get_cancel_keyboard()
    )

def handle_metro_input(user_id, metro):
    """Обработка ввода метро"""
    if metro.lower() == 'нет':
        metro = None
    
    AdDraftManager.update_draft(user_id, 'metro', metro)
    UserState.set_state(user_id, "uploading_photos")
    
    safe_send_message(user_id,
        "📸 <b>Теперь загрузите фотографии:</b>\n\n"
        f"• Минимум: <b>{MIN_PHOTOS}</b> фото\n"
        f"• Максимум: <b>{MAX_PHOTOS}</b> фото\n\n"
        "<b>Рекомендуемые фото:</b>\n"
        "1. Фото спереди\n"
        "2. Фото сзади\n"
        "3. Фото сбоку\n"
        "4. Фото экрана\n"
        "5. Фото повреждений (если есть)\n\n"
        "📤 <i>Отправляйте фото по одному или несколько сразу.</i>",
        reply_markup=get_cancel_keyboard()
    )

def handle_support_message(user_id, message_text):
    """Обработка сообщения в поддержку"""
    # Сохраняем сообщение
    storage.support_messages[user_id] = {
        'text': message_text,
        'username': storage.users.get(user_id, {}).get('username', 'N/A'),
        'first_name': storage.users.get(user_id, {}).get('first_name', 'N/A'),
        'timestamp': datetime.now()
    }
    
    # Формируем сообщение для администраторов
    support_msg = f"""
📩 <b>НОВОЕ СООБЩЕНИЕ В ПОДДЕРЖКУ</b>

👤 <b>Пользователь:</b>
• ID: <code>{user_id}</code>
• Username: @{storage.users.get(user_id, {}).get('username', 'Нет')}
• Имя: {storage.users.get(user_id, {}).get('first_name', 'Неизвестно')}

💬 <b>Сообщение:</b>
{message_text}

⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}
"""
    
    # Отправляем администраторам
    for admin_id in ADMIN_IDS:
        try:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("📝 Ответить", callback_data=f"reply_to:{user_id}"))
            keyboard.add(types.InlineKeyboardButton("✅ Решено", callback_data=f"support_done:{user_id}"))
            
            bot.send_message(admin_id, support_msg, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения админу {admin_id}: {e}")
    
    # Подтверждаем пользователю
    safe_send_message(user_id,
        "✅ <b>Ваше сообщение отправлено в поддержку!</b>\n\n"
        "Наш менеджер ответит вам в течение 24 часов.\n\n"
        "Спасибо за обращение!",
        reply_markup=get_main_keyboard()
    )
    
    UserState.set_state(user_id, None)

# ===== ОБРАБОТКА ФОТОГРАФИЙ =====
@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    """Обработка загрузки фотографий"""
    user_id = message.from_user.id
    current_state = UserState.get_state(user_id)
    
    # Проверяем, находится ли пользователь в процессе загрузки фото
    if current_state != "uploading_photos":
        # Показываем основное меню
        ensure_main_keyboard(user_id)
        return
    
    # Получаем черновик
    draft = AdDraftManager.get_draft(user_id)
    if not draft:
        safe_send_message(user_id,
            "❌ <b>Черновик не найден.</b>\n\n"
            "Начните создание объявления заново.",
            reply_markup=get_main_keyboard()
        )
        UserState.set_state(user_id, None)
        return
    
    # Получаем file_id самой большой версии фото
    photo_id = message.photo[-1].file_id
    
    # Добавляем фото в черновик
    success = AdDraftManager.add_photo(user_id, photo_id)
    
    if not success:
        safe_send_message(user_id,
            f"❌ <b>Не удалось добавить фото.</b>\n\n"
            f"Вы уже загрузили максимальное количество фото ({MAX_PHOTOS}).",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Получаем текущее количество фото
    photos_count = len(draft.get('photos', []))
    
    if photos_count < MIN_PHOTOS:
        # Нужно еще фото
        remaining = MIN_PHOTOS - photos_count
        
        safe_send_message(user_id,
            f"📸 <b>Загружено фото:</b> {photos_count}\n\n"
            f"📥 <b>Нужно еще:</b> {remaining}\n\n"
            "Продолжайте загружать фото или нажмите '❌ Отмена' для отмены.",
            reply_markup=get_cancel_keyboard()
        )
        
    elif photos_count == MIN_PHOTOS:
        # Минимальное количество достигнуто
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("✅ Достаточно", callback_data="photos_done"),
            types.InlineKeyboardButton("➕ Еще фото", callback_data="add_more_photos")
        )
        
        safe_send_message(user_id,
            f"📸 <b>Минимальное количество фото загружено!</b>\n\n"
            f"Загружено: {photos_count} фото\n"
            f"Можно добавить еще: {MAX_PHOTOS - photos_count} фото\n\n"
            "Можете добавить еще фото или продолжить.",
            reply_markup=keyboard
        )
        
    elif photos_count > MIN_PHOTOS and photos_count < MAX_PHOTOS:
        # Можно добавить еще
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("✅ Хватит", callback_data="photos_done"),
            types.InlineKeyboardButton("➕ Еще фото", callback_data="add_more_photos")
        )
        
        safe_send_message(user_id,
            f"📸 <b>Загружено фото:</b> {photos_count}\n\n"
            f"Можно добавить еще: {MAX_PHOTOS - photos_count} фото\n\n"
            "Можете добавить еще фото или продолжить.",
            reply_markup=keyboard
        )
        
    elif photos_count >= MAX_PHOTOS:
        # Достигнут максимум
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("✅ Продолжить", callback_data="photos_done"))
        
        safe_send_message(user_id,
            f"📸 <b>Достигнут максимум фото!</b>\n\n"
            f"Загружено: {photos_count} фото\n\n"
            "Больше фото добавить нельзя. Продолжаем.",
            reply_markup=keyboard
        )

@bot.callback_query_handler(func=lambda call: call.data == "photos_done")
def photos_done_handler(call):
    """Обработка завершения загрузки фото"""
    user_id = call.from_user.id
    draft = AdDraftManager.get_draft(user_id)
    
    if not draft:
        bot.answer_callback_query(call.id, "❌ Черновик не найден", show_alert=True)
        return
    
    photos_count = len(draft.get('photos', []))
    
    if photos_count < MIN_PHOTOS:
        bot.answer_callback_query(call.id, 
            f"❌ Нужно минимум {MIN_PHOTOS} фото", 
            show_alert=True)
        return
    
    # Переходим к предпросмотру
    UserState.set_state(user_id, "preview_ad")
    
    # Показываем превью объявления
    show_ad_preview(user_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "add_more_photos")
def add_more_photos_handler(call):
    """Обработка добавления дополнительных фото"""
    user_id = call.from_user.id
    draft = AdDraftManager.get_draft(user_id)
    
    if not draft:
        bot.answer_callback_query(call.id, "❌ Черновик не найден", show_alert=True)
        return
    
    photos_count = len(draft.get('photos', []))
    
    if photos_count >= MAX_PHOTOS:
        bot.answer_callback_query(call.id, 
            f"❌ Достигнут максимум {MAX_PHOTOS} фото", 
            show_alert=True)
        return
    
    # Возвращаем в состояние загрузки фото
    UserState.set_state(user_id, "uploading_photos")
    
    safe_send_message(user_id,
        f"📸 <b>Продолжаем загрузку фото</b>\n\n"
        f"Загружено: {photos_count} фото\n"
        f"Можно добавить еще: {MAX_PHOTOS - photos_count} фото\n\n"
        "Отправляйте фото по одному или несколько сразу.",
        reply_markup=get_cancel_keyboard()
    )
    bot.answer_callback_query(call.id)

def show_ad_preview(user_id):
    """Показ предпросмотра объявления"""
    draft = AdDraftManager.get_draft(user_id)
    
    if not draft:
        safe_send_message(user_id,
            "❌ <b>Черновик не найден.</b>\n\n"
            "Начните создание объявления заново.",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Форматируем текст объявления
    preview_text = format_ad_preview(draft, for_owner=True)
    
    # Добавляем информацию о фото
    photos_count = len(draft.get('photos', []))
    preview_text += f"\n📸 <b>Фотографий:</b> {photos_count}"
    
    # Показываем фото, если есть
    photos = draft.get('photos', [])
    if photos:
        try:
            if len(photos) == 1:
                msg = bot.send_photo(user_id, photos[0], 
                    caption=preview_text,
                    reply_markup=get_cancel_keyboard())
            else:
                media = []
                for i, photo in enumerate(photos[:10]):  # Ограничиваем количество
                    if i == 0:
                        media.append(types.InputMediaPhoto(photo, caption=preview_text))
                    else:
                        media.append(types.InputMediaPhoto(photo))
                
                bot.send_media_group(user_id, media)
                msg = bot.send_message(user_id, "Превью объявления:", 
                    reply_markup=get_cancel_keyboard())
                
                if msg:
                    storage.message_cache[(user_id, msg.message_id)] = {
                        'type': 'ad_preview',
                        'timestamp': datetime.now()
                    }
                    
        except Exception as e:
            logger.error(f"Ошибка отправки фото превью: {e}")
            safe_send_message(user_id, preview_text, reply_markup=get_cancel_keyboard())
    else:
        safe_send_message(user_id, preview_text, reply_markup=get_cancel_keyboard())
    
    # Показываем кнопки действий
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✅ Опубликовать", callback_data="publish_ad"),
        types.InlineKeyboardButton("✏️ Редактировать", callback_data="edit_draft")
    )
    keyboard.add(
        types.InlineKeyboardButton("💎 Сделать PREMIUM", callback_data="make_premium"),
        types.InlineKeyboardButton("⬅️ Назад", callback_data="back")
    )
    
    bot.send_message(user_id,
        "📋 <b>ПРЕВЬЮ ОБЪЯВЛЕНИЯ</b>\n\n"
        "Проверьте информацию выше. Все верно?",
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data == "publish_ad")
def publish_ad_handler(call):
    """Обработка публикации объявления"""
    user_id = call.from_user.id
    draft = AdDraftManager.get_draft(user_id)
    
    if not draft:
        bot.answer_callback_query(call.id, "❌ Черновик не найден", show_alert=True)
        return
    
    # Проверяем черновик
    is_valid, error_message = AdDraftManager.validate_draft(user_id)
    
    if not is_valid:
        bot.answer_callback_query(call.id, f"❌ {error_message}", show_alert=True)
        return
    
    # Генерируем ID объявления
    ad_id = generate_ad_id(user_id)
    
    # Создаем полное объявление
    ad = {
        'id': ad_id,
        'user_id': user_id,
        'model': draft.get('model'),
        'condition': draft.get('condition'),
        'memory': draft.get('memory'),
        'color': draft.get('color'),
        'has_box': draft.get('has_box', False),
        'has_docs': draft.get('has_docs', False),
        'accessories': draft.get('accessories', 'Нет'),
        'price': draft.get('price', 0),
        'city': draft.get('city'),
        'metro': draft.get('metro'),
        'photos': draft.get('photos', []).copy(),  # Копируем список фото
        'created_at': datetime.now().isoformat(),
        'views': 0,
        'is_premium': user_id in storage.premium_users,
        'status': 'active'
    }
    
    # Сохраняем объявление
    storage.ads[ad_id] = ad
    
    # Увеличиваем счетчик объявлений пользователя
    if user_id in storage.users:
        storage.users[user_id]['ads_count'] = storage.users[user_id].get('ads_count', 0) + 1
    
    try:
        # Публикуем в канале
        ad_text, keyboard = format_ad_for_channel(ad)
        photos = ad.get('photos', [])
        
        if photos:
            if len(photos) == 1:
                bot.send_photo(CHANNEL_ID, photos[0], caption=ad_text, reply_markup=keyboard)
            else:
                media = []
                for i, photo in enumerate(photos[:10]):
                    if i == 0:
                        media.append(types.InputMediaPhoto(photo, caption=ad_text))
                    else:
                        media.append(types.InputMediaPhoto(photo))
                
                bot.send_media_group(CHANNEL_ID, media)
                bot.send_message(CHANNEL_ID, 
                    "📞 <b>Для связи с продавцом используйте кнопки ниже:</b>",
                    reply_markup=keyboard)
        
        else:
            bot.send_message(CHANNEL_ID, ad_text, reply_markup=keyboard)
        
        # Уведомляем пользователя об успешной публикации
        safe_send_message(user_id,
            f"🎉 <b>Объявление успешно опубликовано!</b>\n\n"
            f"🆔 <b>ID объявления:</b> <code>{ad_id}</code>\n"
            f"📱 <b>Модель:</b> {ad.get('model')}\n"
            f"💰 <b>Цена:</b> {ad.get('price'):,} сом\n\n"
            f"📊 <b>Статистика:</b> 0 просмотров\n\n"
            f"Вы можете управлять объявлением через меню 'Мои объявления'.",
            reply_markup=get_main_keyboard()
        )
        
        # Очищаем черновик и состояние
        if user_id in storage.drafts:
            del storage.drafts[user_id]
        UserState.set_state(user_id, None)
        
        bot.answer_callback_query(call.id, "✅ Объявление опубликовано!")
        
    except Exception as e:
        logger.error(f"Ошибка публикации объявления: {e}")
        
        # Сохраняем объявление в хранилище, но помечаем как неопубликованное
        ad['status'] = 'draft'
        storage.ads[ad_id] = ad
        
        safe_send_message(user_id,
            "❌ <b>Ошибка публикации!</b>\n\n"
            "Не удалось опубликовать объявление в канале.\n"
            f"<b>Ошибка:</b> {str(e)}\n\n"
            "Объявление сохранено как черновик. Попробуйте опубликовать позже.",
            reply_markup=get_main_keyboard()
        )
        
        bot.answer_callback_query(call.id, "❌ Ошибка публикации", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data == "back")
def back_handler(call):
    """Обработка кнопки 'Назад'"""
    user_id = call.from_user.id
    
    # Получаем текущее состояние
    current_state = UserState.get_state(user_id)
    
    if not current_state:
        bot.answer_callback_query(call.id, "❌ Нет активного состояния", show_alert=True)
        return
    
    # Определяем, куда вернуться
    if current_state == "select_condition":
        # Возвращаем к выбору модели
        UserState.set_state(user_id, "select_model")
        bot.send_message(user_id, "📱 Выберите модель телефона:", 
                        reply_markup=get_cancel_keyboard())
        bot.send_message(user_id, "Доступные модели:", 
                        reply_markup=get_models_keyboard())
    
    elif current_state == "select_memory" or current_state == "entering_memory":
        # Возвращаем к выбору состояния
        UserState.set_state(user_id, "select_condition")
        bot.send_message(user_id, "📊 Выберите состояние телефона:", 
                        reply_markup=get_cancel_keyboard())
        bot.send_message(user_id, "Выберите состояние:", 
                        reply_markup=get_condition_keyboard())
    
    elif current_state == "entering_color":
        # Возвращаем к выбору памяти
        draft = AdDraftManager.get_draft(user_id)
        model_name = draft.get('model', '') if draft else ''
        
        # Проверяем, есть ли предопределенные варианты памяти
        variants = []
        for m in PHONE_MODELS:
            if f"{m['brand']} {m['model']}" == model_name:
                variants = m['variants']
                break
        
        if variants:
            UserState.set_state(user_id, "select_memory")
            keyboard = types.InlineKeyboardMarkup(row_width=2)
            for variant in variants:
                keyboard.add(types.InlineKeyboardButton(variant, 
                             callback_data=f"memory:{variant}"))
            keyboard.add(types.InlineKeyboardButton("📝 Другой объем", 
                         callback_data="memory:custom"))
            keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
            
            bot.send_message(user_id, "💾 Выберите объем памяти:", 
                            reply_markup=keyboard)
        else:
            UserState.set_state(user_id, "entering_memory")
            bot.send_message(user_id,
                "💾 Введите объем памяти:",
                reply_markup=get_cancel_keyboard()
            )
    
    elif current_state == "select_box":
        # Возвращаем к вводу цвета
        UserState.set_state(user_id, "entering_color")
        bot.send_message(user_id,
            "🎨 Введите цвет телефона:",
            reply_markup=get_cancel_keyboard()
        )
    
    elif current_state == "select_docs":
        # Возвращаем к выбору коробки
        UserState.set_state(user_id, "select_box")
        bot.send_message(user_id, "📦 Есть ли оригинальная коробка?", 
                        reply_markup=get_cancel_keyboard())
        bot.send_message(user_id, "Выберите вариант:", 
                        reply_markup=get_yes_no_keyboard("box"))
    
    elif current_state == "select_accessories":
        # Возвращаем к выбору документов
        UserState.set_state(user_id, "select_docs")
        bot.send_message(user_id, "📄 Есть ли оригинальные документы?", 
                        reply_markup=get_cancel_keyboard())
        bot.send_message(user_id, "Выберите вариант:", 
                        reply_markup=get_yes_no_keyboard("docs"))
    
    elif current_state == "entering_accessories":
        # Возвращаем к выбору аксессуаров
        UserState.set_state(user_id, "select_accessories")
        bot.send_message(user_id, "🔧 Есть ли дополнительные аксессуары?", 
                        reply_markup=get_cancel_keyboard())
        bot.send_message(user_id, "Выберите вариант:", 
                        reply_markup=get_yes_no_keyboard("accessories"))
    
    elif current_state == "entering_price":
        # Возвращаем к вводу комплектации или выбору аксессуаров
        draft = AdDraftManager.get_draft(user_id)
        if draft and draft.get('accessories'):
            # Если комплектация уже введена, возвращаем к редактированию
            UserState.set_state(user_id, "entering_accessories")
            bot.send_message(user_id,
                "🔧 Редактируйте комплектацию:",
                reply_markup=get_cancel_keyboard()
            )
        else:
            # Иначе возвращаем к выбору аксессуаров
            UserState.set_state(user_id, "select_accessories")
            bot.send_message(user_id, "🔧 Есть ли дополнительные аксессуары?", 
                            reply_markup=get_cancel_keyboard())
            bot.send_message(user_id, "Выберите вариант:", 
                            reply_markup=get_yes_no_keyboard("accessories"))
    
    elif current_state == "entering_city":
        # Возвращаем к вводу цены
        UserState.set_state(user_id, "entering_price")
        bot.send_message(user_id,
            "💰 Введите цену в сомах:",
            reply_markup=get_cancel_keyboard()
        )
    
    elif current_state == "entering_metro":
        # Возвращаем к вводу города
        UserState.set_state(user_id, "entering_city")
        bot.send_message(user_id,
            "📍 Введите город:",
            reply_markup=get_cancel_keyboard()
        )
    
    elif current_state == "uploading_photos":
        # Возвращаем к вводу метро
        UserState.set_state(user_id, "entering_metro")
        bot.send_message(user_id,
            "🚇 Укажите станцию метро или напишите 'нет':",
            reply_markup=get_cancel_keyboard()
        )
    
    elif current_state == "preview_ad":
        # Возвращаем к загрузке фото
        UserState.set_state(user_id, "uploading_photos")
        draft = AdDraftManager.get_draft(user_id)
        photos_count = len(draft.get('photos', [])) if draft else 0
        
        bot.send_message(user_id,
            f"📸 <b>Редактирование фотографий</b>\n\n"
            f"Загружено: {photos_count} фото\n"
            f"Можно добавить: {MAX_PHOTOS - photos_count} фото\n\n"
            "Отправляйте новые фото или нажмите '❌ Отмена' для выхода.",
            reply_markup=get_cancel_keyboard()
        )
    
    else:
        # Для других состояний просто очищаем состояние
        UserState.set_state(user_id, None)
        ensure_main_keyboard(user_id)
    
    bot.answer_callback_query(call.id)

# ===== ОБРАБОТКА CALLBACK-КНОПОК =====
@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    """Обработка всех callback-кнопок"""
    try:
        # Логируем callback для отладки
        logger.debug(f"Callback от {call.from_user.id}: {call.data}")
        
        # Обрабатываем специальные кнопки
        if call.data == "faq":
            show_faq(call)
        elif call.data == "buy_premium":
            buy_premium(call)
        elif call.data == "check_payment":
            check_payment(call)
        elif call.data.startswith("reply_to:"):
            handle_admin_reply(call)
        elif call.data.startswith("contact_seller:"):
            contact_seller(call)
        elif call.data.startswith("edit_ad:"):
            edit_advertisement(call)
        elif call.data.startswith("delete_ad:"):
            delete_advertisement(call)
        elif call.data.startswith("stats_ad:"):
            show_ad_stats(call)
        elif call.data == "continue_draft":
            continue_draft(call)
        elif call.data == "restart_draft":
            restart_draft(call)
        elif call.data == "cancel_draft":
            cancel_draft(call)
        elif call.data == "edit_draft":
            edit_draft(call)
        elif call.data == "make_premium":
            make_premium(call)
        else:
            # Для остальных кнопок просто подтверждаем получение
            bot.answer_callback_query(call.id, "✅")
            
    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        
        try:
            # Пытаемся уведомить пользователя об ошибке
            bot.answer_callback_query(call.id, 
                "❌ Произошла ошибка. Попробуйте еще раз.", 
                show_alert=True)
            
            # Возвращаем основную клавиатуру
            ensure_main_keyboard(call.from_user.id)
            
        except Exception as inner_e:
            logger.error(f"Дополнительная ошибка при обработке callback: {inner_e}")

def show_faq(call):
    """Показать FAQ"""
    user_id = call.from_user.id
    
    faq_text = """
📖 <b>FAQ / Часто задаваемые вопросы</b>

❓ <b>Как создать объявление?</b>
1. Нажмите "Создать объявление"
2. Выберите модель телефона
3. Укажите характеристики
4. Загрузите 2-4 фотографии
5. Подтвердите публикацию

❓ <b>Сколько стоит размещение?</b>
• Обычное объявление: <b>бесплатно</b>
• Премиум объявление: <b>299 сом/месяц</b>

❓ <b>Как связаться с продавцом?</b>
• Нажмите кнопку "Связаться" под объявлением
• Отправьте свой контакт или номер телефона

❓ <b>Что дает PREMIUM статус?</b>
✅ Выделение объявлений цветом
✅ Топ-позиция в поиске
✅ Приоритетная поддержка
✅ Аналитика просмотров

⚠️ <b>Правила:</b>
1. Запрещен обман и мошенничество
2. Фото должны быть реальными
3. Цена должна соответствовать рыночной
4. Уважайте других пользователей

❗️ <b>Нарушители правил блокируются!</b>
"""
    
    safe_send_message(user_id, faq_text)
    bot.answer_callback_query(call.id)

def buy_premium(call):
    """Покупка PREMIUM статуса"""
    user_id = call.from_user.id
    
    # Проверяем, не активирован ли уже PREMIUM
    if user_id in storage.premium_users:
        bot.answer_callback_query(call.id, 
            "✅ У вас уже активирован PREMIUM статус!", 
            show_alert=True)
        return
    
    # Создаем инвойс
    invoice = CryptoBotAPI.create_invoice(
        amount=3,  # 3 USDT ≈ 299 сом
        currency="USDT",
        description="PREMIUM статус на 30 дней",
        payload=str(user_id)
    )
    
    if invoice:
        # Отправляем пользователю ссылку для оплаты
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("💳 Оплатить", url=invoice["pay_url"]))
        keyboard.add(types.InlineKeyboardButton("🔄 Проверить оплату", 
                     callback_data="check_payment"))
        
        bot.send_message(
            user_id,
            f"💎 <b>Оплатите {invoice['amount']} {invoice['asset']}</b>\n\n"
            "Для активации PREMIUM статуса на 30 дней.\n\n"
            "Ссылка для оплаты действительна 30 минут.\n"
            "После оплаты статус активируется автоматически.",
            reply_markup=keyboard
        )
        
        bot.answer_callback_query(call.id, "✅ Счет создан")
    else:
        bot.answer_callback_query(call.id, 
            "❌ Ошибка создания счета. Попробуйте позже.", 
            show_alert=True)

def check_payment(call):
    """Проверка оплаты"""
    user_id = call.from_user.id
    
    if user_id in storage.premium_users:
        bot.answer_callback_query(call.id, 
            "✅ Ваш PREMIUM статус активен!", 
            show_alert=True)
    else:
        bot.answer_callback_query(call.id,
            "ℹ️ Платежи проверяются автоматически каждые 30 секунд.\n"
            "Если вы оплатили, статус активируется в течение минуты.",
            show_alert=True)

def handle_admin_reply(call):
    """Обработка ответа администратора"""
    admin_id = call.from_user.id
    
    if admin_id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "❌ Доступ запрещен", show_alert=True)
        return
    
    # Получаем ID пользователя для ответа
    target_user_id = call.data.split(':')[1]
    
    # Устанавливаем состояние ответа
    UserState.set_state(admin_id, "admin_replying", {"target_user": target_user_id})
    
    bot.send_message(
        admin_id,
        f"✍️ <b>Введите ответ для пользователя {target_user_id}:</b>\n\n"
        "Сообщение будет отправлено пользователю.",
        reply_markup=get_cancel_keyboard()
    )
    
    bot.answer_callback_query(call.id)

def contact_seller(call):
    """Обработка связи с продавцом"""
    user_id = call.from_user.id
    ad_id = call.data.split(':')[1]
    
    ad = storage.ads.get(ad_id)
    if not ad:
        bot.answer_callback_query(call.id, "❌ Объявление не найдено", show_alert=True)
        return
    
    # Проверяем, не свое ли объявление
    if ad.get('user_id') == user_id:
        bot.answer_callback_query(call.id, 
            "❌ Это ваше собственное объявление", 
            show_alert=True)
        return
    
    # Увеличиваем счетчик просмотров
    ad['views'] = ad.get('views', 0) + 1
    
    # Предлагаем способы связи
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("📱 Отправить контакт", 
                 callback_data=f"send_contact:{ad_id}"),
        types.InlineKeyboardButton("✏️ Написать сообщение", 
                 callback_data=f"send_message:{ad_id}")
    )
    
    bot.send_message(
        user_id,
        f"📞 <b>Связь с продавцом</b>\n\n"
        f"Объявление: {ad.get('model', 'Не указано')}\n"
        f"Цена: {ad.get('price', 0):,} сом\n\n"
        "Выберите способ связи:",
        reply_markup=keyboard
    )
    
    bot.answer_callback_query(call.id)

def edit_advertisement(call):
    """Редактирование объявления"""
    user_id = call.from_user.id
    ad_id = call.data.split(':')[1]
    
    ad = storage.ads.get(ad_id)
    if not ad:
        bot.answer_callback_query(call.id, "❌ Объявление не найдено", show_alert=True)
        return
    
    # Проверяем права
    if ad.get('user_id') != user_id:
        bot.answer_callback_query(call.id, "❌ Нет прав для редактирования", show_alert=True)
        return
    
    # Создаем черновик из объявления
    storage.drafts[user_id] = {
        'user_id': user_id,
        'model': ad.get('model'),
        'condition': ad.get('condition'),
        'memory': ad.get('memory'),
        'color': ad.get('color'),
        'has_box': ad.get('has_box', False),
        'has_docs': ad.get('has_docs', False),
        'accessories': ad.get('accessories', 'Нет'),
        'price': ad.get('price', 0),
        'city': ad.get('city'),
        'metro': ad.get('metro'),
        'photos': ad.get('photos', []).copy(),
        'created_at': datetime.now(),
        'last_modified': datetime.now(),
        'original_ad_id': ad_id
    }
    
    # Начинаем редактирование
    UserState.set_state(user_id, "select_model")
    
    bot.send_message(
        user_id,
        "✏️ <b>Редактирование объявления</b>\n\n"
        "Начните редактирование с выбора модели.\n"
        "Все текущие данные сохранены в черновик.",
        reply_markup=get_cancel_keyboard()
    )
    
    bot.send_message(user_id, "Выберите модель:", reply_markup=get_models_keyboard())
    bot.answer_callback_query(call.id)

def delete_advertisement(call):
    """Удаление объявления"""
    user_id = call.from_user.id
    ad_id = call.data.split(':')[1]
    
    ad = storage.ads.get(ad_id)
    if not ad:
        bot.answer_callback_query(call.id, "❌ Объявление не найдено", show_alert=True)
        return
    
    # Проверяем права
    if ad.get('user_id') != user_id:
        bot.answer_callback_query(call.id, "❌ Нет прав для удаления", show_alert=True)
        return
    
    # Запрашиваем подтверждение
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete:{ad_id}"),
        types.InlineKeyboardButton("❌ Нет, отменить", callback_data=f"cancel_delete:{ad_id}")
    )
    
    bot.send_message(
        user_id,
        f"🗑️ <b>Удаление объявления</b>\n\n"
        f"Вы уверены, что хотите удалить объявление?\n\n"
        f"📱 {ad.get('model', 'Не указано')}\n"
        f"💰 {ad.get('price', 0):,} сом\n\n"
        f"<i>Это действие нельзя отменить!</i>",
        reply_markup=keyboard
    )
    
    bot.answer_callback_query(call.id)

def show_ad_stats(call):
    """Показать статистику объявления"""
    user_id = call.from_user.id
    ad_id = call.data.split(':')[1]
    
    ad = storage.ads.get(ad_id)
    if not ad:
        bot.answer_callback_query(call.id, "❌ Объявление не найдено", show_alert=True)
        return
    
    # Проверяем права
    if ad.get('user_id') != user_id:
        bot.answer_callback_query(call.id, "❌ Нет прав для просмотра статистики", show_alert=True)
        return
    
    # Формируем статистику
    created_date = datetime.fromisoformat(ad['created_at'])
    days_online = (datetime.now() - created_date).days
    
    stats_text = f"""
📊 <b>Статистика объявления</b>

🆔 <b>ID:</b> <code>{ad_id}</code>
📱 <b>Модель:</b> {ad.get('model', 'Не указано')}
💰 <b>Цена:</b> {ad.get('price', 0):,} сом

👁 <b>Просмотры:</b> {ad.get('views', 0)}
📅 <b>Онлайн:</b> {days_online} дней
🕐 <b>Создано:</b> {created_date.strftime('%d.%m.%Y %H:%M')}

💎 <b>Статус:</b> {'PREMIUM ✅' if ad.get('is_premium') else 'Обычный'}
"""
    
    bot.send_message(user_id, stats_text)
    bot.answer_callback_query(call.id)

def continue_draft(call):
    """Продолжить черновик"""
    user_id = call.from_user.id
    draft = AdDraftManager.get_draft(user_id)
    
    if not draft:
        bot.answer_callback_query(call.id, "❌ Черновик не найден", show_alert=True)
        return
    
    # Определяем, на каком шаге остановились
    last_step = None
    
    # Проверяем заполненные поля
    if not draft.get('model'):
        last_step = "select_model"
    elif not draft.get('condition'):
        last_step = "select_condition"
    elif not draft.get('memory'):
        # Проверяем, есть ли предопределенные варианты
        model_name = draft.get('model', '')
        variants = []
        for m in PHONE_MODELS:
            if f"{m['brand']} {m['model']}" == model_name:
                variants = m['variants']
                break
        
        if variants:
            last_step = "select_memory"
        else:
            last_step = "entering_memory"
    elif not draft.get('color'):
        last_step = "entering_color"
    elif 'has_box' not in draft:
        last_step = "select_box"
    elif 'has_docs' not in draft:
        last_step = "select_docs"
    elif not draft.get('accessories'):
        last_step = "select_accessories"
    elif not draft.get('price'):
        last_step = "entering_price"
    elif not draft.get('city'):
        last_step = "entering_city"
    elif 'metro' not in draft:
        last_step = "entering_metro"
    elif len(draft.get('photos', [])) < MIN_PHOTOS:
        last_step = "uploading_photos"
    else:
        last_step = "preview_ad"
    
    # Устанавливаем состояние
    UserState.set_state(user_id, last_step)
    
    # Продолжаем с нужного шага
    if last_step == "select_model":
        bot.send_message(user_id, "📱 Продолжаем выбор модели:", 
                        reply_markup=get_cancel_keyboard())
        bot.send_message(user_id, "Доступные модели:", 
                        reply_markup=get_models_keyboard())
    
    elif last_step == "select_condition":
        bot.send_message(user_id, "📊 Продолжаем выбор состояния:", 
                        reply_markup=get_cancel_keyboard())
        bot.send_message(user_id, "Выберите состояние:", 
                        reply_markup=get_condition_keyboard())
    
    elif last_step == "select_memory":
        model_name = draft.get('model', '')
        variants = []
        for m in PHONE_MODELS:
            if f"{m['brand']} {m['model']}" == model_name:
                variants = m['variants']
                break
        
        if variants:
            keyboard = types.InlineKeyboardMarkup(row_width=2)
            for variant in variants:
                keyboard.add(types.InlineKeyboardButton(variant, 
                             callback_data=f"memory:{variant}"))
            keyboard.add(types.InlineKeyboardButton("📝 Другой объем", 
                         callback_data="memory:custom"))
            keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="back"))
            
            bot.send_message(user_id, "💾 Продолжаем выбор памяти:", 
                            reply_markup=keyboard)
    
    elif last_step == "entering_memory":
        bot.send_message(user_id, "💾 Введите объем памяти:", 
                        reply_markup=get_cancel_keyboard())
    
    elif last_step == "entering_color":
        bot.send_message(user_id, "🎨 Введите цвет телефона:", 
                        reply_markup=get_cancel_keyboard())
    
    elif last_step == "select_box":
        bot.send_message(user_id, "📦 Есть ли оригинальная коробка?", 
                        reply_markup=get_cancel_keyboard())
        bot.send_message(user_id, "Выберите вариант:", 
                        reply_markup=get_yes_no_keyboard("box"))
    
    elif last_step == "select_docs":
        bot.send_message(user_id, "📄 Есть ли оригинальные документы?", 
                        reply_markup=get_cancel_keyboard())
        bot.send_message(user_id, "Выберите вариант:", 
                        reply_markup=get_yes_no_keyboard("docs"))
    
    elif last_step == "select_accessories":
        bot.send_message(user_id, "🔧 Есть ли дополнительные аксессуары?", 
                        reply_markup=get_cancel_keyboard())
        bot.send_message(user_id, "Выберите вариант:", 
                        reply_markup=get_yes_no_keyboard("accessories"))
    
    elif last_step == "entering_accessories":
        bot.send_message(user_id, "🔧 Опишите комплектацию:", 
                        reply_markup=get_cancel_keyboard())
    
    elif last_step == "entering_price":
        bot.send_message(user_id, "💰 Введите цену в сомах:", 
                        reply_markup=get_cancel_keyboard())
    
    elif last_step == "entering_city":
        bot.send_message(user_id, "📍 Введите город:", 
                        reply_markup=get_cancel_keyboard())
    
    elif last_step == "entering_metro":
        bot.send_message(user_id, "🚇 Укажите станцию метро:", 
                        reply_markup=get_cancel_keyboard())
    
    elif last_step == "uploading_photos":
        photos_count = len(draft.get('photos', []))
        bot.send_message(user_id,
            f"📸 Продолжаем загрузку фото\n\n"
            f"Загружено: {photos_count} фото\n"
            f"Нужно еще: {MIN_PHOTOS - photos_count} фото\n\n"
            "Отправляйте фото:",
            reply_markup=get_cancel_keyboard()
        )
    
    elif last_step == "preview_ad":
        show_ad_preview(user_id)
    
    bot.answer_callback_query(call.id)

def restart_draft(call):
    """Начать черновик заново"""
    user_id = call.from_user.id
    
    # Удаляем старый черновик
    if user_id in storage.drafts:
        del storage.drafts[user_id]
    
    # Создаем новый
    AdDraftManager.create_draft(user_id)
    UserState.set_state(user_id, "select_model")
    
    bot.send_message(user_id, 
        "🔄 <b>Начинаем создание объявления заново</b>\n\n"
        "📱 <b>Выберите модель телефона:</b>",
        reply_markup=get_cancel_keyboard()
    )
    
    bot.send_message(user_id, "Доступные модели:", reply_markup=get_models_keyboard())
    bot.answer_callback_query(call.id)

def cancel_draft(call):
    """Отменить черновик"""
    user_id = call.from_user.id
    
    # Удаляем черновик
    if user_id in storage.drafts:
        del storage.drafts[user_id]
    
    # Очищаем состояние
    UserState.set_state(user_id, None)
    
    safe_send_message(user_id,
        "❌ <b>Черновик удален.</b>\n\n"
        "Возвращаю в главное меню.",
        reply_markup=get_main_keyboard()
    )
    
    bot.answer_callback_query(call.id)

def edit_draft(call):
    """Редактировать черновик"""
    user_id = call.from_user.id
    draft = AdDraftManager.get_draft(user_id)
    
    if not draft:
        bot.answer_callback_query(call.id, "❌ Черновик не найден", show_alert=True)
        return
    
    # Предлагаем выбрать поле для редактирования
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    fields = [
        ("📱 Модель", "edit_field:model"),
        ("📊 Состояние", "edit_field:condition"),
        ("💾 Память", "edit_field:memory"),
        ("🎨 Цвет", "edit_field:color"),
        ("📦 Коробка", "edit_field:box"),
        ("📄 Документы", "edit_field:docs"),
        ("🔧 Комплектация", "edit_field:accessories"),
        ("💰 Цена", "edit_field:price"),
        ("📍 Город", "edit_field:city"),
        ("🚇 Метро", "edit_field:metro"),
        ("📸 Фото", "edit_field:photos"),
        ("⬅️ Назад", "back_to_preview")
    ]
    
    # Добавляем кнопки по 2 в ряд
    for i in range(0, len(fields), 2):
        row = fields[i:i+2]
        if len(row) == 2:
            keyboard.add(
                types.InlineKeyboardButton(row[0][0], callback_data=row[0][1]),
                types.InlineKeyboardButton(row[1][0], callback_data=row[1][1])
            )
        else:
            keyboard.add(types.InlineKeyboardButton(row[0][0], callback_data=row[0][1]))
    
    bot.send_message(
        user_id,
        "✏️ <b>Редактирование черновика</b>\n\n"
        "Выберите поле, которое хотите отредактировать:",
        reply_markup=keyboard
    )
    
    bot.answer_callback_query(call.id)

def make_premium(call):
    """Сделать объявление PREMIUM"""
    user_id = call.from_user.id
    
    # Проверяем, есть ли у пользователя PREMIUM
    if user_id not in storage.premium_users:
        bot.answer_callback_query(call.id,
            "❌ У вас нет PREMIUM статуса!\n\n"
            "Приобретите PREMIUM статус, чтобы сделать объявление премиальным.",
            show_alert=True)
        return
    
    draft = AdDraftManager.get_draft(user_id)
    if not draft:
        bot.answer_callback_query(call.id, "❌ Черновик не найден", show_alert=True)
        return
    
    # Помечаем черновик как премиальный
    draft['is_premium'] = True
    
    bot.answer_callback_query(call.id,
        "✅ Объявление будет премиальным!\n\n"
        "Теперь ваше объявление будет выделяться в канале.",
        show_alert=True)
    
    # Показываем обновленный превью
    show_ad_preview(user_id)

# ===== АДМИН КОМАНДЫ =====
@bot.message_handler(commands=['admin'])
def admin_command(message):
    """Команда администратора"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        bot.send_message(user_id, "❌ Доступ запрещен")
        return
    
    admin_text = f"""
⚙️ <b>Админ панель</b>

📊 <b>Статистика:</b>
• Пользователей: {len(storage.users)}
• Объявлений: {len(storage.ads)}
• PREMIUM пользователей: {len(storage.premium_users)}
• Черновиков: {len(storage.drafts)}

📢 <b>Команды рассылки:</b>
• /broadcast - Рассылка всем пользователям
• /stats - Подробная статистика
• /users - Список пользователей

🔧 <b>Управление:</b>
• /cleanup - Очистка старых данных
• /backup - Резервное копирование
"""
    
    safe_send_message(user_id, admin_text)

@bot.message_handler(commands=['broadcast'])
def broadcast_command(message):
    """Рассылка сообщений"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    # Сохраняем состояние рассылки
    UserState.set_state(user_id, "admin_broadcast")
    
    bot.send_message(
        user_id,
        "📢 <b>Рассылка сообщений</b>\n\n"
        "Отправьте сообщение для рассылки всем пользователям.\n"
        "Можно отправить текст, фото, видео или документ.\n\n"
        "Для отмены нажмите '❌ Отмена'.",
        reply_markup=get_cancel_keyboard()
    )

@bot.message_handler(commands=['stats'])
def stats_command(message):
    """Подробная статистика"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    # Считаем статистику
    total_ads_price = sum(ad.get('price', 0) for ad in storage.ads.values())
    active_ads = sum(1 for ad in storage.ads.values() if ad.get('status') == 'active')
    premium_ads = sum(1 for ad in storage.ads.values() if ad.get('is_premium'))
    
    # Пользователи за последнюю неделю
    week_ago = datetime.now() - timedelta(days=7)
    new_users = sum(1 for user in storage.users.values() 
                   if datetime.fromisoformat(user.get('created_at', '2000-01-01')) > week_ago)
    
    stats_text = f"""
📊 <b>Подробная статистика</b>

👥 <b>Пользователи:</b>
• Всего: {len(storage.users)}
• Новые (за неделю): {new_users}
• PREMIUM: {len(storage.premium_users)}

📢 <b>Объявления:</b>
• Всего: {len(storage.ads)}
• Активных: {active_ads}
• PREMIUM: {premium_ads}
• Общая сумма: {total_ads_price:,} сом

💰 <b>Платежи:</b>
• Инвойсов: {len(storage.invoices)}
• Оплачено: {sum(1 for i in storage.invoices.values() if i.get('status') == 'paid')}

⚙️ <b>Система:</b>
• Состояний: {len(storage.states)}
• Черновиков: {len(storage.drafts)}
• Кэш сообщений: {len(storage.message_cache)}
"""
    
    bot.send_message(user_id, stats_text)

@bot.message_handler(commands=['users'])
def users_command(message):
    """Список пользователей"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    # Получаем последних 20 пользователей
    users_list = []
    for uid, user_data in list(storage.users.items())[:20]:
        username = user_data.get('username', 'Нет')
        first_name = user_data.get('first_name', '')
        last_name = user_data.get('last_name', '')
        is_premium = "💎" if uid in storage.premium_users else "🔹"
        created = datetime.fromisoformat(user_data.get('created_at', '2000-01-01')).strftime('%d.%m.%Y')
        
        name = f"{first_name} {last_name}".strip() or "Без имени"
        users_list.append(f"{is_premium} {uid} - {name} (@{username}) - {created}")
    
    users_text = "👥 <b>Последние пользователи:</b>\n\n" + "\n".join(users_list)
    
    if len(storage.users) > 20:
        users_text += f"\n\n... и еще {len(storage.users) - 20} пользователей"
    
    bot.send_message(user_id, users_text)

# ===== ОСНОВНОЙ ЦИКЛ =====
def cleanup_old_data():
    """Очистка старых данных"""
    logger.info("Запущена очистка старых данных")
    
    cutoff_time = datetime.now() - timedelta(hours=24)
    cleaned_count = 0
    
    # Очищаем старые состояния
    for user_id, state in list(storage.states.items()):
        if state.get('timestamp', datetime.min) < cutoff_time:
            del storage.states[user_id]
            cleaned_count += 1
    
    # Очищаем старые черновики (старше 7 дней)
    draft_cutoff = datetime.now() - timedelta(days=7)
    for user_id, draft in list(storage.drafts.items()):
        if draft.get('created_at', datetime.min) < draft_cutoff:
            del storage.drafts[user_id]
            cleaned_count += 1
    
    # Очищаем старые сообщения поддержки (старше 30 дней)
    support_cutoff = datetime.now() - timedelta(days=30)
    for user_id, msg in list(storage.support_messages.items()):
        if msg.get('timestamp', datetime.min) < support_cutoff:
            del storage.support_messages[user_id]
            cleaned_count += 1
    
    # Очищаем старый кэш сообщений
    cache_cutoff = datetime.now() - timedelta(hours=6)
    for key, msg_data in list(storage.message_cache.items()):
        if msg_data.get('timestamp', datetime.min) < cache_cutoff:
            del storage.message_cache[key]
            cleaned_count += 1
    
    logger.info(f"Очистка завершена. Удалено объектов: {cleaned_count}")
    
    # Запускаем следующую очистку через 1 час
    threading.Timer(3600, cleanup_old_data).start()

# Запускаем очистку старых данных
cleanup_old_data()

# ===== ЗАПУСК БОТА =====
if __name__ == '__main__':
    print("=" * 60)
    print("🤖 БОТ ДЛЯ ОБЪЯВЛЕНИЙ О ТЕЛЕФОНАХ")
    print("=" * 60)
    print(f"Telegram Bot Token: {'✅ Установлен' if TOKEN != 'ВАШ_ТОКЕН_БОТА' else '❌ НЕ УСТАНОВЛЕН'}")
    print(f"CryptoBot API Key: {'✅ Установлен' if CRYPTO_BOT_API_KEY != 'ВАШ_КЛЮЧ_CRYPTOBOT' else '❌ НЕ УСТАНОВЛЕН'}")
    print(f"Администраторы: {ADMIN_IDS}")
    print(f"Моделей телефонов: {len(PHONE_MODELS)}")
    print(f"Канал для публикаций: {CHANNEL_ID}")
    print(f"Чат поддержки: {SUPPORT_CHAT_ID}")
    print("=" * 60)
    print("📢 Основные команды:")
    print("• /start - Начать работу")
    print("• /help - Помощь")
    print("• /myads - Мои объявления")
    print("• /admin - Админ-панель (только для администраторов)")
    print("=" * 60)
    print("🔧 Фоновые процессы запущены:")
    print("• Проверка платежей CryptoBot")
    print("• Очистка старых данных")
    print("=" * 60)
    print("🚀 Запуск бота...")
    print("Логи записываются в bot.log")
    print("=" * 60)
    
    try:
        # Устанавливаем прокси, если нужно (раскомментировать при необходимости)
        # telebot.apihelper.proxy = {'https': 'socks5://127.0.0.1:9050'}
        
        bot.polling(
            none_stop=True,
            interval=0,
            timeout=60,
            long_polling_timeout=30
        )
        
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем")
        logger.info("Бот остановлен пользователем")
        
    except Exception as e:
        logger.critical(f"Критическая ошибка бота: {e}")
        print(f"❌ Критическая ошибка: {e}")
        print("Попытка перезапуска через 30 секунд...")
        
        time.sleep(30)
        os.execv(sys.executable, [sys.executable] + sys.argv)