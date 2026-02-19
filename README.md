# Image Bot 🤖

Telegram бот для обработки изображений с логотипом.

## Функционал

- Затемнение изображений на 60% (черный overlay)
- Наложение логотипа Neopass в левый нижний угол
- Автоматическая обработка при отправке фото

## Deploy на Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app)

### Environment Variables

Установи в Railway:
- `BOT_TOKEN` - токен от @BotFather

## Локальный запуск

```bash
pip install -r requirements.txt
python neopass_bot.py
```

## Stack

- Python 3.11+
- python-telegram-bot 21.0
- Pillow 10.2.0
