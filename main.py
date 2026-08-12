import asyncio
import base64
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    FSInputFile
)

from openai import AsyncOpenAI


# ============================================================
# SOZLAMALAR
# ============================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DAILY_LIMIT = 4
RESET_HOURS = 24

IMAGE_MODEL = "gpt-image-1"
TEXT_MODEL = "gpt-5-mini"

DB_FILE = "bot.db"


if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN topilmadi!")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY topilmadi!")

if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID topilmadi!")


# ============================================================
# BOT
# ============================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

openai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY
)


# ============================================================
# DATABASE
# ============================================================

db = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

db.row_factory = sqlite3.Row


def init_db():

    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            limit_count INTEGER DEFAULT 4,
            reset_at TEXT,
            notifications INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            prompt TEXT,
            created_at TEXT
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS limit_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS bot_status (
            id INTEGER PRIMARY KEY,
            last_update TEXT,
            next_update TEXT
        )
    """)

    now = datetime.now(timezone.utc)

    last_update = now.isoformat()

    next_update = (
        now + timedelta(days=7)
    ).isoformat()

    db.execute("""
        INSERT OR IGNORE INTO bot_status
        (id, last_update, next_update)
        VALUES (1, ?, ?)
    """, (
        last_update,
        next_update
    ))

    db.commit()


# ============================================================
# VAQT
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)


# ============================================================
# USER
# ============================================================

def get_user(user_id: int):

    return db.execute(
        """
        SELECT *
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()


