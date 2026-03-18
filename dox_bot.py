#!/usr/bin/env python3
"""
Dox Image Bot v3.0
Затемняет изображения и добавляет логотип.
Поддерживает несколько именованных профилей ватермарки.
"""

import os
import asyncio
import logging
from io import BytesIO
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8578752100:AAEmpvdVrkl-n8qgocT1uYjSTWc8y49J3GU")
DEFAULT_LOGO_PATH = "dox_logo.png"
DEFAULT_DARKNESS = 60
DEFAULT_POSITION = "bottom-left"
DEFAULT_WATERMARK_SIZE = 0.2

user_settings = {}

# Буфер для медиагрупп (несколько фото сразу)
# ключ: media_group_id → {'user_id', 'chat_id', 'file_ids': [], 'task'}
media_group_buffer: dict = {}


# ===== НАСТРОЙКИ =====

def get_user_settings(user_id):
    if user_id not in user_settings:
        user_settings[user_id] = {
            'darkness': DEFAULT_DARKNESS,
            'position': DEFAULT_POSITION,
            'watermark_size': DEFAULT_WATERMARK_SIZE,
            'last_image': None,
            'logo': None,
            # Профили
            'profiles': {},             # pid → {name, logo, position, size}
            'active_profile_id': None,  # None = дефолтный Dox лого
            'next_profile_id': 1,
            # Состояния
            'waiting_for_size': False,
            'waiting_for_profile_logo': False,  # ждём лого для создания/замены профиля
            'waiting_for_profile_name': False,  # ждём название нового профиля
            'pending_profile_logo': None,        # байты лого до присвоения имени
            'editing_profile_id': None,          # id профиля при замене лого
        }
    s = user_settings[user_id]
    # Миграция старых настроек
    for key, default in [
        ('watermark_size', DEFAULT_WATERMARK_SIZE),
        ('waiting_for_size', False),
        ('profiles', {}),
        ('active_profile_id', None),
        ('next_profile_id', 1),
        ('waiting_for_profile_logo', False),
        ('waiting_for_profile_name', False),
        ('pending_profile_logo', None),
        ('editing_profile_id', None),
    ]:
        if key not in s:
            s[key] = default
    return s


# ===== ПРОФИЛИ =====

def get_active_profile(user_id):
    """Вернуть активный профиль или None"""
    s = get_user_settings(user_id)
    pid = s['active_profile_id']
    if pid and pid in s['profiles']:
        return s['profiles'][pid]
    return None


def activate_profile(user_id, profile_id):
    """Загрузить данные профиля в текущие настройки"""
    s = get_user_settings(user_id)
    if profile_id not in s['profiles']:
        return
    p = s['profiles'][profile_id]
    s['active_profile_id'] = profile_id
    s['logo'] = p['logo']
    s['position'] = p['position']
    s['watermark_size'] = p['size']


def sync_active_profile(user_id):
    """Сохранить текущие position/size/logo обратно в активный профиль"""
    s = get_user_settings(user_id)
    pid = s['active_profile_id']
    if pid and pid in s['profiles']:
        s['profiles'][pid]['position'] = s['position']
        s['profiles'][pid]['size'] = s['watermark_size']
        s['profiles'][pid]['logo'] = s['logo']


def use_default_logo(user_id):
    """Переключиться на дефолтный Dox логотип"""
    s = get_user_settings(user_id)
    s['active_profile_id'] = None
    s['logo'] = None


# ===== ЛОГО И ИЗОБРАЖЕНИЕ =====

def get_user_logo(user_id):
    s = get_user_settings(user_id)
    if s['logo']:
        return BytesIO(s['logo'])
    return DEFAULT_LOGO_PATH


def get_logo_bytes(user_id):
    s = get_user_settings(user_id)
    if s['logo']:
        return s['logo']
    with open(DEFAULT_LOGO_PATH, 'rb') as f:
        return f.read()


