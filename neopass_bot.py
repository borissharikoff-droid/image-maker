#!/usr/bin/env python3
"""
Neopass Image Bot v2.0
Затемняет изображения и добавляет логотип Neopass с настройками
"""

import os
import logging
from io import BytesIO
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен бота из environment variable
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8578752100:AAEmpvdVrkl-n8qgocT1uYjSTWc8y49J3GU")

# Путь к логотипу (PNG)
LOGO_PATH = "neopass_logo.png"

# Настройки по умолчанию
DEFAULT_DARKNESS = 60
DEFAULT_POSITION = "bottom-left"

# Хранилище настроек пользователей {user_id: {darkness: int, position: str, last_image: bytes}}
user_settings = {}


def get_user_settings(user_id):
    """Получить настройки пользователя"""
    if user_id not in user_settings:
        user_settings[user_id] = {
            'darkness': DEFAULT_DARKNESS,
            'position': DEFAULT_POSITION,
            'last_image': None
        }
    return user_settings[user_id]


def process_image_with_settings(image_bytes, darkness, position):
    """Обработать изображение с заданными настройками"""
    # Открываем изображение
    img = Image.open(BytesIO(image_bytes))
    
    # Конвертируем в RGBA если нужно
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    # Создаём затемняющий слой
    overlay = Image.new('RGBA', img.size, (0, 0, 0, int(255 * (darkness / 100))))
    
    # Накладываем затемнение
    img = Image.alpha_composite(img, overlay)
    
    # Открываем логотип
    if not os.path.exists(LOGO_PATH):
        raise FileNotFoundError(f"Логотип {LOGO_PATH} не найден!")
        
    logo = Image.open(LOGO_PATH)
    
    # Конвертируем логотип в RGBA
    if logo.mode != 'RGBA':
        logo = logo.convert('RGBA')
    
    # Рассчитываем размер логотипа (20% ширины изображения)
    logo_width = int(img.width * 0.2)
    logo_height = int(logo.height * (logo_width / logo.width))
    logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
    
    # Определяем позицию логотипа
    padding = 20
    positions = {
        'top-left': (padding, padding),
        'top-right': (img.width - logo_width - padding, padding),
        'bottom-left': (padding, img.height - logo_height - padding),
        'bottom-right': (img.width - logo_width - padding, img.height - logo_height - padding)
    }
    
    logo_position = positions.get(position, positions['bottom-left'])
    
    # Накладываем логотип
    img.paste(logo, logo_position, logo)
    
    # Конвертируем обратно в RGB для сохранения в JPEG
    img = img.convert('RGB')
    
    # Сохраняем в BytesIO
    output = BytesIO()
    img.save(output, format='JPEG', quality=95)
    output.seek(0)
    
    return output