def create_user(message: Message):

    user_id = message.from_user.id

    user = get_user(user_id)

    if user:
        return user

    now = now_utc()

    reset_at = (
        now + timedelta(hours=RESET_HOURS)
    )

    db.execute("""
        INSERT INTO users (
            user_id,
            username,
            first_name,
            limit_count,
            reset_at,
            notifications,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        message.from_user.username or "",
        message.from_user.first_name or "",
        DAILY_LIMIT,
        reset_at.isoformat(),
        1,
        now.isoformat()
    ))

    db.commit()

    return get_user(user_id)


def refresh_limit(user_id: int):

    if user_id == ADMIN_ID:
        return

    user = get_user(user_id)

    if not user:
        return

    reset_at = datetime.fromisoformat(
        user["reset_at"]
    )

    if now_utc() >= reset_at:

        new_reset = (
            now_utc() +
            timedelta(hours=RESET_HOURS)
        )

        db.execute("""
            UPDATE users
            SET limit_count = ?,
                reset_at = ?
            WHERE user_id = ?
        """, (
            DAILY_LIMIT,
            new_reset.isoformat(),
            user_id
        ))

        db.commit()


def get_remaining_limit(user_id: int):

    if user_id == ADMIN_ID:
        return "∞"

    refresh_limit(user_id)

    user = get_user(user_id)

    if not user:
        return DAILY_LIMIT

    return max(
        0,
        user["limit_count"]
    )


def use_limit(user_id: int):

    if user_id == ADMIN_ID:
        return True

    refresh_limit(user_id)

    user = get_user(user_id)

    if not user:
        return False

    if user["limit_count"] <= 0:
        return False

    db.execute("""
        UPDATE users
        SET limit_count = limit_count - 1
        WHERE user_id = ?
    """, (user_id,))

    db.commit()

    return True


# ============================================================
# ASOSIY KLAVIATURA
# ============================================================

def main_keyboard(user_id: int):

    buttons = [

        [
            KeyboardButton(
                text="🎨 Rasm yaratish"
            )
        ],

        [
            KeyboardButton(
                text="✨ AI orqali yaratish"
            )
        ],

        [
            KeyboardButton(
                text="👤 Mening profilim"
            )
        ],

        [
            KeyboardButton(
                text="📜 Mening tarixim"
            )
        ],

        [
            KeyboardButton(
                text="🔔 Xabarnomalar"
            )
        ],

        [
            KeyboardButton(
                text="🤖 Botning holati"
            )
        ]

    ]

    # ADMIN TUGMASI FAQAT ADMINDA
    if user_id == ADMIN_ID:

        buttons.append(
            [
                KeyboardButton(
                    text="⚙️ Admin panel"
                )
            ]
        )

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True
    )


# ============================================================
# PROFIL KLAVIATURASI
# ============================================================

def profile_keyboard():

    return ReplyKeyboardMarkup(
        keyboard=[

            [
                KeyboardButton(
                    text="💰 Mening balansim"
                )
            ],

            [
                KeyboardButton(
                    text="🖼️ Mening rasmlarim"
                )
            ],

            [
                KeyboardButton(
                    text="🎟️ Mening qolgan limitim"
                )
            ],

            [
                KeyboardButton(
                    text="📩 Admindan limit so‘rash"
                )
            ],

            [
                KeyboardButton(
                    text="⬅️ Bosh menyu"
                )
            ]

        ],
        resize_keyboard=True
    )


# ============================================================
# TIL TANLASH
# ============================================================

def language_keyboard():

    return ReplyKeyboardMarkup(
        keyboard=[

            [
                KeyboardButton(
                    text="🇺🇿 O‘zbekcha"
                ),

                KeyboardButton(
                    text="🇷🇺 Русский"
                )
            ],

            [
                KeyboardButton(
                    text="🇬🇧 English"
                )
            ],

            [
                KeyboardButton(
                    text="⬅️ Bosh menyu"
                )
            ]

        ],
        resize_keyboard=True
    )


# ============================================================
# XABARNOMALAR
# ============================================================

def notification_keyboard():

    return ReplyKeyboardMarkup(
        keyboard=[

            [
                KeyboardButton(
                    text="🔔 Xabarnomalarni yoqish"
                )
            ],

            [
                KeyboardButton(
                    text="🔕 Xabarnomalarni o‘chirish"
                )
            ],

            [
                KeyboardButton(
                    text="⬅️ Bosh menyu"
                )
            ]

        ],
        resize_keyboard=True
    )


# ============================================================
# ADMIN
# ============================================================

def admin_keyboard():

    return ReplyKeyboardMarkup(
        keyboard=[

            [
                KeyboardButton(
                    text="📊 Statistika"
                )
            ],

            [
                KeyboardButton(
                    text="📩 Limit so‘rovlari"
                )
            ],

            [
                KeyboardButton(
                    text="➕ Limit qo‘shish"
                )
            ],

            [
                KeyboardButton(
                    text="👥 Foydalanuvchilar"
                )
            ],

            [
                KeyboardButton(
                    text="⬅️ Bosh menyu"
                )
            ]

        ],
        resize_keyboard=True
    )


# ============================================================
# FSM HOLATLAR
# ============================================================

class GenerateStates(StatesGroup):

    language = State()

    prompt = State()


class LimitRequestStates(StatesGroup):

    amount = State()


class AdminStates(StatesGroup):

    add_limit_user = State()

    add_limit_amount = State()


# ============================================================
# START
# ============================================================

@dp.message(CommandStart())
async def start_handler(
    message: Message,
    state: FSMContext
):

    await state.clear()

    create_user(message)

    loading = await message.answer(
        "⏳ <b>Bot ishga tushmoqda...</b>",
        parse_mode="HTML"
    )

    await asyncio.sleep(1)

    try:
        await loading.delete()
    except Exception:
        pass

    text = (
        "🤖 <b>OpenAI Generator</b>\n\n"

        "✅ <b>Bot tayyor!</b>\n\n"

        "🎨 <b>Rasm yaratish</b>\n"
        "O‘zingiz xohlagan rasm haqida prompt yozing. "
        "Bot uni tushunib, siz uchun rasm yaratadi.\n\n"

        "✨ <b>AI orqali yaratish</b>\n"
        "Oddiy qilib nima xohlayotganingizni yozing. "
        "AI fikringizni tushunib, unga ijodiy detallar "
        "qo‘shadi va professional rasm yaratadi.\n\n"

        "👤 <b>Mening profilim</b>\n"
        "Balansingiz, yaratgan rasmlaringiz va "
        "qolgan limitingizni ko‘ring.\n\n"

        "📜 <b>Mening tarixim</b>\n"
        "Avval yaratgan rasmlaringiz va "
        "promptlaringiz tarixini ko‘ring.\n\n"

        "🔔 <b>Xabarnomalar</b>\n"
        "Limit yangilanganda avtomatik xabar "
        "olishni boshqaring.\n\n"

        "🤖 <b>Botning holati</b>\n"
        "Botning oxirgi va keyingi yangilanishini ko‘ring.\n\n"

        "🚀 <b>Boshlash uchun pastdagi menyudan "
        "bo‘lim tanlang!</b>"
    )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=main_keyboard(
            message.from_user.id
        )
    )


# ============================================================
# BOSH MENYU
# ============================================================

@dp.message(F.text == "⬅️ Bosh menyu")
async def back_home(
    message: Message,
    state: FSMContext
):

    await state.clear()

    await message.answer(
        "🏠 <b>Bosh menyu</b>\n\n"
        "Kerakli bo‘limni tanlang 👇",
        parse_mode="HTML",
        reply_markup=main_keyboard(
            message.from_user.id
        )
    )


# ============================================================
# PROFIL
# ============================================================

@dp.message(F.text == "👤 Mening profilim")
async def profile(message: Message):

    create_user(message)

    remaining = get_remaining_limit(
        message.from_user.id
    )

    await message.answer(
        "👤 <b>Mening profilim</b>\n\n"

        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"👤 Ism: {message.from_user.first_name or '-'}\n\n"

        f"🎟️ Qolgan limit: <b>{remaining}</b>\n"
        f"🎨 Kunlik asosiy limit: <b>{DAILY_LIMIT}</b>",

        parse_mode="HTML",
        reply_markup=profile_keyboard()
    )


# ============================================================
# BALANS
# ============================================================

@dp.message(F.text == "💰 Mening balansim")
async def balance(message: Message):

    remaining = get_remaining_limit(
        message.from_user.id
    )

    await message.answer(
        "💰 <b>Mening balansim</b>\n\n"
        f"🎟️ Rasm limiti: <b>{remaining}</b>",
        parse_mode="HTML"
    )


# ============================================================
# QOLGAN LIMIT
# ============================================================

@dp.message(F.text == "🎟️ Mening qolgan limitim")
async def remaining_limit(message: Message):

    create_user(message)

    remaining = get_remaining_limit(
        message.from_user.id
    )

    if message.from_user.id == ADMIN_ID:

        await message.answer(
            "👑 <b>Admin</b>\n\n"
            "♾️ Sizda rasm yaratish limiti <b>limitsiz</b>.",
            parse_mode="HTML"
        )

        return

    user = get_user(
        message.from_user.id
    )

    reset_at = datetime.fromisoformat(
        user["reset_at"]
    )

    await message.answer(
        "🎟️ <b>Mening qolgan limitim</b>\n\n"

        f"Qolgan: <b>{remaining}/{DAILY_LIMIT}</b>\n"

        f"🔄 Yangilanish: "
        f"<b>{reset_at.strftime('%d.%m.%Y %H:%M')} UTC</b>",

        parse_mode="HTML"
    )


# ============================================================
# BOT HOLATI
# ============================================================

@dp.message(F.text == "🤖 Botning holati")
async def bot_status(message: Message):

    row = db.execute(
        """
        SELECT *
        FROM bot_status
        WHERE id = 1
        """
    ).fetchone()

    last_update = datetime.fromisoformat(
        row["last_update"]
    )

    next_update = datetime.fromisoformat(
        row["next_update"]
    )

    await message.answer(
        "🤖 <b>OpenAI Generator — Bot holati</b>\n\n"

        "🟢 <b>Holati:</b> Ishlayapti\n\n"

        f"🕐 <b>Oxirgi yangilanish:</b>\n"
        f"{last_update.strftime('%d.%m.%Y %H:%M')} UTC\n\n"

        f"🔄 <b>Keyingi yangilanish:</b>\n"
        f"{next_update.strftime('%d.%m.%Y %H:%M')} UTC\n\n"

        "📅 <b>Yangilanish:</b> Har haftada bir marta",

        parse_mode="HTML"
  )# ============================================================
# RASM YARATISH — TIL TANLASH
# ============================================================

@dp.message(F.text == "🎨 Rasm yaratish")
async def image_start(
    message: Message,
    state: FSMContext
):
    create_user(message)

    if message.from_user.id != ADMIN_ID:

        remaining = get_remaining_limit(
            message.from_user.id
        )

        if remaining <= 0:

            user = get_user(
                message.from_user.id
            )

            reset_at = datetime.fromisoformat(
                user["reset_at"]
            )

            await message.answer(
                "❌ <b>Limitingiz tugagan.</b>\n\n"
                "🎟️ Qolgan limit: <b>0</b>\n"
                f"🔄 Limit qaytishi: "
                f"<b>{reset_at.strftime('%d.%m.%Y %H:%M')} UTC</b>\n\n"
                "📩 Qo‘shimcha limit so‘rash uchun "
                "profil bo‘limidan foydalaning.",
                parse_mode="HTML"
            )

            return

    await state.clear()

    await state.set_state(
        GenerateStates.language
    )

    await message.answer(
        "🌐 <b>Prompt tilini tanlang:</b>",
        parse_mode="HTML",
        reply_markup=language_keyboard()
    )


# ============================================================
# TIL TANLANDI
# ============================================================

@dp.message(
    GenerateStates.language,
    F.text.in_({
        "🇺🇿 O‘zbekcha",
        "🇷🇺 Русский",
        "🇬🇧 English"
    })
)
async def select_language(
    message: Message,
    state: FSMContext
):

    languages = {
        "🇺🇿 O‘zbekcha": "uz",
        "🇷🇺 Русский": "ru",
        "🇬🇧 English": "en"
    }

    language = languages[
        message.text
    ]

    await state.update_data(
        language=language,
        ai_mode=False
    )

    await state.set_state(
        GenerateStates.prompt
    )

    await message.answer(
        "✍️ <b>Endi rasm uchun promptingizni yozing:</b>\n\n"

        "Masalan:\n"
        "<i>Qora fon oldida turgan anime qahramoni, "
        "qo‘lida qilich, dramatik yorug‘lik.</i>\n\n"

        "🎨 Promptingizni yozing 👇",

        parse_mode="HTML"
    )


# ============================================================
# OPENAI — TARJIMA
# ============================================================

async def translate_prompt(
    prompt: str,
    language: str
):

    if language == "en":
        return prompt

    language_name = {
        "uz": "Uzbek",
        "ru": "Russian"
    }.get(
        language,
        "the original language"
    )

    response = await openai_client.responses.create(

        model=TEXT_MODEL,

        instructions=(
            "Translate the user's image prompt into "
            "natural and precise English for an AI image "
            "generator. Preserve the exact meaning and "
            "important details. Do not add unrelated "
            "information. Return ONLY the English prompt."
        ),

        input=(
            f"Translate this {language_name} "
            f"image prompt into English:\n\n{prompt}"
        )
    )

    return response.output_text.strip()


# ============================================================
# OPENAI — AI PROMPTNI PROFESSIONAL QILISH
# ============================================================

async def improve_prompt(prompt: str):

    response = await openai_client.responses.create(

        model=TEXT_MODEL,

        instructions=(
            "You are a professional AI image prompt engineer. "
            "Take the user's simple idea and transform it into "
            "a detailed, creative, high-quality English image "
            "generation prompt. Preserve the user's main idea "
            "and intelligently add useful visual details such "
            "as composition, lighting, atmosphere, camera angle, "
            "environment, colors and visual quality. "
            "Do not add unrelated subjects. "
            "Return ONLY the final English prompt."
        ),

        input=prompt
    )

    return response.output_text.strip()


# ============================================================
# OPENAI — RASM YARATISH
# ============================================================

async def generate_image(prompt: str):

    result = await openai_client.images.generate(

        model=IMAGE_MODEL,

        prompt=prompt,

        size="1024x1024",

        quality="auto"
    )

    if not result.data:
        raise RuntimeError(
            "Rasm qaytmadi."
        )

    image_b64 = result.data[0].b64_json

    if not image_b64:
        raise RuntimeError(
            "Rasm ma'lumoti olinmadi."
        )

    return base64.b64decode(
        image_b64
    )


# ============================================================
# ODDIY RASM YARATISH
# ============================================================

async def create_normal_image(
    message: Message,
    state: FSMContext
):

    user_id = message.from_user.id

    prompt = message.text.strip()

    data = await state.get_data()

    language = data.get(
        "language",
        "en"
    )

    if user_id != ADMIN_ID:

        if not use_limit(user_id):

            await message.answer(
                "❌ <b>Limitingiz tugagan.</b>",
                parse_mode="HTML"
            )

            await state.clear()

            return

    status = await message.answer(
        "⏳ <b>Prompt tayyorlanmoqda...</b>",
        parse_mode="HTML"
    )

    try:

        english_prompt = await translate_prompt(
            prompt,
            language
        )

        await status.edit_text(
            "🎨 <b>Rasm yaratilmoqda...</b>\n\n"
            "⏳ Biroz kuting...",
            parse_mode="HTML"
        )

        image_bytes = await generate_image(
            english_prompt
        )

        filename = (
            f"image_{user_id}_"
            f"{int(now_utc().timestamp())}.png"
        )

        with open(
            filename,
            "wb"
        ) as file:

            file.write(
                image_bytes
            )

        db.execute(
            """
            INSERT INTO images
            (user_id, prompt, created_at)
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                prompt,
                now_utc().isoformat()
            )
        )

        db.commit()

        await status.delete()

        await message.answer_photo(

            photo=FSInputFile(
                filename
            ),

            caption=(
                "✅ <b>Rasm tayyor!</b>\n\n"
                f"📝 Prompt:\n{prompt}"
            ),

            parse_mode="HTML"
        )

        try:
            os.remove(
                filename
            )
        except Exception:
            pass

    except Exception:

        logging.exception(
            "Image generation error"
        )

        # Xatolik bo'lsa limit qaytariladi
        if user_id != ADMIN_ID:

            db.execute(
                """
                UPDATE users
                SET limit_count =
                    limit_count + 1
                WHERE user_id = ?
                """,
                (user_id,)
            )

            db.commit()

        await status.edit_text(
            "❌ <b>Rasm yaratishda xatolik yuz berdi.</b>\n\n"
            "Iltimos, birozdan keyin qayta urinib ko‘ring.",
            parse_mode="HTML"
        )

    await state.clear()