def process_image_with_settings(image_bytes, darkness, position, logo_source, logo_size_fraction=None):
    if logo_size_fraction is None:
        logo_size_fraction = DEFAULT_WATERMARK_SIZE

    img = Image.open(BytesIO(image_bytes))
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    if darkness > 0:
        overlay = Image.new('RGBA', img.size, (0, 0, 0, int(255 * (darkness / 100))))
        img = Image.alpha_composite(img, overlay)

    if logo_size_fraction > 0:
        logo = Image.open(logo_source)
        if logo.mode != 'RGBA':
            logo = logo.convert('RGBA')
        logo_width = int(img.width * logo_size_fraction)
        logo_height = int(logo.height * (logo_width / logo.width))
        logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
        padding = 20
        positions = {
            'top-left':      (padding, padding),
            'top-center':    ((img.width - logo_width) // 2, padding),
            'top-right':     (img.width - logo_width - padding, padding),
            'bottom-left':   (padding, img.height - logo_height - padding),
            'bottom-center': ((img.width - logo_width) // 2, img.height - logo_height - padding),
            'bottom-right':  (img.width - logo_width - padding, img.height - logo_height - padding),
        }
        img.paste(logo, positions.get(position, positions['bottom-left']), logo)

    img = img.convert('RGB')
    output = BytesIO()
    img.save(output, format='JPEG', quality=95)
    output.seek(0)
    return output


# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

POSITION_LABELS = {
    "top-left":      "сверху слева",
    "top-center":    "сверху по центру",
    "top-right":     "сверху справа",
    "bottom-left":   "снизу слева",
    "bottom-center": "снизу по центру",
    "bottom-right":  "снизу справа",
}


def get_position_label(position):
    return POSITION_LABELS.get(position, position)


def get_watermark_size_label(fraction):
    return f"{int(round(fraction * 100))}%"


def get_active_label(user_id):
    """Название активного лого/профиля"""
    s = get_user_settings(user_id)
    pid = s['active_profile_id']
    if pid and pid in s['profiles']:
        return f"📁 {s['profiles'][pid]['name']}"
    return "Dox (дефолтный)"


def make_status_caption(user_id, title="✅ <b>Готово!</b>"):
    s = get_user_settings(user_id)
    dark = 'Без затемнения' if s['darkness'] == 0 else f"{s['darkness']}%"
    return (
        f"{title}\n"
        f"Профиль: {get_active_label(user_id)}\n"
        f"Затемнение: {dark}\n"
        f"Позиция: {get_position_label(s['position'])}\n"
        f"Размер ватермарки: {get_watermark_size_label(s['watermark_size'])}"
    )


# ===== КЛАВИАТУРЫ =====

def get_main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Настройки ватермарки", callback_data="menu_logo")],
        [InlineKeyboardButton("⚫ Процент затемнения",    callback_data="choose_darkness")],
        [InlineKeyboardButton("ℹ️ Кратко о боте",         callback_data="about_bot")],
    ])


def get_settings_keyboard():
    return get_main_menu_keyboard()


def get_profiles_keyboard(user_id):
    """Список профилей"""
    s = get_user_settings(user_id)
    rows = []

    # Дефолтный
    is_default = s['active_profile_id'] is None
    rows.append([InlineKeyboardButton(
        f"{'✅ ' if is_default else ''}Dox (дефолтный)",
        callback_data="profile_use_default"
    )])

    # Пользовательские профили
    for pid, p in s['profiles'].items():
        is_active = s['active_profile_id'] == pid
        rows.append([InlineKeyboardButton(
            f"{'✅ ' if is_active else '📁 '}{p['name']}",
            callback_data=f"profile_select_{pid}"
        )])

    rows.append([InlineKeyboardButton("➕ Создать профиль", callback_data="profile_new")])
    rows.append([InlineKeyboardButton("« Назад",            callback_data="back_to_main")])
    return InlineKeyboardMarkup(rows)


