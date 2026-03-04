#!/usr/bin/env python3
"""
Dox Image Bot v2.3 STABLE
Затемняет изображения и добавляет пользовательский логотип с настройками
"""

import os
import logging
from io import BytesIO
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен бота из environment variable
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8578752100:AAEmpvdVrkl-n8qgocT1uYjSTWc8y49J3GU")

# Путь к логотипу по умолчанию
DEFAULT_LOGO_PATH = "dox_logo.png"

# Настройки по умолчанию
DEFAULT_DARKNESS = 60
DEFAULT_POSITION = "bottom-left"
DEFAULT_WATERMARK_SIZE = 0.2  # доля ширины картинки (20%)

# Хранилище настроек пользователей
user_settings = {}


def get_user_settings(user_id):
    """Получить настройки пользователя"""
    if user_id not in user_settings:
        user_settings[user_id] = {
            'darkness': DEFAULT_DARKNESS,
            'position': DEFAULT_POSITION,
            'watermark_size': DEFAULT_WATERMARK_SIZE,
            'last_image': None,
            'logo': None,  # bytes пользовательского логотипа
            'waiting_for_logo': False
        }
    s = user_settings[user_id]
    if 'watermark_size' not in s:
        s['watermark_size'] = DEFAULT_WATERMARK_SIZE
    return s


def get_user_logo(user_id):
    """Получить логотип пользователя (путь или BytesIO)"""
    settings = get_user_settings(user_id)
    if settings['logo']:
        return BytesIO(settings['logo'])
    else:
        return DEFAULT_LOGO_PATH


def get_logo_bytes(user_id):
    """Получить байты логотипа для отправки"""
    settings = get_user_settings(user_id)
    if settings['logo']:
        return settings['logo']
    else:
        with open(DEFAULT_LOGO_PATH, 'rb') as f:
            return f.read()