# ============================================================
# AI ORQALI RASM YARATISH
# ============================================================

@dp.message(
    F.text == "✨ AI orqali yaratish"
)
async def ai_create_start(
    message: Message,
    state: FSMContext
):

    create_user(message)

    if message.from_user.id != ADMIN_ID:

        remaining = get_remaining_limit(
            message.from_user.id
        )

        if remaining <= 0:

            await message.answer(
                "❌ <b>Limitingiz tugagan.</b>\n\n"
                "🎟️ Limit qaytishini kuting yoki "
                "👤 Mening profilim orqali "
                "admindan limit so‘rang.",
                parse_mode="HTML"
            )

            return

    await state.clear()

    await state.update_data(
        ai_mode=True
    )

    await state.set_state(
        GenerateStates.prompt
    )

    await message.answer(
        "✨ <b>AI orqali rasm yaratish</b>\n\n"

        "Oddiy qilib nimani xohlayotganingizni yozing.\n\n"

        "Masalan:\n"
        "<i>Orqasi qora bo‘lsin, anime qahramoni "
        "bo‘lsin, qo‘lida qilich bo‘lsin.</i>\n\n"

        "🧠 AI sizning fikringizni tushunadi, "
        "unga mos ijodiy detallar qo‘shadi va "
        "professional prompt yaratadi.\n\n"

        "✍️ G‘oyangizni yozing 👇",

        parse_mode="HTML"
    )