def get_profile_settings_keyboard(profile_id, current_size_pct):
    """Настройки активного профиля"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("−10%", callback_data="wmsize_minus10"),
            InlineKeyboardButton("−5%",  callback_data="wmsize_minus5"),
            InlineKeyboardButton(f"◾ {current_size_pct}%", callback_data="wmsize_noop"),
            InlineKeyboardButton("+5%",  callback_data="wmsize_plus5"),
            InlineKeyboardButton("+10%", callback_data="wmsize_plus10"),
        ],
        [InlineKeyboardButton("✏️ Ввести размер вручную", callback_data="wmsize_input")],
        [
            InlineKeyboardButton("↖️", callback_data="position_top-left"),
            InlineKeyboardButton("⬆️", callback_data="position_top-center"),
            InlineKeyboardButton("↗️", callback_data="position_top-right"),
        ],
        [
            InlineKeyboardButton("↙️", callback_data="position_bottom-left"),
            InlineKeyboardButton("⬇️", callback_data="position_bottom-center"),
            InlineKeyboardButton("↘️", callback_data="position_bottom-right"),
        ],
        [
            InlineKeyboardButton("📤 Сменить лого",    callback_data=f"profile_change_logo_{profile_id}"),
            InlineKeyboardButton("✏️ Переименовать",   callback_data=f"profile_rename_{profile_id}"),
            InlineKeyboardButton("🗑 Удалить",         callback_data=f"profile_delete_{profile_id}"),
        ],
        [InlineKeyboardButton("« К профилям", callback_data="menu_logo")],
    ])


def get_darkness_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("☀️ Без затемнения", callback_data="darkness_0")],
        [
            InlineKeyboardButton("30%", callback_data="darkness_30"),
            InlineKeyboardButton("40%", callback_data="darkness_40"),
            InlineKeyboardButton("50%", callback_data="darkness_50"),
        ],
        [
            InlineKeyboardButton("60%", callback_data="darkness_60"),
            InlineKeyboardButton("70%", callback_data="darkness_70"),
            InlineKeyboardButton("80%", callback_data="darkness_80"),
        ],
        [
            InlineKeyboardButton("90%",  callback_data="darkness_90"),
            InlineKeyboardButton("100%", callback_data="darkness_100"),
        ],
        [InlineKeyboardButton("« Назад", callback_data="back_to_main")],
    ])


# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ЭКРАНОВ =====

async def send_profiles_screen(chat_id, context, user_id, delete_msg=None):
    s = get_user_settings(user_id)
    text = (
        f"⚙️ <b>Настройки ватермарки</b>\n\n"
        f"Активный профиль: <b>{get_active_label(user_id)}</b>\n"
        f"Позиция: {get_position_label(s['position'])}\n"
        f"Размер: {get_watermark_size_label(s['watermark_size'])}\n\n"
        f"Профилей: {len(s['profiles'])}\n\n"
        "Выбери профиль или создай новый:"
    )
    if delete_msg:
        await delete_msg.delete()
    await context.bot.send_message(
        chat_id=chat_id, text=text, parse_mode='HTML',
        reply_markup=get_profiles_keyboard(user_id)
    )


async def send_profile_settings_screen(chat_id, context, user_id, profile_id, delete_msg=None):
    s = get_user_settings(user_id)
    p = s['profiles'].get(profile_id)
    if not p:
        return
    current_pct = int(round(s['watermark_size'] * 100))
    caption = (
        f"📁 <b>{p['name']}</b>\n\n"
        f"Размер: {get_watermark_size_label(s['watermark_size'])}\n"
        f"Позиция: {get_position_label(s['position'])}"
    )
    logo_bytes = s['logo'] if s['logo'] else open(DEFAULT_LOGO_PATH, 'rb').read()
    if delete_msg:
        await delete_msg.delete()
    await context.bot.send_photo(
        chat_id=chat_id,
        photo=BytesIO(logo_bytes),
        caption=caption,
        parse_mode='HTML',
        reply_markup=get_profile_settings_keyboard(profile_id, current_pct)
    )


# ===== ОБРАБОТЧИКИ =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s = get_user_settings(user_id)
    dark = 'Без затемнения' if s['darkness'] == 0 else f"{s['darkness']}%"
    text = (
        "👋 <b>Добро пожаловать в Dox Image Bot!</b>\n\n"
        "Отправь картинку — я затемню её и добавлю ватермарку.\n\n"
        f"<b>Текущие настройки:</b>\n"
        f"Профиль: {get_active_label(user_id)}\n"
        f"Затемнение: {dark}\n"
        f"Позиция: {get_position_label(s['position'])}\n"
        f"Размер ватермарки: {get_watermark_size_label(s['watermark_size'])}\n\n"
        "Используй кнопки ниже 👇"
    )
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=get_main_menu_keyboard())


async def process_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Текстовые сообщения: ввод размера или названия профиля"""
    user_id = update.effective_user.id
    s = get_user_settings(user_id)

    # ── Ввод названия нового профиля ──
    if s.get('waiting_for_profile_name'):
        name = update.message.text.strip()
        if not name:
            await update.message.reply_text("❌ Название не может быть пустым. Введи снова:")
            return

        s['waiting_for_profile_name'] = False
        pid = str(s['next_profile_id'])
        s['next_profile_id'] += 1

        # Если редактируем существующий профиль (замена лого)
        editing_id = s.get('editing_profile_id')
        if editing_id and editing_id in s['profiles']:
            s['profiles'][editing_id]['logo'] = s['pending_profile_logo']
            s['profiles'][editing_id]['name'] = name
            s['pending_profile_logo'] = None
            s['editing_profile_id'] = None
            activate_profile(user_id, editing_id)
            await send_profile_settings_screen(update.message.chat_id, context, user_id, editing_id)
        else:
            # Новый профиль
            s['profiles'][pid] = {
                'name': name,
                'logo': s['pending_profile_logo'],
                'position': s['position'],
                'size': s['watermark_size'],
            }
            s['pending_profile_logo'] = None
            activate_profile(user_id, pid)
            await send_profile_settings_screen(update.message.chat_id, context, user_id, pid)
        return

    # ── Ввод размера ватермарки ──
    if s.get('waiting_for_size'):
        s['waiting_for_size'] = False
        raw = update.message.text.strip().rstrip('%')
        try:
            value = int(raw)
            if not 0 <= value <= 100:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ Введи число от 0 до 100 (например: <b>25</b>)", parse_mode='HTML'
            )
            s['waiting_for_size'] = True
            return

        s['watermark_size'] = round(value / 100, 2)
        sync_active_profile(user_id)
        current_pct = value
        pid = s['active_profile_id']

        if s['last_image']:
            output = process_image_with_settings(
                s['last_image'], s['darkness'], s['position'],
                get_user_logo(user_id), logo_size_fraction=s['watermark_size']
            )
            await update.message.reply_photo(
                photo=output,
                caption=make_status_caption(user_id, f"✅ <b>Размер: {value}%</b>"),
                parse_mode='HTML',
                reply_markup=get_settings_keyboard()
            )
        elif pid and pid in s['profiles']:
            await send_profile_settings_screen(update.message.chat_id, context, user_id, pid)
        else:
            await update.message.reply_text(
                f"✅ Размер ватермарки: {value}%\n\nОтправь фото для обработки!",
                reply_markup=get_main_menu_keyboard()
            )
        return