def process_image_with_settings(image_bytes, darkness, position, logo_source, logo_size_fraction=None):
    """Обработать изображение с заданными настройками"""
    if logo_size_fraction is None:
        logo_size_fraction = DEFAULT_WATERMARK_SIZE
    # Открываем изображение
    img = Image.open(BytesIO(image_bytes))
    
    # Конвертируем в RGBA
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    # Создаём и накладываем затемняющий слой (если darkness > 0)
    if darkness > 0:
        overlay = Image.new('RGBA', img.size, (0, 0, 0, int(255 * (darkness / 100))))
        img = Image.alpha_composite(img, overlay)
    
    # Открываем логотип
    if isinstance(logo_source, str):
        logo = Image.open(logo_source)
    else:
        logo = Image.open(logo_source)
    
    # Конвертируем логотип в RGBA
    if logo.mode != 'RGBA':
        logo = logo.convert('RGBA')
    
    # Рассчитываем размер логотипа (доля ширины картинки)
    logo_width = int(img.width * logo_size_fraction)
    logo_height = int(logo.height * (logo_width / logo.width))
    logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
    
    # Определяем позицию
    padding = 20
    positions = {
        'top-left': (padding, padding),
        'top-center': ((img.width - logo_width) // 2, padding),
        'top-right': (img.width - logo_width - padding, padding),
        'bottom-left': (padding, img.height - logo_height - padding),
        'bottom-center': ((img.width - logo_width) // 2, img.height - logo_height - padding),
        'bottom-right': (img.width - logo_width - padding, img.height - logo_height - padding)
    }
    
    logo_position = positions.get(position, positions['bottom-left'])
    
    # Накладываем логотип
    img.paste(logo, logo_position, logo)
    
    # Конвертируем в RGB для JPEG
    img = img.convert('RGB')
    
    # Сохраняем
    output = BytesIO()
    img.save(output, format='JPEG', quality=95)
    output.seek(0)
    
    return output


# ===== КЛАВИАТУРЫ =====

POSITION_LABELS = {
    "top-left": "сверху слева",
    "top-center": "сверху по центру",
    "top-right": "сверху справа",
    "bottom-left": "снизу слева",
    "bottom-center": "снизу по центру",
    "bottom-right": "снизу справа",
}


def get_position_label(position: str) -> str:
    """Красивое название позиции"""
    return POSITION_LABELS.get(position, position)


# Размер ватермарки: доля ширины картинки → подпись
WATERMARK_SIZE_FRACTIONS = {
    "size_10": 0.10,
    "size_15": 0.15,
    "size_20": 0.20,
    "size_25": 0.25,
    "size_30": 0.30,
}


def get_watermark_size_label(fraction: float) -> str:
    """Подпись размера ватермарки (процент от ширины)"""
    pct = int(round(fraction * 100))
    return f"{pct}%"


def get_main_menu_keyboard():
    """Главное меню"""
    keyboard = [
        [InlineKeyboardButton("🖼️ Выбор ватермарки", callback_data="menu_logo")],
        [InlineKeyboardButton("⚫ Процент затемнения", callback_data="choose_darkness")],
        [InlineKeyboardButton("ℹ️ Кратко о боте", callback_data="about_bot")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_logo_menu_keyboard():
    """Меню ватермарки (логотип + позиция + размер)"""
    keyboard = [
        [InlineKeyboardButton("📤 Загрузить свой логотип", callback_data="upload_logo")],
        [InlineKeyboardButton("🔄 Сбросить на дефолтный", callback_data="reset_logo")],
        [
            InlineKeyboardButton("10%", callback_data="wmsize_size_10"),
            InlineKeyboardButton("15%", callback_data="wmsize_size_15"),
            InlineKeyboardButton("20%", callback_data="wmsize_size_20"),
            InlineKeyboardButton("25%", callback_data="wmsize_size_25"),
            InlineKeyboardButton("30%", callback_data="wmsize_size_30"),
        ],
        [
            InlineKeyboardButton("↖️", callback_data="position_top-left"),
            InlineKeyboardButton("⬆️", callback_data="position_top-center"),
            InlineKeyboardButton("↗️", callback_data="position_top-right")
        ],
        [
            InlineKeyboardButton("↙️", callback_data="position_bottom-left"),
            InlineKeyboardButton("⬇️", callback_data="position_bottom-center"),
            InlineKeyboardButton("↘️", callback_data="position_bottom-right")
        ],
        [InlineKeyboardButton("« Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_darkness_keyboard():
    """Выбор затемнения"""
    keyboard = [
        [InlineKeyboardButton("☀️ Без затемнения", callback_data="darkness_0")],
        [
            InlineKeyboardButton("30%", callback_data="darkness_30"),
            InlineKeyboardButton("40%", callback_data="darkness_40"),
            InlineKeyboardButton("50%", callback_data="darkness_50")
        ],
        [
            InlineKeyboardButton("60%", callback_data="darkness_60"),
            InlineKeyboardButton("70%", callback_data="darkness_70"),
            InlineKeyboardButton("80%", callback_data="darkness_80")
        ],
        [
            InlineKeyboardButton("90%", callback_data="darkness_90"),
            InlineKeyboardButton("100%", callback_data="darkness_100")
        ],
        [InlineKeyboardButton("« Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_settings_keyboard():
    """Кнопки под обработанным фото"""
    keyboard = [
        [InlineKeyboardButton("🖼️ Выбор ватермарки", callback_data="menu_logo")],
        [InlineKeyboardButton("⚫ Процент затемнения", callback_data="choose_darkness")],
        [InlineKeyboardButton("ℹ️ Кратко о боте", callback_data="about_bot")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ===== ОБРАБОТЧИКИ =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user_id = update.effective_user.id
    settings = get_user_settings(user_id)
    
    text = (
        "👋 <b>Добро пожаловать в Dox Image Bot!</b>\n\n"
        "Отправь мне любую картинку, и я:\n"
        "• Затемню её (настраиваемый процент)\n"
        "• Добавлю твой логотип (настраиваемая позиция)\n\n"
        f"<b>Текущие настройки:</b>\n"
        f"Затемнение: {'Без затемнения' if settings['darkness'] == 0 else str(settings['darkness']) + '%'}\n"
        f"Позиция: {get_position_label(settings['position'])}\n"
        f"Размер ватермарки: {get_watermark_size_label(settings['watermark_size'])}\n"
        f"Логотип: {'пользовательский ✅' if settings['logo'] else 'Dox (дефолтный)'}\n\n"
        "Используй кнопки ниже для настройки 👇"
    )
    
    await update.message.reply_text(
        text,
        parse_mode='HTML',
        reply_markup=get_main_menu_keyboard()
    )


async def process_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фотографий"""
    user_id = update.effective_user.id
    settings = get_user_settings(user_id)
    
    try:
        # Проверяем: это загрузка логотипа или обработка фото?
        if settings.get('waiting_for_logo', False):
            # ===== ЗАГРУЗКА ЛОГОТИПА =====
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            logo_bytes = await file.download_as_bytearray()
            
            # Сохраняем логотип
            settings['logo'] = bytes(logo_bytes)
            settings['waiting_for_logo'] = False
            
            # Отправляем подтверждение
            await update.message.reply_photo(
                photo=BytesIO(settings['logo']),
                caption="✅ <b>Логотип загружен!</b>\n\nТеперь отправь фото для обработки.",
                parse_mode='HTML',
                reply_markup=get_main_menu_keyboard()
            )
            
            logger.info(f"Пользователь {user_id} загрузил логотип")
            return
        
        # ===== ОБРАБОТКА ФОТО =====
        photo = update.message.photo[-1]
        
        # Уведомляем
        msg = await update.message.reply_text("⏳ Обрабатываю...")
        
        # Скачиваем
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        
        # Сохраняем оригинал
        settings['last_image'] = bytes(photo_bytes)
        
        # Обрабатываем
        logo_source = get_user_logo(user_id)
        output = process_image_with_settings(
            photo_bytes,
            settings['darkness'],
            settings['position'],
            logo_source,
            logo_size_fraction=settings['watermark_size']
        )
        
        # Удаляем "Обрабатываю..."
        await msg.delete()
        
        # Отправляем результат
        caption = (
            f"✅ <b>Готово!</b>\n"
            f"Затемнение: {'Без затемнения' if settings['darkness'] == 0 else str(settings['darkness']) + '%'}\n"
            f"Позиция: {get_position_label(settings['position'])}\n"
            f"Размер ватермарки: {get_watermark_size_label(settings['watermark_size'])}\n"
            f"Логотип: {'пользовательский ✅' if settings['logo'] else 'Dox (дефолтный)'}"
        )
        
        await update.message.reply_photo(
            photo=output,
            caption=caption,
            parse_mode='HTML',
            reply_markup=get_settings_keyboard()
        )
        
        logger.info(f"Обработано фото от пользователя {user_id}")
        
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка обработки: {str(e)}")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки"""
    query = update.callback_query
    user_id = update.effective_user.id
    settings = get_user_settings(user_id)
    data = query.data
    
    try:
        await query.answer()
        
        # ===== ГЛАВНОЕ МЕНЮ =====
        if data == "back_to_main":
            text = (
                f"<b>Текущие настройки:</b>\n"
                f"Затемнение: {'Без затемнения' if settings['darkness'] == 0 else str(settings['darkness']) + '%'}\n"
                f"Позиция: {get_position_label(settings['position'])}\n"
                f"Размер ватермарки: {get_watermark_size_label(settings['watermark_size'])}\n"
                f"Логотип: {'пользовательский ✅' if settings['logo'] else 'Dox (дефолтный)'}\n\n"
                "Выбери опцию:"
            )
            
            # Удаляем старое сообщение и отправляем новое
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=text,
                parse_mode='HTML',
                reply_markup=get_main_menu_keyboard()
            )
        
        # ===== МЕНЮ ЛОГОТИПА =====
        elif data == "menu_logo":
            logo_bytes = get_logo_bytes(user_id)
            
            caption = (
                f"🖼️ <b>Меню ватермарки</b>\n\n"
                f"{'Пользовательский ✅' if settings['logo'] else 'Dox (дефолтный)'}\n"
                f"Позиция: {get_position_label(settings['position'])}\n"
                f"Размер: {get_watermark_size_label(settings['watermark_size'])}\n\n"
                "Выбери логотип, размер или позицию:"
            )
            
            await query.message.delete()
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=BytesIO(logo_bytes),
                caption=caption,
                parse_mode='HTML',
                reply_markup=get_logo_menu_keyboard()
            )
        
        # ===== ЗАГРУЗКА ЛОГОТИПА =====
        elif data == "upload_logo":
            settings['waiting_for_logo'] = True
            
            text = (
                "📤 <b>Загрузка логотипа</b>\n\n"
                "Отправь мне изображение логотипа.\n\n"
                "<i>Рекомендации:</i>\n"
                "• PNG с прозрачным фоном\n"
                "• Квадратный формат\n"
                "• Хорошее качество"
            )
            
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Отмена", callback_data="cancel_upload")]])
            )
        
        # ===== ОТМЕНА ЗАГРУЗКИ =====
        elif data == "cancel_upload":
            settings['waiting_for_logo'] = False
            
            logo_bytes = get_logo_bytes(user_id)
            caption = (
                f"🖼️ <b>Меню ватермарки</b>\n\n"
                f"{'Пользовательский ✅' if settings['logo'] else 'Dox (дефолтный)'}\n"
                f"Позиция: {get_position_label(settings['position'])}\n"
                f"Размер: {get_watermark_size_label(settings['watermark_size'])}"
            )
            
            await query.message.delete()
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=BytesIO(logo_bytes),
                caption=caption,
                parse_mode='HTML',
                reply_markup=get_logo_menu_keyboard()
            )
        
        # ===== СБРОС ЛОГОТИПА =====
        elif data == "reset_logo":
            settings['logo'] = None
            
            with open(DEFAULT_LOGO_PATH, 'rb') as f:
                logo_bytes = f.read()
            
            caption = (
                "🖼️ <b>Меню ватермарки</b>\n\n"
                "Dox (дефолтный) ✅\n"
                f"Позиция: {get_position_label(settings['position'])}\n"
                f"Размер: {get_watermark_size_label(settings['watermark_size'])}"
            )
            
            await query.message.delete()
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=BytesIO(logo_bytes),
                caption=caption,
                parse_mode='HTML',
                reply_markup=get_logo_menu_keyboard()
            )
        
        # ===== ВЫБОР ЗАТЕМНЕНИЯ =====
        elif data == "choose_darkness":
            text = f"⚫ <b>Выбери процент затемнения:</b>\n\nТекущий: {'Без затемнения' if settings['darkness'] == 0 else str(settings['darkness']) + '%'}"
            
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=text,
                parse_mode='HTML',
                reply_markup=get_darkness_keyboard()
            )
        
        # ===== КРАТКОЕ ОПИСАНИЕ =====
        elif data == "about_bot":
            text = (
                "ℹ️ <b>Что делает бот:</b>\n\n"
                "• Добавляет ватермарку (твой логотип или дефолтный)\n"
                "• Размер ватермарки: 10%, 15%, 20%, 25% или 30% ширины фото\n"
                "• Позиция: 6 вариантов (верх/низ, лево/центр/право)\n"
                "• Затемнение: 0–100% (или без затемнения)\n\n"
                "Отправь фото — бот вернёт результат."
            )

            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=text,
                parse_mode='HTML',
                reply_markup=get_main_menu_keyboard()
            )
        
        # ===== ИЗМЕНЕНИЕ ЗАТЕМНЕНИЯ =====
        elif data.startswith("darkness_"):
            darkness = int(data.split("_")[1])
            settings['darkness'] = darkness
            
            if settings['last_image']:
                # Пересоздаём фото
                logo_source = get_user_logo(user_id)
                output = process_image_with_settings(
                    settings['last_image'],
                    settings['darkness'],
                    settings['position'],
                    logo_source,
                    logo_size_fraction=settings['watermark_size']
                )
                
                caption = (
                    f"✅ <b>Затемнение: {'Без затемнения' if darkness == 0 else str(darkness) + '%'}</b>\n"
                    f"Позиция: {get_position_label(settings['position'])}\n"
                    f"Размер ватермарки: {get_watermark_size_label(settings['watermark_size'])}\n"
                    f"Логотип: {'пользовательский ✅' if settings['logo'] else 'Dox (дефолтный)'}"
                )
                
                await query.message.delete()
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=output,
                    caption=caption,
                    parse_mode='HTML',
                    reply_markup=get_settings_keyboard()
                )
            else:
                # Просто обновляем настройки
                text = (
                    f"✅ Затемнение: {'Без затемнения' if darkness == 0 else str(darkness) + '%'}\n\n"
                    "Отправь фото для обработки!"
                )
                
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=text,
                    reply_markup=get_main_menu_keyboard()
                )
        
        # ===== ИЗМЕНЕНИЕ РАЗМЕРА ВАТЕРМАРКИ =====
        elif data.startswith("wmsize_"):
            key = data.replace("wmsize_", "", 1)
            if key in WATERMARK_SIZE_FRACTIONS:
                settings['watermark_size'] = WATERMARK_SIZE_FRACTIONS[key]
                size_label = get_watermark_size_label(settings['watermark_size'])
                if settings['last_image']:
                    logo_source = get_user_logo(user_id)
                    output = process_image_with_settings(
                        settings['last_image'],
                        settings['darkness'],
                        settings['position'],
                        logo_source,
                        logo_size_fraction=settings['watermark_size']
                    )
                    caption = (
                        f"✅ <b>Размер ватермарки: {size_label}</b>\n"
                        f"Затемнение: {'Без затемнения' if settings['darkness'] == 0 else str(settings['darkness']) + '%'}\n"
                        f"Позиция: {get_position_label(settings['position'])}\n"
                        f"Логотип: {'пользовательский ✅' if settings['logo'] else 'Dox (дефолтный)'}"
                    )
                    await query.message.delete()
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=output,
                        caption=caption,
                        parse_mode='HTML',
                        reply_markup=get_settings_keyboard()
                    )
                elif query.message.photo:
                    logo_bytes = get_logo_bytes(user_id)
                    caption = (
                        f"🖼️ <b>Меню ватермарки</b>\n\n"
                        f"{'Пользовательский ✅' if settings['logo'] else 'Dox (дефолтный)'}\n"
                        f"Позиция: {get_position_label(settings['position'])}\n"
                        f"Размер: {get_watermark_size_label(settings['watermark_size'])}"
                    )
                    await query.message.delete()
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=BytesIO(logo_bytes),
                        caption=caption,
                        parse_mode='HTML',
                        reply_markup=get_logo_menu_keyboard()
                    )
                else:
                    text = (
                        f"✅ Размер ватермарки: {size_label}\n\n"
                        "Отправь фото для обработки!"
                    )
                    await query.message.delete()
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=text,
                        reply_markup=get_main_menu_keyboard()
                    )
        
        # ===== ИЗМЕНЕНИЕ ПОЗИЦИИ =====
        elif data.startswith("position_"):
            position = data.split("_", 1)[1]
            settings['position'] = position
            
            if settings['last_image']:
                # Пересоздаём фото
                logo_source = get_user_logo(user_id)
                output = process_image_with_settings(
                    settings['last_image'],
                    settings['darkness'],
                    settings['position'],
                    logo_source,
                    logo_size_fraction=settings['watermark_size']
                )
                
                caption = (
                    f"✅ <b>Позиция: {get_position_label(position)}</b>\n"
                    f"Затемнение: {'Без затемнения' if settings['darkness'] == 0 else str(settings['darkness']) + '%'}\n"
                    f"Размер ватермарки: {get_watermark_size_label(settings['watermark_size'])}\n"
                    f"Логотип: {'пользовательский ✅' if settings['logo'] else 'Dox (дефолтный)'}"
                )
                
                await query.message.delete()
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=output,
                    caption=caption,
                    parse_mode='HTML',
                    reply_markup=get_settings_keyboard()
                )
            else:
                # Просто обновляем настройки
                text = (
                    f"✅ Позиция изменена на {get_position_label(position)}\n\n"
                    "Отправь фото для обработки!"
                )

                if query.message.photo:
                    logo_bytes = get_logo_bytes(user_id)
                    caption = (
                        f"🖼️ <b>Меню ватермарки</b>\n\n"
                        f"{'Пользовательский ✅' if settings['logo'] else 'Dox (дефолтный)'}\n"
                        f"Позиция: {get_position_label(settings['position'])}\n"
                        f"Размер: {get_watermark_size_label(settings['watermark_size'])}"
                    )
                    await query.message.delete()
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=BytesIO(logo_bytes),
                        caption=caption,
                        parse_mode='HTML',
                        reply_markup=get_logo_menu_keyboard()
                    )
                else:
                    await query.message.delete()
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=text,
                        reply_markup=get_main_menu_keyboard()
                    )
    
    except Exception as e:
        logger.error(f"Ошибка callback: {e}", exc_info=True)
        try:
            await query.answer("❌ Ошибка. Попробуй /start", show_alert=True)
        except:
            pass


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Глобальный обработчик ошибок"""
    logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)


async def post_init(application: Application):
    """Установка команд бота"""
    commands = [
        BotCommand("start", "Главное меню и настройки")
    ]
    await application.bot.set_my_commands(commands)
    logger.info("✅ Команды бота установлены")


def main():
    """Запуск бота"""
    if not os.path.exists(DEFAULT_LOGO_PATH):
        logger.error(f"ОШИБКА: Файл {DEFAULT_LOGO_PATH} не найден!")
        return
    
    logger.info("🚀 Запуск Dox Image Bot v2.3 STABLE...")
    
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, process_photo))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_error_handler(error_handler)
    
    logger.info("✅ Бот запущен! Готов к работе...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