# ============================================================
# PROMPT QABUL QILISH
# ============================================================

@dp.message(
    GenerateStates.prompt,
    F.text
)
async def prompt_handler(
    message: Message,
    state: FSMContext
):

    if message.text == "⬅️ Bosh menyu":

        await state.clear()

        await message.answer(
            "🏠 <b>Bosh menyu</b>",
            parse_mode="HTML",
            reply_markup=main_keyboard(
                message.from_user.id
            )
        )

        return

    data = await state.get_data()

    ai_mode = data.get(
        "ai_mode",
        False
    )

    if ai_mode:

        user_id = message.from_user.id

        if user_id != ADMIN_ID:

            if not use_limit(user_id):

                await state.clear()

                await message.answer(
                    "❌ <b>Limitingiz tugagan.</b>",
                    parse_mode="HTML"
                )

                return

        prompt = message.text.strip()

        status = await message.answer(
            "🧠 <b>AI promptingizni "
            "professional qilmoqda...</b>",
            parse_mode="HTML"
        )

        try:

            final_prompt = await improve_prompt(
                prompt
            )

            await status.edit_text(
                "🎨 <b>AI rasm yaratmoqda...</b>\n\n"
                "⏳ Biroz kuting...",
                parse_mode="HTML"
            )

            image_bytes = await generate_image(
                final_prompt
            )

            filename = (
                f"ai_image_{user_id}_"
                f"{int(now_utc().timestamp())}.png"
            )

            with open(
                filename,
                "wb"
            ) as file:

                file.write(
                    image_bytes
                )

            db.execute(
                """
                INSERT INTO images
                (user_id, prompt, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    user_id,
                    prompt,
                    now_utc().isoformat()
                )
            )

            db.commit()

            await status.delete()

            await message.answer_photo(

                photo=FSInputFile(
                    filename
                ),

                caption=(
                    "✨ <b>AI orqali rasm tayyor!</b>\n\n"
                    f"📝 Sizning g‘oyangiz:\n{prompt}"
                ),

                parse_mode="HTML"
            )

            try:
                os.remove(
                    filename
                )
            except Exception:
                pass

        except        except Exception:

            logging.exception(
                "AI image generation error"
            )

            if user_id != ADMIN_ID:

                db.execute(
                    """
                    UPDATE users
                    SET limit_count =
                        limit_count + 1
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

                db.commit()

            await status.edit_text(
                "❌ <b>Rasm yaratishda xatolik yuz berdi.</b>\n\n"
                "Iltimos, qayta urinib ko‘ring.",
                parse_mode="HTML"
            )

        await state.clear()

        return


# ============================================================
# MENING RASMLARIM
# ============================================================

@dp.message(
    F.text == "🖼️ Mening rasmlarim"
)
async def my_images(
    message: Message
):

    rows = db.execute(
        """
        SELECT prompt, created_at
        FROM images
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 10
        """,
        (message.from_user.id,)
    ).fetchall()

    if not rows:

        await message.answer(
            "🖼️ Siz hali hech qanday "
            "rasm yaratmagansiz."
        )

        return

    text = (
        "🖼️ <b>Oxirgi yaratgan rasmlaringiz:</b>\n\n"
    )

    for index, row in enumerate(
        rows,
        1
    ):

        text += (
            f"{index}. "
            f"{row['prompt'][:120]}\n"
            f"🕐 {row['created_at'][:16]}\n\n"
        )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# ============================================================
# LIMIT SO‘RASH
# ============================================================

@dp.message(
    F.text == "📩 Admindan limit so‘rash"
)
async def request_limit_start(
    message: Message,
    state: FSMContext
):

    if message.from_user.id == ADMIN_ID:

        await message.answer(
            "👑 Siz adminsiz.\n"
            "Sizda limit <b>limitsiz</b>.",
            parse_mode="HTML"
        )

        return

    await state.set_state(
        LimitRequestStates.amount
    )

    await message.answer(
        "📩 <b>Qo‘shimcha limit so‘rash</b>\n\n"
        "Nechta limit kerakligini yozing.\n\n"
        "Masalan:\n"
        "<code>3</code>",
        parse_mode="HTML"
    )


@dp.message(
    LimitRequestStates.amount
)
async def limit_request_amount(
    message: Message,
    state: FSMContext
):

    try:

        amount = int(
            message.text.strip()
        )

    except ValueError:

        await message.answer(
            "❌ Faqat son yozing.\n"
            "Masalan: 3"
        )

        return

    if amount < 1 or amount > 100:

        await message.answer(
            "❌ 1 dan 100 gacha son kiriting."
        )

        return

    user_id = message.from_user.id

    db.execute(
        """
        INSERT INTO limit_requests
        (user_id, amount, status, created_at)
        VALUES (?, ?, 'pending', ?)
        """,
        (
            user_id,
            amount,
            now_utc().isoformat()
        )
    )

    db.commit()

    await message.answer(
        "✅ <b>So‘rovingiz adminga yuborildi!</b>\n\n"
        f"➕ So‘ralgan limit: <b>{amount}</b>\n"
        "⏳ Admin tasdig‘ini kuting.",
        parse_mode="HTML"
    )

    await bot.send_message(

        ADMIN_ID,

        "📩 <b>Yangi limit so‘rovi!</b>\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"👤 Username: @{message.from_user.username or '-'}\n"
        f"➕ So‘ralgan limit: <b>{amount}</b>\n\n"
        "⚙️ Admin panel orqali tasdiqlashingiz mumkin.",

        parse_mode="HTML"
    )

    await state.clear()


# ============================================================
# XABARNOMALAR
# ============================================================

@dp.message(
    F.text == "🔔 Xabarnomalar"
)
async def notifications(
    message: Message
):

    user = get_user(
        message.from_user.id
    )

    enabled = (
        bool(user["notifications"])
        if user
        else True
    )

    status = (
        "🟢 Yoqilgan"
        if enabled
        else "🔴 O‘chirilgan"
    )

    await message.answer(
        "🔔 <b>Xabarnomalar</b>\n\n"
        f"Holati: <b>{status}</b>\n\n"
        "Limit 24 soatdan keyin yangilanganda "
        "bot sizga avtomatik xabar yuboradi.",
        parse_mode="HTML",
        reply_markup=notification_keyboard()
    )


@dp.message(
    F.text == "🔔 Xabarnomalarni yoqish"
)
async def notifications_on(
    message: Message
):

    db.execute(
        """
        UPDATE users
        SET notifications = 1
        WHERE user_id = ?
        """,
        (message.from_user.id,)
    )

    db.commit()

    await message.answer(
        "🔔 Xabarnomalar yoqildi! ✅"
    )


@dp.message(
    F.text == "🔕 Xabarnomalarni o‘chirish"
)
async def notifications_off(
    message: Message
):

    db.execute(
        """
        UPDATE users
        SET notifications = 0
        WHERE user_id = ?
        """,
        (message.from_user.id,)
    )

    db.commit()

    await message.answer(
        "🔕 Xabarnomalar o‘chirildi."
    )


# ============================================================
# ADMIN TEKSHIRUV
# ============================================================

def is_admin(
    user_id: int
):

    return user_id == ADMIN_ID


# ============================================================
# ADMIN PANEL
# ============================================================

@dp.message(
    F.text == "⚙️ Admin panel"
)
async def admin_panel(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "⛔ <b>Siz admin emassiz!</b>",
            parse_mode="HTML"
        )

        return

    await message.answer(
        "⚙️ <b>Admin panel</b>\n\n"
        "Kerakli bo‘limni tanlang 👇",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


# ============================================================
# ADMIN STATISTIKA
# ============================================================

@dp.message(
    F.text == "📊 Statistika"
)
async def admin_stats(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "⛔ Siz admin emassiz!"
        )

        return

    users = db.execute(
        """
        SELECT COUNT(*) AS count
        FROM users
        """
    ).fetchone()["count"]

    images = db.execute(
        """
        SELECT COUNT(*) AS count
        FROM images
        """
    ).fetchone()["count"]

    pending = db.execute(
        """
        SELECT COUNT(*) AS count
        FROM limit_requests
        WHERE status = 'pending'
        """
    ).fetchone()["count"]

    await message.answer(
        "📊 <b>Bot statistikasi</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{users}</b>\n"
        f"🖼️ Yaratilgan rasmlar: <b>{images}</b>\n"
        f"📩 Kutilayotgan so‘rovlar: <b>{pending}</b>",
        parse_mode="HTML"
    )


# ============================================================
# ADMIN LIMIT SO‘ROVLARI
# ============================================================

@dp.message(
    F.text == "📩 Limit so‘rovlari"
)
async def admin_requests(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "⛔ Siz admin emassiz!"
        )

        return

    rows = db.execute(
        """
        SELECT *
        FROM limit_requests
        WHERE status = 'pending'
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()

    if not rows:

        await message.answer(
            "📩 Hozircha kutilayotgan "
            "limit so‘rovlari yo‘q."
        )

        return

    text = (
        "📩 <b>Kutilayotgan so‘rovlar:</b>\n\n"
    )

    for row in rows:

        text += (
            f"🆔 So‘rov: <code>{row['id']}</code>\n"
            f"👤 User: <code>{row['user_id']}</code>\n"
            f"➕ Miqdor: <b>{row['amount']}</b>\n"
            f"🕐 {row['created_at'][:16]}\n\n"
        )

    text += (
        "✅ Tasdiqlash:\n"
        "<code>/approve ID</code>\n\n"
        "❌ Rad etish:\n"
        "<code>/reject ID</code>"
    )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# ============================================================
# ADMIN — TASDIQLASH
# ============================================================

@dp.message(
    F.text.startswith("/approve")
)
async def approve_request(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "⛔ Siz admin emassiz!"
        )

        return

    parts = message.text.split()

    if len(parts) != 2:

        await message.answer(
            "❌ Masalan:\n"
            "<code>/approve 12</code>",
            parse_mode="HTML"
        )

        return

    try:

        request_id = int(
            parts[1]
        )

    except ValueError:

        await message.answer(
            "❌ ID noto‘g‘ri."
        )

        return

    row = db.execute(
        """
        SELECT *
        FROM limit_requests
        WHERE id = ?
        AND status = 'pending'
        """,
        (request_id,)
    ).fetchone()

    if not row:

        await message.answer(
            "❌ Bunday so‘rov topilmadi."
        )

        return

    user_id = row["user_id"]
    amount = row["amount"]

    db.execute(
        """
        UPDATE users
        SET limit_count =
            limit_count + ?
        WHERE user_id = ?
        """,
        (
            amount,
            user_id
        )
    )

    db.execute(
        """
        UPDATE limit_requests
        SET status = 'approved'
        WHERE id = ?
        """,
        (request_id,)
    )

    db.commit()

    await message.answer(
        "✅ <b>So‘rov tasdiqlandi!</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"➕ Qo‘shildi: <b>{amount}</b>",
        parse_mode="HTML"
    )

    try:

        await bot.send_message(
            user_id,
            "🎉 <b>Admin so‘rovingizni tasdiqladi!</b>\n\n"
            f"➕ Sizga <b>{amount}</b> ta "
            "qo‘shimcha limit berildi.",
            parse_mode="HTML"
        )

    except Exception:
        pass# ============================================================
# QO‘SHIMCHA LIMIT UCHUN DATABASE TUZILMASI
# ============================================================

def prepare_database():

    try:
        db.execute(
            """
            ALTER TABLE users
            ADD COLUMN bonus_limit INTEGER DEFAULT 0
            """
        )

        db.commit()

    except sqlite3.OperationalError:
        # Ustun allaqachon mavjud bo‘lsa, xato qilmaydi
        pass


# ============================================================
# LIMITNI YANGILASH — 24 SOAT
# ============================================================

def refresh_limit(user_id: int):

    if user_id == ADMIN_ID:
        return

    user = get_user(user_id)

    if not user:
        return

    reset_at = datetime.fromisoformat(
        user["reset_at"]
    )

    if now_utc() >= reset_at:

        new_reset = (
            now_utc() +
            timedelta(hours=24)
        )

        # Faqat kunlik limit yangilanadi.
        # bonus_limit saqlanib qoladi.
        db.execute(
            """
            UPDATE users
            SET limit_count = ?,
                reset_at = ?
            WHERE user_id = ?
            """,
            (
                DAILY_LIMIT,
                new_reset.isoformat(),
                user_id
            )
        )

        db.commit()


# ============================================================
# QOLGAN LIMITNI HISOBLASH
# ============================================================

def get_remaining_limit(user_id: int):

    if user_id == ADMIN_ID:
        return "∞"

    refresh_limit(user_id)

    user = get_user(user_id)

    if not user:
        return DAILY_LIMIT

    bonus = user["bonus_limit"] or 0

    return max(
        0,
        user["limit_count"] + bonus
    )


# ============================================================
# LIMIT ISHLATISH
# ============================================================

def use_limit(user_id: int):

    if user_id == ADMIN_ID:
        return True

    refresh_limit(user_id)

    user = get_user(user_id)

    if not user:
        return False

    daily = user["limit_count"] or 0
    bonus = user["bonus_limit"] or 0

    total = daily + bonus

    if total <= 0:
        return False

    # Avval admin bergan bonus limit ishlatiladi
    if bonus > 0:

        db.execute(
            """
            UPDATE users
            SET bonus_limit = bonus_limit - 1
            WHERE user_id = ?
            """,
            (user_id,)
        )

    else:

        db.execute(
            """
            UPDATE users
            SET limit_count = limit_count - 1
            WHERE user_id = ?
            """,
            (user_id,)
        )

    db.commit()

    return True


# ============================================================
# ADMIN — LIMIT QO‘SHISH
# ============================================================

@dp.message(
    F.text == "➕ Limit qo‘shish"
)
async def admin_add_limit_start(
    message: Message,
    state: FSMContext
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "⛔ Siz admin emassiz!"
        )

        return

    await state.set_state(
        AdminStates.add_limit_user
    )

    await message.answer(
        "👤 Limit beriladigan "
        "foydalanuvchining Telegram ID "
        "raqamini yuboring."
    )


@dp.message(
    AdminStates.add_limit_user
)
async def admin_add_limit_user(
    message: Message,
    state: FSMContext
):

    try:

        user_id = int(
            message.text.strip()
        )

    except ValueError:

        await message.answer(
            "❌ Telegram ID faqat raqam bo‘lishi kerak."
        )

        return

    user = get_user(user_id)

    if not user:

        await message.answer(
            "❌ Bu foydalanuvchi hali "
            "botni ishlatmagan."
        )

        return

    await state.update_data(
        target_user=user_id
    )

    await state.set_state(
        AdminStates.add_limit_amount
    )

    await message.answer(
        "➕ Nechta <b>qo‘shimcha</b> limit berilsin?\n\n"
        "Masalan: <code>2</code>",
        parse_mode="HTML"
    )


@dp.message(
    AdminStates.add_limit_amount
)
async def admin_add_limit_amount(
    message: Message,
    state: FSMContext
):

    try:

        amount = int(
            message.text.strip()
        )

    except ValueError:

        await message.answer(
            "❌ Faqat son kiriting."
        )

        return

    if amount < 1 or amount > 100:

        await message.answer(
            "❌ 1 dan 100 gacha son kiriting."
        )

        return

    data = await state.get_data()

    user_id = data["target_user"]

    db.execute(
        """
        UPDATE users
        SET bonus_limit =
            bonus_limit + ?
        WHERE user_id = ?
        """,
        (
            amount,
            user_id
        )
    )

    db.commit()

    await message.answer(
        "✅ <b>Limit qo‘shildi!</b>\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"🎁 Qo‘shimcha limit: <b>{amount}</b>",
        parse_mode="HTML"
    )

    try:

        await bot.send_message(
            user_id,

            "🎁 <b>Admin sizga qo‘shimcha limit berdi!</b>\n\n"
            f"➕ Qo‘shilgan limit: <b>{amount}</b>\n\n"
            "Bu limit sizning kunlik limitingizdan "
            "alohida hisoblanadi.",

            parse_mode="HTML"
        )

    except Exception:
        pass

    await state.clear()


# ============================================================
# ADMIN — FOYDALANUVCHILAR
# ============================================================

@dp.message(
    F.text == "👥 Foydalanuvchilar"
)
async def admin_users(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "⛔ Siz admin emassiz!"
        )

        return

    rows = db.execute(
        """
        SELECT
            user_id,
            username,
            first_name,
            limit_count,
            bonus_limit
        FROM users
        ORDER BY created_at DESC
        LIMIT 30
        """
    ).fetchall()

    if not rows:

        await message.answer(
            "👥 Foydalanuvchilar yo‘q."
        )

        return

    text = "👥 <b>Foydalanuvchilar</b>\n\n"

    for row in rows:

        daily = row["limit_count"] or 0
        bonus = row["bonus_limit"] or 0

        text += (
            f"🆔 <code>{row['user_id']}</code>\n"
            f"👤 {row['first_name'] or '-'}\n"
            f"📛 @{row['username'] or '-'}\n"
            f"🎟️ Kunlik: <b>{daily}</b>\n"
            f"🎁 Bonus: <b>{bonus}</b>\n"
            f"📊 Jami: <b>{daily + bonus}</b>\n\n"
        )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# ============================================================
# ADMIN — SO‘ROVNI RAD ETISH
# ============================================================

@dp.message(
    F.text.startswith("/reject")
)
async def reject_request(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "⛔ Siz admin emassiz!"
        )

        return

    parts = message.text.split()

    if len(parts) != 2:

        await message.answer(
            "❌ Masalan:\n"
            "<code>/reject 12</code>",
            parse_mode="HTML"
        )

        return

    try:

        request_id = int(
            parts[1]
        )

    except ValueError:

        await message.answer(
            "❌ ID noto‘g‘ri."
        )

        return

    row = db.execute(
        """
        SELECT *
        FROM limit_requests
        WHERE id = ?
        AND status = 'pending'
        """,
        (request_id,)
    ).fetchone()

    if not row:

        await message.answer(
            "❌ So‘rov topilmadi."
        )

        return

    db.execute(
        """
        UPDATE limit_requests
        SET status = 'rejected'
        WHERE id = ?
        """,
        (request_id,)
    )

    db.commit()

    await message.answer(
        "❌ <b>So‘rov rad etildi.</b>",
        parse_mode="HTML"
    )

    try:

        await bot.send_message(
            row["user_id"],

            "❌ <b>Limit so‘rovingiz rad etildi.</b>\n\n"
            "Agar kerak bo‘lsa, keyinroq "
            "yana so‘rov yuborishingiz mumkin.",

            parse_mode="HTML"
        )

    except Exception:
        pass


# ============================================================
# 24 SOATLIK LIMITNI AVTOMATIK TEKSHIRISH
# ============================================================

async def limit_reset_worker():

    while True:

        try:

            users = db.execute(
                """
                SELECT *
                FROM users
                WHERE reset_at IS NOT NULL
                """
            ).fetchall()

            current = now_utc()

            for user in users:

                user_id = user["user_id"]

                if user_id == ADMIN_ID:
                    continue

                reset_at = datetime.fromisoformat(
                    user["reset_at"]
                )

                if current >= reset_at:

                    new_reset = (
                        current +
                        timedelta(hours=24)
                    )

                    db.execute(
                        """
                        UPDATE users
                        SET limit_count = ?,
                            reset_at = ?
                        WHERE user_id = ?
                        """,
                        (
                            DAILY_LIMIT,
                            new_reset.isoformat(),
                            user_id
                        )
                    )

                    db.commit()

                    # XABARNOMA
                    if user["notifications"]:

                        try:

                            bonus = user["bonus_limit"] or 0

                            await bot.send_message(
                                user_id,

                                "🔔 <b>Limitingiz yangilandi!</b>\n\n"
                                f"🎟️ Yangi kunlik limit: "
                                f"<b>{DAILY_LIMIT}</b>\n"
                                f"🎁 Bonus limit: "
                                f"<b>{bonus}</b>\n\n"
                                "🚀 Endi yana rasm yaratishingiz mumkin!",

                                parse_mode="HTML"
                            )

                        except Exception:
                            pass

        except Exception:

            logging.exception(
                "Limit reset worker error"
            )

        # Har 60 soniyada tekshiradi
        await asyncio.sleep(60)


# ============================================================
# ADMIN BO‘LMAGAN Odam ADMIN TUGMASINI ISHLATSA
# ============================================================

@dp.message(
    F.text == "⚙️ Admin panel"
)
async def admin_only_message(
    message: Message
):

    if message.from_user.id != ADMIN_ID:

        await message.answer(
            "⛔ <b>Siz admin emassiz!</b>\n\n"
            "Bu bo‘lim faqat bot administratori uchun.",
            parse_mode="HTML"
        )

        return


# ============================================================
# NOTO‘G‘RI XABAR
# ============================================================

@dp.message()
async def unknown_message(
    message: Message
):

    await message.answer(
        "🤖 <b>OpenAI Generator</b>\n\n"
        "Iltimos, pastdagi menyudan "
        "kerakli bo‘limni tanlang 👇",
        parse_mode="HTML",
        reply_markup=main_keyboard(
            message.from_user.id
        )
    )


# ============================================================
# BOTNI ISHGA TUSHIRISH
# ============================================================

async def main():

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(message)s"
        )
    )

    # Database
    init_db()

    # Bonus limit ustunini tayyorlash
    prepare_database()

    # 24 soatlik limit worker
    asyncio.create_task(
        limit_reset_worker()
    )

    print(
        "🤖 OpenAI Generator ishga tushdi!"
    )

    await dp.start_polling(
        bot
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
  )