async def _save_logo_for_profile(user_id, logo_bytes, chat_id, context):
    """После получения лого — спросить название профиля"""
    s = get_user_settings(user_id)
    s['pending_profile_logo'] = logo_bytes
    s['waiting_for_profile_name'] = True
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "✅ Лого получен!\n\n"
            "Теперь введи <b>название</b> для этого профиля.\n"
            "Например: <code>Dox Agency</code>, <code>Личный бренд</code>"
        ),
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("« Отмена", callback_data="profile_cancel_create")
        ]])
    )


async def process_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Документы (PNG без сжатия)"""
    user_id = update.effective_user.id
    s = get_user_settings(user_id)

    if s.get('waiting_for_profile_logo'):
        s['waiting_for_profile_logo'] = False
        try:
            doc = update.message.document
            file = await context.bot.get_file(doc.file_id)
            logo_bytes = bytes(await file.download_as_bytearray())
            await _save_logo_for_profile(user_id, logo_bytes, update.message.chat_id, context)
        except Exception as e:
            logger.error(f"Ошибка загрузки лого (документ): {e}")
            await update.message.reply_text("❌ Ошибка. Попробуй ещё раз.")
        return


async def _process_media_group(group_id: str, chat_id: int, user_id: int, context):
    """Обработать все фото медиагруппы после небольшой задержки"""
    await asyncio.sleep(1.5)  # ждём, пока придут все фото группы

    entry = media_group_buffer.pop(group_id, None)
    if not entry:
        return

    file_ids = entry['file_ids']
    s = get_user_settings(user_id)

    try:
        msg = await context.bot.send_message(chat_id=chat_id, text=f"⏳ Обрабатываю {len(file_ids)} фото...")

        results = []
        for file_id in file_ids:
            file = await context.bot.get_file(file_id)
            photo_bytes = bytes(await file.download_as_bytearray())
            output = process_image_with_settings(
                photo_bytes, s['darkness'], s['position'],
                get_user_logo(user_id), logo_size_fraction=s['watermark_size']
            )
            results.append(output)

        # Сохраняем последнее фото как last_image для повторного использования
        if results:
            last_file = await context.bot.get_file(file_ids[-1])
            s['last_image'] = bytes(await last_file.download_as_bytearray())

        await msg.delete()

        # Отправляем как альбом (первое фото с подписью)
        media = []
        for i, output in enumerate(results):
            caption = make_status_caption(user_id) if i == 0 else None
            parse_mode = 'HTML' if i == 0 else None
            media.append(InputMediaPhoto(media=output, caption=caption, parse_mode=parse_mode))

        sent = await context.bot.send_media_group(chat_id=chat_id, media=media)

        # Отправляем кнопки настроек отдельным сообщением
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ Обработано фото: {len(results)}",
            reply_markup=get_settings_keyboard()
        )

        logger.info(f"Обработана медиагруппа {group_id} ({len(results)} фото) от {user_id}")

    except Exception as e:
        logger.error(f"Ошибка обработки медиагруппы: {e}", exc_info=True)
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Ошибка: {e}")


async def process_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фотографии — одиночные и альбомы"""
    user_id = update.effective_user.id
    s = get_user_settings(user_id)

    try:
        # ── Загрузка лого для профиля ──
        if s.get('waiting_for_profile_logo'):
            s['waiting_for_profile_logo'] = False
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            logo_bytes = bytes(await file.download_as_bytearray())
            await _save_logo_for_profile(user_id, logo_bytes, update.message.chat_id, context)
            return

        photo = update.message.photo[-1]
        group_id = update.message.media_group_id

        # ── Медиагруппа (несколько фото) ──
        if group_id:
            if group_id not in media_group_buffer:
                media_group_buffer[group_id] = {
                    'user_id': user_id,
                    'chat_id': update.message.chat_id,
                    'file_ids': [],
                    'task': None,
                }
            media_group_buffer[group_id]['file_ids'].append(photo.file_id)

            # Перезапускаем таймер — ждём прихода всех фото группы
            existing_task = media_group_buffer[group_id].get('task')
            if existing_task and not existing_task.done():
                existing_task.cancel()
            task = asyncio.create_task(
                _process_media_group(group_id, update.message.chat_id, user_id, context)
            )
            media_group_buffer[group_id]['task'] = task
            return

        # ── Одиночное фото ──
        msg = await update.message.reply_text("⏳ Обрабатываю...")
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = bytes(await file.download_as_bytearray())
        s['last_image'] = photo_bytes

        output = process_image_with_settings(
            photo_bytes, s['darkness'], s['position'],
            get_user_logo(user_id), logo_size_fraction=s['watermark_size']
        )
        await msg.delete()
        await update.message.reply_photo(
            photo=output,
            caption=make_status_caption(user_id),
            parse_mode='HTML',
            reply_markup=get_settings_keyboard()
        )
        logger.info(f"Обработано фото от {user_id}")

    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    s = get_user_settings(user_id)
    data = query.data

    try:
        await query.answer()

        # ── Главное меню ──
        if data == "back_to_main":
            dark = 'Без затемнения' if s['darkness'] == 0 else f"{s['darkness']}%"
            text = (
                f"<b>Текущие настройки:</b>\n"
                f"Профиль: {get_active_label(user_id)}\n"
                f"Затемнение: {dark}\n"
                f"Позиция: {get_position_label(s['position'])}\n"
                f"Размер ватермарки: {get_watermark_size_label(s['watermark_size'])}\n\n"
                "Выбери опцию:"
            )
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id, text=text, parse_mode='HTML',
                reply_markup=get_main_menu_keyboard()
            )

        # ── Список профилей ──
        elif data == "menu_logo":
            await send_profiles_screen(query.message.chat_id, context, user_id, query.message)

        # ── Использовать дефолтный лого ──
        elif data == "profile_use_default":
            use_default_logo(user_id)
            if s['last_image']:
                output = process_image_with_settings(
                    s['last_image'], s['darkness'], s['position'],
                    get_user_logo(user_id), logo_size_fraction=s['watermark_size']
                )
                await query.message.delete()
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=output,
                    caption=make_status_caption(user_id, "✅ <b>Активирован Dox (дефолтный)</b>"),
                    parse_mode='HTML',
                    reply_markup=get_settings_keyboard()
                )
            else:
                await send_profiles_screen(query.message.chat_id, context, user_id, query.message)

        # ── Выбрать профиль ──
        elif data.startswith("profile_select_"):
            pid = data.removeprefix("profile_select_")
            if pid not in s['profiles']:
                return
            activate_profile(user_id, pid)
            if s['last_image']:
                output = process_image_with_settings(
                    s['last_image'], s['darkness'], s['position'],
                    get_user_logo(user_id), logo_size_fraction=s['watermark_size']
                )
                await query.message.delete()
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=output,
                    caption=make_status_caption(user_id, f"✅ <b>Профиль: {s['profiles'][pid]['name']}</b>"),
                    parse_mode='HTML',
                    reply_markup=get_settings_keyboard()
                )
            else:
                await send_profile_settings_screen(
                    query.message.chat_id, context, user_id, pid, query.message
                )

        # ── Создать профиль ──
        elif data == "profile_new":
            s['waiting_for_profile_logo'] = True
            s['editing_profile_id'] = None
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=(
                    "📤 <b>Создание профиля — шаг 1/2</b>\n\n"
                    "Отправь изображение логотипа.\n\n"
                    "<i>Рекомендации:</i>\n"
                    "• PNG с прозрачным фоном\n"
                    "• Хорошее качество"
                ),
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Отмена", callback_data="profile_cancel_create")
                ]])
            )

        # ── Отмена создания профиля ──
        elif data == "profile_cancel_create":
            s['waiting_for_profile_logo'] = False
            s['waiting_for_profile_name'] = False
            s['pending_profile_logo'] = None
            s['editing_profile_id'] = None
            await send_profiles_screen(query.message.chat_id, context, user_id, query.message)

        # ── Сменить лого профиля ──
        elif data.startswith("profile_change_logo_"):
            pid = data.removeprefix("profile_change_logo_")
            if pid not in s['profiles']:
                return
            s['waiting_for_profile_logo'] = True
            s['editing_profile_id'] = pid
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=(
                    f"📤 <b>Замена лого профиля «{s['profiles'][pid]['name']}»</b>\n\n"
                    "Отправь новый логотип (PNG с прозрачным фоном)."
                ),
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Отмена", callback_data="profile_cancel_create")
                ]])
            )

        # ── Переименовать профиль ──
        elif data.startswith("profile_rename_"):
            pid = data.removeprefix("profile_rename_")
            if pid not in s['profiles']:
                return
            s['waiting_for_profile_name'] = True
            s['editing_profile_id'] = pid
            # Не трогаем лого — только меняем имя
            s['pending_profile_logo'] = s['profiles'][pid]['logo']
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=(
                    f"✏️ <b>Переименование профиля «{s['profiles'][pid]['name']}»</b>\n\n"
                    "Введи новое название:"
                ),
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Отмена", callback_data="profile_cancel_create")
                ]])
            )

        # ── Удалить профиль ──
        elif data.startswith("profile_delete_"):
            pid = data.removeprefix("profile_delete_")
            if pid in s['profiles']:
                del s['profiles'][pid]
            if s['active_profile_id'] == pid:
                use_default_logo(user_id)
            await send_profiles_screen(query.message.chat_id, context, user_id, query.message)

        # ── Выбор затемнения ──
        elif data == "choose_darkness":
            dark = 'Без затемнения' if s['darkness'] == 0 else f"{s['darkness']}%"
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"⚫ <b>Выбери процент затемнения:</b>\n\nТекущий: {dark}",
                parse_mode='HTML',
                reply_markup=get_darkness_keyboard()
            )

        # ── Краткое описание ──
        elif data == "about_bot":
            text = (
                "ℹ️ <b>Что делает бот:</b>\n\n"
                "• Добавляет ватермарку (из профилей или дефолтную)\n"
                "• Несколько профилей лого — каждый со своим именем, размером и позицией\n"
                "• Размер ватермарки: 0–100% ширины фото\n"
                "• Позиция: 6 вариантов\n"
                "• Затемнение: 0–100%\n\n"
                "Отправь фото — бот вернёт результат."
            )
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id, text=text, parse_mode='HTML',
                reply_markup=get_main_menu_keyboard()
            )

        # ── Изменение затемнения ──
        elif data.startswith("darkness_"):
            darkness = int(data.split("_")[1])
            s['darkness'] = darkness
            dark_label = 'Без затемнения' if darkness == 0 else f"{darkness}%"

            if s['last_image']:
                output = process_image_with_settings(
                    s['last_image'], s['darkness'], s['position'],
                    get_user_logo(user_id), logo_size_fraction=s['watermark_size']
                )
                await query.message.delete()
                await context.bot.send_photo(
                    chat_id=query.message.chat_id, photo=output,
                    caption=make_status_caption(user_id, f"✅ <b>Затемнение: {dark_label}</b>"),
                    parse_mode='HTML', reply_markup=get_settings_keyboard()
                )
            else:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"✅ Затемнение: {dark_label}\n\nОтправь фото для обработки!",
                    reply_markup=get_main_menu_keyboard()
                )

        # ── Изменение размера ватермарки ──
        elif data.startswith("wmsize_"):
            step_map = {
                "wmsize_minus10": -0.10,
                "wmsize_minus5":  -0.05,
                "wmsize_plus5":    0.05,
                "wmsize_plus10":   0.10,
            }

            if data == "wmsize_input":
                s['waiting_for_size'] = True
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=(
                        "✏️ <b>Введи размер ватермарки</b>\n\n"
                        "Число от <b>0</b> до <b>100</b> — процент от ширины фото.\n"
                        "Например: <code>15</code>"
                    ),
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("« Отмена", callback_data="cancel_size_input")
                    ]])
                )
                return

            if data in step_map:
                s['watermark_size'] = max(0.0, min(1.0, round(s['watermark_size'] + step_map[data], 2)))
            sync_active_profile(user_id)

            current_pct = int(round(s['watermark_size'] * 100))
            pid = s['active_profile_id']

            if s['last_image']:
                output = process_image_with_settings(
                    s['last_image'], s['darkness'], s['position'],
                    get_user_logo(user_id), logo_size_fraction=s['watermark_size']
                )
                await query.message.delete()
                await context.bot.send_photo(
                    chat_id=query.message.chat_id, photo=output,
                    caption=make_status_caption(user_id, f"✅ <b>Размер: {current_pct}%</b>"),
                    parse_mode='HTML', reply_markup=get_settings_keyboard()
                )
            elif pid and pid in s['profiles']:
                await send_profile_settings_screen(
                    query.message.chat_id, context, user_id, pid, query.message
                )
            else:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"✅ Размер: {current_pct}%\n\nОтправь фото для обработки!",
                    reply_markup=get_main_menu_keyboard()
                )

        # ── Отмена ввода размера ──
        elif data == "cancel_size_input":
            s['waiting_for_size'] = False
            pid = s['active_profile_id']
            if pid and pid in s['profiles']:
                await send_profile_settings_screen(
                    query.message.chat_id, context, user_id, pid, query.message
                )
            else:
                await send_profiles_screen(query.message.chat_id, context, user_id, query.message)

        # ── Изменение позиции ──
        elif data.startswith("position_"):
            position = data.split("_", 1)[1]
            s['position'] = position
            sync_active_profile(user_id)
            pid = s['active_profile_id']

            if s['last_image']:
                output = process_image_with_settings(
                    s['last_image'], s['darkness'], s['position'],
                    get_user_logo(user_id), logo_size_fraction=s['watermark_size']
                )
                await query.message.delete()
                await context.bot.send_photo(
                    chat_id=query.message.chat_id, photo=output,
                    caption=make_status_caption(user_id, f"✅ <b>Позиция: {get_position_label(position)}</b>"),
                    parse_mode='HTML', reply_markup=get_settings_keyboard()
                )
            elif pid and pid in s['profiles']:
                await send_profile_settings_screen(
                    query.message.chat_id, context, user_id, pid, query.message
                )
            else:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"✅ Позиция: {get_position_label(position)}\n\nОтправь фото!",
                    reply_markup=get_main_menu_keyboard()
                )

    except Exception as e:
        logger.error(f"Ошибка callback: {e}", exc_info=True)
        try:
            await query.answer("❌ Ошибка. Попробуй /start", show_alert=True)
        except Exception:
            pass


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)


async def post_init(application: Application):
    await application.bot.set_my_commands([BotCommand("start", "Главное меню и настройки")])
    logger.info("✅ Команды бота установлены")


def main():
    if not os.path.exists(DEFAULT_LOGO_PATH):
        logger.error(f"ОШИБКА: {DEFAULT_LOGO_PATH} не найден!")
        return

    logger.info("🚀 Запуск Dox Image Bot v3.0...")
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, process_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, process_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_text))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_error_handler(error_handler)

    logger.info("✅ Бот запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