def get_settings_keyboard():
    """Клавиатура с настройками"""
    keyboard = [
        [InlineKeyboardButton("⚫ Выбрать процент затемнения", callback_data="choose_darkness")],
        [InlineKeyboardButton("📍 Расположение лого", callback_data="choose_position")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_darkness_keyboard():
    """Клавиатура выбора затемнения"""
    keyboard = [
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
        [InlineKeyboardButton("« Назад", callback_data="back_to_settings")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_position_keyboard():
    """Клавиатура выбора позиции"""
    keyboard = [
        [
            InlineKeyboardButton("↖️ Сверху слева", callback_data="position_top-left"),
            InlineKeyboardButton("↗️ Сверху справа", callback_data="position_top-right")
        ],
        [
            InlineKeyboardButton("↙️ Снизу слева", callback_data="position_bottom-left"),
            InlineKeyboardButton("↘️ Снизу справа", callback_data="position_bottom-right")
        ],
        [InlineKeyboardButton("« Назад", callback_data="back_to_settings")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "👋 Привет! Я Neopass Image Bot v2.0.\n\n"
        "Отправь мне картинку, и я:\n"
        "• Затемню её (настраиваемый %)\n"
        "• Добавлю логотип Neopass (настраиваемая позиция)\n\n"
        "После обработки ты сможешь изменить настройки и пересоздать фото!"
    )


async def process_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик фотографий"""
    try:
        user_id = update.effective_user.id
        settings = get_user_settings(user_id)
        
        # Получаем фото максимального качества
        photo = update.message.photo[-1]
        
        # Уведомляем пользователя
        msg = await update.message.reply_text("⏳ Обрабатываю...")
        
        # Скачиваем фото
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        
        # Сохраняем оригинал в настройках пользователя
        settings['last_image'] = bytes(photo_bytes)
        
        # Обрабатываем
        output = process_image_with_settings(
            photo_bytes,
            settings['darkness'],
            settings['position']
        )
        
        # Удаляем сообщение "Обрабатываю..."
        await msg.delete()
        
        # Отправляем результат с кнопками
        caption = (
            f"✅ Готово!\n"
            f"Затемнение: {settings['darkness']}%\n"
            f"Позиция лого: {settings['position']}"
        )
        
        await update.message.reply_photo(
            photo=output,
            caption=caption,
            reply_markup=get_settings_keyboard()
        )
        
        logger.info(f"Обработано фото от пользователя {user_id}")
        
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}")
        await update.message.reply_text(f"❌ Ошибка обработки: {str(e)}")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    settings = get_user_settings(user_id)
    
    data = query.data
    
    # Меню выбора затемнения
    if data == "choose_darkness":
        await query.edit_message_caption(
            caption=f"Выбери процент затемнения:\nТекущий: {settings['darkness']}%",
            reply_markup=get_darkness_keyboard()
        )
    
    # Меню выбора позиции
    elif data == "choose_position":
        await query.edit_message_caption(
            caption=f"Выбери расположение логотипа:\nТекущее: {settings['position']}",
            reply_markup=get_position_keyboard()
        )
    
    # Назад к настройкам
    elif data == "back_to_settings":
        caption = (
            f"✅ Текущие настройки:\n"
            f"Затемнение: {settings['darkness']}%\n"
            f"Позиция лого: {settings['position']}"
        )
        await query.edit_message_caption(
            caption=caption,
            reply_markup=get_settings_keyboard()
        )
    
    # Выбор затемнения
    elif data.startswith("darkness_"):
        darkness = int(data.split("_")[1])
        settings['darkness'] = darkness
        
        # Пересоздаём изображение
        if settings['last_image']:
            try:
                output = process_image_with_settings(
                    settings['last_image'],
                    settings['darkness'],
                    settings['position']
                )
                
                caption = (
                    f"✅ Затемнение изменено на {darkness}%\n"
                    f"Позиция лого: {settings['position']}"
                )
                
                # Удаляем старое фото
                await query.message.delete()
                
                # Отправляем новое
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=output,
                    caption=caption,
                    reply_markup=get_settings_keyboard()
                )
            except Exception as e:
                await query.message.reply_text(f"❌ Ошибка: {str(e)}")
    
    # Выбор позиции
    elif data.startswith("position_"):
        position = data.split("_", 1)[1]
        settings['position'] = position
        
        # Пересоздаём изображение
        if settings['last_image']:
            try:
                output = process_image_with_settings(
                    settings['last_image'],
                    settings['darkness'],
                    settings['position']
                )
                
                caption = (
                    f"✅ Позиция логотипа изменена\n"
                    f"Затемнение: {settings['darkness']}%\n"
                    f"Позиция: {position}"
                )
                
                # Удаляем старое фото
                await query.message.delete()
                
                # Отправляем новое
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=output,
                    caption=caption,
                    reply_markup=get_settings_keyboard()
                )
            except Exception as e:
                await query.message.reply_text(f"❌ Ошибка: {str(e)}")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Update {update} caused error {context.error}")


def main():
    """Запуск бота"""
    # Проверяем наличие логотипа
    if not os.path.exists(LOGO_PATH):
        logger.error(f"ОШИБКА: Файл {LOGO_PATH} не найден!")
        logger.error(f"Положи файл {LOGO_PATH} в ту же папку, где находится бот.")
        return
    
    logger.info("🚀 Запуск Neopass Image Bot v2.0...")
    
    # Создаём приложение
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрируем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, process_photo))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_error_handler(error_handler)
    
    # Запускаем бота
    logger.info("✅ Бот запущен! Жду фотографии...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
