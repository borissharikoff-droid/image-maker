#!/usr/bin/env python3
"""
Neopass Image Bot
Затемняет изображения на 60% и добавляет логотип Neopass в левый нижний угол
"""

import os
import logging
from io import BytesIO
from PIL import Image, ImageDraw
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен бота из environment variable
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8578752100:AAEmpvdVrkl-n8qgocT1uYjSTWc8y49J3GU")

# Путь к логотипу
LOGO_PATH = "neopass_logo.jpg"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "👋 Привет! Я Neopass Image Bot.\n\n"
        "Отправь мне картинку, и я:\n"
        "• Затемню её на 60%\n"
        "• Добавлю логотип Neopass в левый нижний угол\n\n"
        "Просто кинь мне фото!"
    )


async def process_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик фотографий"""
    try:
        # Получаем фото максимального качества
        photo = update.message.photo[-1]
        
        # Уведомляем пользователя
        await update.message.reply_text("⏳ Обрабатываю...")
        
        # Скачиваем фото
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        
        # Открываем изображение
        img = Image.open(BytesIO(photo_bytes))
        
        # Конвертируем в RGBA если нужно
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        # Создаём затемняющий слой (черный с 60% прозрачностью)
        overlay = Image.new('RGBA', img.size, (0, 0, 0, int(255 * 0.6)))
        
        # Накладываем затемнение
        img = Image.alpha_composite(img, overlay)
        
        # Открываем логотип
        if not os.path.exists(LOGO_PATH):
            await update.message.reply_text("❌ Логотип не найден! Положи neopass_logo.jpg рядом с ботом.")
            return
            
        logo = Image.open(LOGO_PATH)
        
        # Конвертируем логотип в RGBA
        if logo.mode != 'RGBA':
            logo = logo.convert('RGBA')
        
        # Рассчитываем размер логотипа (20% ширины изображения)
        logo_width = int(img.width * 0.2)
        logo_height = int(logo.height * (logo_width / logo.width))
        logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
        
        # Позиция логотипа в левом нижнем углу (отступ 20px)
        position = (20, img.height - logo_height - 20)
        
        # Накладываем логотип
        img.paste(logo, position, logo)
        
        # Конвертируем обратно в RGB для сохранения в JPEG
        img = img.convert('RGB')
        
        # Сохраняем в BytesIO
        output = BytesIO()
        img.save(output, format='JPEG', quality=95)
        output.seek(0)
        
        # Отправляем результат
        await update.message.reply_photo(
            photo=output,
            caption="✅ Готово! Изображение затемнено на 60% с логотипом Neopass"
        )
        
        logger.info(f"Обработано фото от пользователя {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}")
        await update.message.reply_text(f"❌ Ошибка обработки: {str(e)}")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Update {update} caused error {context.error}")


def main():
    """Запуск бота"""
    # Проверяем наличие логотипа
    if not os.path.exists(LOGO_PATH):
        logger.error(f"ОШИБКА: Файл {LOGO_PATH} не найден!")
        logger.error("Положи файл neopass_logo.jpg в ту же папку, где находится бот.")
        return
    
    logger.info("🚀 Запуск Neopass Image Bot...")
    
    # Создаём приложение
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрируем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, process_photo))
    app.add_error_handler(error_handler)
    
    # Запускаем бота
    logger.info("✅ Бот запущен! Жду фотографии...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
