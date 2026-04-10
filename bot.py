"""
Blackbird OSINT Telegram Bot
Based on the Blackbird project by Lucas Antoniaci (p1ngul1n0)
"""

import asyncio
import logging
import os
import sys
from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import db
from keyboards import (
    agree_keyboard,
    main_menu_keyboard,
    admin_menu_keyboard,
    admin_panel_keyboard,
    cancel_keyboard,
    results_keyboard,
)
from blackbird_runner import search_username, search_email, search_email_full, search_phone

# Per-user last result cache for export
_last_results: dict = {}

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ── Bot & Dispatcher ──────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN not set in .env!")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# DB pool — set at startup
pool = None

BLACKBIRD_WEB_URL = os.getenv("BLACKBIRD_WEB_URL", "http://127.0.0.1:5000")

# ── FSM States ────────────────────────────────────────────────────────────────
class SearchState(StatesGroup):
    waiting_username = State()
    waiting_email = State()
    waiting_phone = State()


class AdminState(StatesGroup):
    waiting_ban_id = State()
    waiting_unban_id = State()
    waiting_add_admin_id = State()


# ── Texts ─────────────────────────────────────────────────────────────────────
DISCLAIMER_TEXT = """
🦅 <b>Recon OSINT Bot</b>

⚠️ <b>ВАЖНОЕ ПРЕДУПРЕЖДЕНИЕ / IMPORTANT DISCLAIMER</b>

Данный бот является инструментом для поиска публичной информации (OSINT).

<b>Автор не несёт ответственности за:</b>
• использование полученных данных в незаконных целях
• нарушение конфиденциальности третьих лиц
• любые последствия использования результатов поиска

<b>Все данные получаются исключительно из открытых источников.</b>

Используя этого бота, вы подтверждаете, что:
✅ будете использовать инструмент только в законных целях
✅ осознаёте, что вся информация получена из публичных источников
✅ принимаете полную ответственность за свои действия
✅ не будете использовать бот для слежки или преследования людей

<b>Я был разработан @aloneabove. Все вопросы к нему 😉.<b>
---

<i>This bot is an OSINT tool for public information search. The author takes no responsibility for illegal use. All data is collected from open sources only. By using this bot you agree to use it for legal purposes only.</i>

Нажмите <b>✅ Я согласен</b> чтобы продолжить.
"""

INSTRUCTION_TEXT = """
📖 <b>Инструкция по использованию Recon</b>

<b>1. Что это такое</b>
Recon — OSINT-инструмент, который ищет аккаунты человека по username или email на 600+ сайтах и соцсетях.

<b>2. Возможности:</b>
• 🔍 Поиск профилей по username
• 📧 Поиск аккаунтов по email
• 📊 Получение публичной информации (имя, описание)
• 📄 Отчёты PDF / CSV / JSON (в web-версии)
• 🤖 AI-анализ аккаунтов (в web-версии)

<b>3. Как использовать бота:</b>

👤 <b>Поиск по Username:</b>
Нажмите "🔍 Поиск по Username" и введите имя пользователя.
Пример: <code>johndoe</code>

📧 <b>Поиск по Email:</b>
Нажмите "📧 Поиск по Email" и введите email.
Пример: <code>user@example.com</code>

<b>4. Веб-интерфейс:</b>
Нажмите "🌐 Веб-интерфейс" для доступа к полной версии с PDF-отчётами и AI-анализом.

<b>5. Параметры</b>
<code>username</code> — поиск по имени пользователя
<code>email</code> — поиск по электронной почте

⏳ Поиск занимает 30–120 секунд в зависимости от нагрузки.

⚠️ Используйте только для законных целей. Все данные из открытых источников.

Юз моего создателя: @AloneAbove ❤️
Канал с зеркалами (на случай блокировки): @recon_mirror
Наш канал: @recon_osint
"""


# ── Helpers ───────────────────────────────────────────────────────────────────
async def ensure_user(message: Message):
    """Register/update user in DB and return user record."""
    user = message.from_user
    return await db.get_or_create_user(
        pool, user.id, user.username or "", user.full_name or ""
    )


async def check_banned(message: Message) -> bool:
    if await db.is_banned(pool, message.from_user.id):
        await message.answer("🚫 Вы заблокированы. Обратитесь к администратору.")
        return True
    return False


async def get_keyboard(user_id: int):
    if await db.is_admin(pool, user_id):
        return admin_menu_keyboard()
    return main_menu_keyboard()


async def send_result(message: Message, progress_msg, result: dict, query: str):
    """Send result as text if short, or as JSON file if too long."""
    import json as _json
    from io import BytesIO
    from aiogram.types import BufferedInputFile

    text = format_results(result)
    search_type = result.get("type", "username")

    # Store last result per user for export
    _last_results[message.from_user.id] = result

    if len(text) <= 4000:
        try:
            await progress_msg.edit_text(
                text, parse_mode="HTML", disable_web_page_preview=True,
                reply_markup=results_keyboard(query, search_type),
            )
        except Exception:
            await message.answer(
                text, parse_mode="HTML", disable_web_page_preview=True,
                reply_markup=results_keyboard(query, search_type),
            )
    else:
        summary = text[:1500] + "\n\n<i>📎 Полный результат — в файле ниже.</i>"
        try:
            await progress_msg.edit_text(
                summary, parse_mode="HTML", disable_web_page_preview=True,
                reply_markup=results_keyboard(query, search_type),
            )
        except Exception:
            await message.answer(
                summary, parse_mode="HTML", disable_web_page_preview=True,
                reply_markup=results_keyboard(query, search_type),
            )
        json_bytes = _json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
        filename = f"recon_{query.replace('@','').replace('+','').replace(' ','_')}.json"
        await message.answer_document(
            BufferedInputFile(json_bytes, filename=filename),
            caption=f"📄 Полный отчёт: <code>{query}</code>",
            parse_mode="HTML",
        )


def format_results(result: dict) -> str:
    """Format search results into a readable message."""
    search_type = result.get("type", "username")

    if search_type == "phone":
        return _format_phone_results(result)

    found = result.get("found", [])
    total = result.get("total_checked", 0)
    elapsed = result.get("elapsed", 0)
    query = result.get("query", "")

    icon = "👤" if search_type == "username" else "📧"
    header = f"{icon} <b>Результаты поиска: <code>{query}</code></b>\n\n"
    stats = f"📊 Найдено: <b>{len(found)}</b> аккаунтов из {total} проверенных сайтов\n"
    stats += f"⏱ Время: {elapsed} сек.\n"

    # Domain info for email
    domain_info = result.get("domain_info")
    if domain_info and search_type == "email":
        stats += f"\n🌐 <b>Домен: {domain_info.get('domain', '')}</b>\n"
        mx = domain_info.get("mx_records", [])
        if mx:
            stats += f"  📬 MX: {mx[0]['host']}\n"
        if domain_info.get("spf"):
            stats += f"  🛡 SPF: <code>{domain_info['spf'][:80]}</code>\n"
        if domain_info.get("dmarc"):
            stats += f"  🔒 DMARC: <code>{domain_info['dmarc'][:80]}</code>\n"
        w = domain_info.get("whois")
        if w:
            if w.get("creation_date"):
                stats += f"  📅 Зарегистрирован: {w['creation_date']}\n"
            if w.get("registrar"):
                stats += f"  🏢 Регистратор: {w['registrar']}\n"
        stats += "\n"

    if not found:
        return header + stats + "⭕ Аккаунты не найдены."

    lines = [header + stats]

    # Group by category
    categories = {}
    for acc in found:
        cat = acc.get("category", "Other")
        categories.setdefault(cat, []).append(acc)

    for cat, accounts in sorted(categories.items()):
        lines.append(f"<b>📂 {cat}</b>")
        for acc in accounts:
            name = acc.get("name", "?")
            url = acc.get("url", "")
            meta = acc.get("metadata")
            line = f"  ✅ <a href='{url}'>{name}</a>"
            if meta:
                for m in meta[:2]:
                    line += f"\n      └ {m.get('name', '')}: {m.get('value', '')}"
            lines.append(line)
        lines.append("")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3900] + "\n\n<i>...и ещё результаты (слишком много для одного сообщения)</i>"
    return text


def _format_phone_results(result: dict) -> str:
    """Format phone search results."""
    query = result.get("query", "")
    header = f"📞 <b>Результаты поиска номера: <code>{query}</code></b>\n\n"

    if not result.get("success"):
        return header + f"❌ Ошибка: {result.get('error', 'неизвестная ошибка')}"

    num = result.get("number_info") or {}
    lines = [header]

    if num:
        lines.append("📋 <b>Информация о номере:</b>")
        if num.get("valid") is not None:
            lines.append(f"  ✅ Валидный: {'Да' if num['valid'] else 'Нет'}")
        for label, key in [
            ("📱 Номер", "international_format"),
            ("🌍 Страна", "country_name"),
            ("📍 Регион", "location"),
            ("📡 Оператор", "carrier"),
            ("📶 Тип линии", "line_type"),
            ("🏳 Код страны", "country_code"),
        ]:
            val = num.get(key) or num.get(key.split("_")[0])
            if val:
                lines.append(f"  {label}: {val}")
        lines.append("")

    platforms = result.get("registered_platforms", [])
    if platforms:
        lines.append(f"🔗 <b>Найден на платформах:</b>")
        for p in platforms:
            lines.append(f"  ✅ {p}")
        lines.append("")

    scanners = result.get("scanners", [])
    for s in scanners:
        name = s.get("scanner", "?")
        data = s.get("data", {})
        if not data:
            continue
        lines.append(f"🔍 <b>{name}:</b>")
        for k, v in data.items():
            if not v or k == "error":
                continue
            if isinstance(v, list):
                lines.append(f"  └ {k}: ({len(v)} результатов)")
                for item in v[:3]:
                    if isinstance(item, dict):
                        url = item.get("url", "")
                        if url:
                            lines.append(f"      • {url}")
                    elif isinstance(item, str):
                        lines.append(f"      • {item}")
            else:
                lines.append(f"  └ {k}: {v}")
        lines.append("")

    if not num and not scanners and not platforms:
        lines.append("ℹ️ Данные не найдены.")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3900] + "\n\n<i>...обрезано</i>"
    return text


# ── Handlers: /start ──────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await ensure_user(message)

    if await check_banned(message):
        return

    agreed = await db.has_agreed_terms(pool, message.from_user.id)
    if not agreed:
        await message.answer(DISCLAIMER_TEXT, parse_mode="HTML", reply_markup=agree_keyboard())
    else:
        kb = await get_keyboard(message.from_user.id)
        await message.answer(
            "🦅 <b>Recon OSINT Bot</b>\n\nВыберите действие из меню ниже:",
            parse_mode="HTML",
            reply_markup=kb,
        )


@dp.callback_query(F.data == "agree_terms")
async def callback_agree(call: CallbackQuery):
    await call.answer()
    await db.set_agreed_terms(pool, call.from_user.id)
    kb = await get_keyboard(call.from_user.id)
    await call.message.edit_text(
        "✅ <b>Вы приняли условия использования.</b>\n\nДобро пожаловать в Recon OSINT Bot!",
        parse_mode="HTML",
    )
    await call.message.answer(
        "🦅 <b>Recon OSINT Bot</b>\n\nВыберите действие из меню ниже:",
        parse_mode="HTML",
        reply_markup=kb,
    )


@dp.callback_query(F.data == "disagree_terms")
async def callback_disagree(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text(
        "❌ Вы отказались от условий использования. Бот недоступен.\n\n"
        "Чтобы начать заново, отправьте /start",
        parse_mode="HTML",
    )


# ── Handlers: Instruction & Web ───────────────────────────────────────────────
@dp.message(F.text == "📖 Инструкция")
async def show_instruction(message: Message):
    if await check_banned(message):
        return
    if not await db.has_agreed_terms(pool, message.from_user.id):
        await message.answer("Сначала примите условия использования. Отправьте /start")
        return
    await message.answer(INSTRUCTION_TEXT, parse_mode="HTML", disable_web_page_preview=True)


@dp.message(F.text == "🌐 Веб-интерфейс")
async def show_web(message: Message):
    if await check_banned(message):
        return
    if not await db.has_agreed_terms(pool, message.from_user.id):
        await message.answer("Сначала примите условия использования. Отправьте /start")
        return
    await message.answer(
        f"🌐 <b>Веб-интерфейс Recon</b>\n\n"
        f"Перейдите по ссылке для доступа к полной версии:\n"
        f"<a href='{BLACKBIRD_WEB_URL}'>{BLACKBIRD_WEB_URL}</a>\n\n"
        f"В веб-версии доступны:\n"
        f"• PDF/CSV/JSON отчёты\n"
        f"• AI-анализ аккаунтов\n"
        f"• Расширенные фильтры",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@dp.message(F.text == "📊 Мой профиль")
async def show_profile(message: Message):
    if await check_banned(message):
        return
    if not await db.has_agreed_terms(pool, message.from_user.id):
        await message.answer("Сначала примите условия использования. Отправьте /start")
        return

    async with pool.acquire() as conn:
        searches = await conn.fetchval(
            "SELECT COUNT(*) FROM searches WHERE user_id = $1", message.from_user.id
        )
        username_s = await conn.fetchval(
            "SELECT COUNT(*) FROM searches WHERE user_id = $1 AND search_type = 'username'",
            message.from_user.id,
        )
        email_s = await conn.fetchval(
            "SELECT COUNT(*) FROM searches WHERE user_id = $1 AND search_type = 'email'",
            message.from_user.id,
        )
        phone_s = await conn.fetchval(
            "SELECT COUNT(*) FROM searches WHERE user_id = $1 AND search_type = 'phone'",
            message.from_user.id,
        )

    is_adm = await db.is_admin(pool, message.from_user.id)
    user = message.from_user

    text = (
        f"📊 <b>Ваш профиль</b>\n\n"
        f"👤 Имя: {user.full_name}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"🔖 Username: @{user.username or 'не указан'}\n"
        f"👑 Роль: {'Администратор' if is_adm else 'Пользователь'}\n\n"
        f"🔍 Всего поисков: <b>{searches}</b>\n"
        f"  👤 По username: {username_s}\n"
        f"  📧 По email: {email_s}\n"
        f"  📞 По телефону: {phone_s}"
    )
    await message.answer(text, parse_mode="HTML")


# ── Handlers: Username Search ─────────────────────────────────────────────────
@dp.message(F.text == "🔍 Поиск по Username")
async def start_username_search(message: Message, state: FSMContext):
    if await check_banned(message):
        return
    if not await db.has_agreed_terms(pool, message.from_user.id):
        await message.answer("Сначала примите условия использования. Отправьте /start")
        return

    await state.set_state(SearchState.waiting_username)
    await message.answer(
        "👤 <b>Поиск по Username</b>\n\n"
        "Введите имя пользователя для поиска:\n"
        "<i>Пример: johndoe</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@dp.message(SearchState.waiting_username)
async def process_username_search(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        kb = await get_keyboard(message.from_user.id)
        await message.answer("Отменено.", reply_markup=kb)
        return

    username = message.text.strip().lstrip("@")
    if not username or len(username) > 100:
        await message.answer("❌ Некорректный username. Попробуйте ещё раз.")
        return

    await state.clear()
    kb = await get_keyboard(message.from_user.id)

    progress_msg = await message.answer(
        f"🛰 <b>Запущен поиск username: <code>{username}</code></b>\n\n"
        f"⏳ Проверяем 600+ сайтов... Это может занять 1–2 минуты.\n"
        f"Пожалуйста, подождите...",
        parse_mode="HTML",
        reply_markup=kb,
    )

    last_update = [0]

    async def progress_callback(done, total):
        pct = int(done / total * 100)
        if pct - last_update[0] >= 15:
            last_update[0] = pct
            try:
                await progress_msg.edit_text(
                    f"🛰 <b>Поиск username: <code>{username}</code></b>\n\n"
                    f"⏳ Прогресс: {pct}% ({done}/{total} сайтов)",
                    parse_mode="HTML",
                )
            except Exception:
                pass

    result = await search_username(username, progress_callback)

    await db.save_search(
        pool,
        message.from_user.id,
        "username",
        username,
        len(result.get("found", [])),
    )

    if not result["success"]:
        await progress_msg.edit_text(
            f"❌ Ошибка при поиске: {result.get('error', 'неизвестная ошибка')}",
            parse_mode="HTML",
        )
        return

    await send_result(message, progress_msg, result, username)


# ── Handlers: Email Search ────────────────────────────────────────────────────
@dp.message(F.text == "📧 Поиск по Email")
async def start_email_search(message: Message, state: FSMContext):
    if await check_banned(message):
        return
    if not await db.has_agreed_terms(pool, message.from_user.id):
        await message.answer("Сначала примите условия использования. Отправьте /start")
        return

    await state.set_state(SearchState.waiting_email)
    await message.answer(
        "📧 <b>Поиск по Email</b>\n\n"
        "Введите email для поиска:\n"
        "<i>Пример: user@example.com</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@dp.message(SearchState.waiting_email)
async def process_email_search(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        kb = await get_keyboard(message.from_user.id)
        await message.answer("Отменено.", reply_markup=kb)
        return

    email = message.text.strip()
    if not email or "@" not in email or len(email) > 200:
        await message.answer("❌ Некорректный email. Попробуйте ещё раз.")
        return

    await state.clear()
    kb = await get_keyboard(message.from_user.id)

    progress_msg = await message.answer(
        f"🛰 <b>Запущен поиск email: <code>{email}</code></b>\n\n"
        f"⏳ Проверяем базы данных... Это может занять некоторое время.\n"
        f"Пожалуйста, подождите...",
        parse_mode="HTML",
        reply_markup=kb,
    )

    last_update = [0]

    async def progress_callback(done, total):
        pct = int(done / total * 100)
        if pct - last_update[0] >= 20:
            last_update[0] = pct
            try:
                await progress_msg.edit_text(
                    f"🛰 <b>Поиск email: <code>{email}</code></b>\n\n"
                    f"⏳ Прогресс: {pct}% ({done}/{total} сайтов)",
                    parse_mode="HTML",
                )
            except Exception:
                pass

    result = await search_email_full(email, progress_callback)

    await db.save_search(
        pool,
        message.from_user.id,
        "email",
        email,
        len(result.get("found", [])),
    )

    if not result["success"]:
        await progress_msg.edit_text(
            f"❌ Ошибка при поиске: {result.get('error', 'неизвестная ошибка')}",
            parse_mode="HTML",
        )
        return

    await send_result(message, progress_msg, result, email)


# ── Handlers: Phone Search ────────────────────────────────────────────────────
@dp.message(F.text == "📞 Поиск по Телефону")
async def start_phone_search(message: Message, state: FSMContext):
    if await check_banned(message):
        return
    if not await db.has_agreed_terms(pool, message.from_user.id):
        await message.answer("Сначала примите условия использования. Отправьте /start")
        return
    await state.set_state(SearchState.waiting_phone)
    await message.answer(
        "📞 <b>Поиск по номеру телефона</b>\n\n"
        "Введите номер в международном формате:\n"
        "<i>Пример: +79001234567 или +12025551234</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@dp.message(SearchState.waiting_phone)
async def process_phone_search(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        kb = await get_keyboard(message.from_user.id)
        await message.answer("Отменено.", reply_markup=kb)
        return

    phone = message.text.strip()
    if not phone or len(phone) > 20:
        await message.answer("❌ Некорректный номер. Введите в формате +79001234567")
        return

    await state.clear()
    kb = await get_keyboard(message.from_user.id)

    progress_msg = await message.answer(
        f"🛰 <b>Запущен поиск номера: <code>{phone}</code></b>\n\n"
        f"⏳ Запрашиваем PhoneInfoga...",
        parse_mode="HTML",
        reply_markup=kb,
    )

    result = await search_phone(phone)
    await db.save_search(pool, message.from_user.id, "phone", phone, 0)

    await send_result(message, progress_msg, result, phone)


# ── Admin Panel ───────────────────────────────────────────────────────────────
async def admin_panel(message: Message, state: FSMContext):
    if not await db.is_admin(pool, message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    await state.clear()
    await message.answer(
        "⚙️ <b>Панель администратора</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard(),
    )


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if not await db.is_admin(pool, call.from_user.id):
        await call.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await call.answer()
    stats = await db.get_stats(pool)
    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: <b>{stats['total_users']}</b>\n"
        f"✅ Приняли условия: <b>{stats['agreed_users']}</b>\n"
        f"🚫 Забанено: <b>{stats['banned_users']}</b>\n\n"
        f"🔍 Всего поисков: <b>{stats['total_searches']}</b>\n"
        f"  👤 По username: {stats['username_searches']}\n"
        f"  📧 По email: {stats['email_searches']}\n"
        f"  📞 По телефону: {stats.get('phone_searches', 0)}"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=admin_panel_keyboard())


@dp.callback_query(F.data == "admin_users")
async def admin_users(call: CallbackQuery):
    if not await db.is_admin(pool, call.from_user.id):
        await call.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await call.answer()
    users = await db.get_all_users(pool)
    if not users:
        await call.message.edit_text("Нет пользователей.", reply_markup=admin_panel_keyboard())
        return

    lines = [f"👥 <b>Пользователи ({len(users)}):</b>\n"]
    for u in users[:30]:
        status = "🚫" if u["is_banned"] else "✅"
        lines.append(
            f"{status} <code>{u['user_id']}</code> — @{u['username'] or '—'} {u['full_name'] or ''}"
        )
    if len(users) > 30:
        lines.append(f"\n<i>...и ещё {len(users) - 30} пользователей</i>")

    await call.message.edit_text(
        "\n".join(lines), parse_mode="HTML", reply_markup=admin_panel_keyboard()
    )


@dp.callback_query(F.data == "admin_searches")
async def admin_searches(call: CallbackQuery):
    if not await db.is_admin(pool, call.from_user.id):
        await call.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await call.answer()
    searches = await db.get_all_searches(pool, limit=20)
    if not searches:
        await call.message.edit_text("Нет поисков.", reply_markup=admin_panel_keyboard())
        return

    lines = [f"🔎 <b>Последние 20 поисков:</b>\n"]
    for s in searches:
        icon = "👤" if s["search_type"] == "username" else "📧"
        lines.append(
            f"{icon} <code>{s['query']}</code> — {s['results_count']} найдено | @{s['username'] or s['user_id']}"
        )

    await call.message.edit_text(
        "\n".join(lines), parse_mode="HTML", reply_markup=admin_panel_keyboard()
    )


@dp.callback_query(F.data == "admin_ban")
async def admin_ban_prompt(call: CallbackQuery, state: FSMContext):
    if not await db.is_admin(pool, call.from_user.id):
        await call.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await call.answer()
    await state.set_state(AdminState.waiting_ban_id)
    await call.message.answer(
        "🚫 Введите Telegram ID пользователя для бана:", reply_markup=cancel_keyboard()
    )


@dp.message(AdminState.waiting_ban_id)
async def admin_ban_execute(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        kb = await get_keyboard(message.from_user.id)
        await message.answer("Отменено.", reply_markup=kb)
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите числовой ID.")
        return
    uid = int(message.text)
    await db.ban_user(pool, uid)
    await state.clear()
    kb = await get_keyboard(message.from_user.id)
    await message.answer(f"✅ Пользователь <code>{uid}</code> забанен.", parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "admin_unban")
async def admin_unban_prompt(call: CallbackQuery, state: FSMContext):
    if not await db.is_admin(pool, call.from_user.id):
        await call.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await call.answer()
    await state.set_state(AdminState.waiting_unban_id)
    await call.message.answer(
        "✅ Введите Telegram ID пользователя для разбана:", reply_markup=cancel_keyboard()
    )


@dp.message(AdminState.waiting_unban_id)
async def admin_unban_execute(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        kb = await get_keyboard(message.from_user.id)
        await message.answer("Отменено.", reply_markup=kb)
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите числовой ID.")
        return
    uid = int(message.text)
    await db.unban_user(pool, uid)
    await state.clear()
    kb = await get_keyboard(message.from_user.id)
    await message.answer(f"✅ Пользователь <code>{uid}</code> разбанен.", parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "admin_add_admin")
async def admin_add_admin_prompt(call: CallbackQuery, state: FSMContext):
    if not await db.is_admin(pool, call.from_user.id):
        await call.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await call.answer()
    await state.set_state(AdminState.waiting_add_admin_id)
    await call.message.answer(
        "👑 Введите Telegram ID нового администратора:", reply_markup=cancel_keyboard()
    )


@dp.message(AdminState.waiting_add_admin_id)
async def admin_add_admin_execute(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        kb = await get_keyboard(message.from_user.id)
        await message.answer("Отменено.", reply_markup=kb)
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите числовой ID.")
        return
    uid = int(message.text)
    await db.add_admin(pool, uid)
    await state.clear()
    kb = await get_keyboard(message.from_user.id)
    await message.answer(
        f"✅ Пользователь <code>{uid}</code> назначен администратором.",
        parse_mode="HTML",
        reply_markup=kb,
    )


@dp.callback_query(F.data == "admin_back")
async def admin_back(call: CallbackQuery):
    await call.answer()
    await call.message.delete()


# ── New search callbacks ───────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("new_search_"))
async def new_search_callback(call: CallbackQuery, state: FSMContext):
    await call.answer()
    search_type = call.data.replace("new_search_", "")
    if search_type == "username":
        await state.set_state(SearchState.waiting_username)
        await call.message.answer(
            "👤 Введите username для поиска:", reply_markup=cancel_keyboard()
        )
    else:
        await state.set_state(SearchState.waiting_email)
        await call.message.answer(
            "📧 Введите email для поиска:", reply_markup=cancel_keyboard()
        )


# ── Export callbacks ──────────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("export_"))
async def export_callback(call: CallbackQuery):
    import json as _json
    import csv as _csv
    from io import StringIO
    from aiogram.types import BufferedInputFile

    await call.answer("⏳ Готовлю файл...")

    uid = call.from_user.id
    result = _last_results.get(uid)
    if not result:
        await call.message.answer("❌ Нет данных для экспорта. Сначала выполните поиск.")
        return

    parts = call.data.split("_")  # export_json_username
    fmt = parts[1]
    query = result.get("query", "result")
    filename_base = query.replace("@", "").replace("+", "").replace(" ", "_")

    if fmt == "json":
        content = _json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
        filename = f"recon_{filename_base}.json"
        await call.message.answer_document(
            BufferedInputFile(content, filename=filename),
            caption="📄 <b>JSON экспорт</b>", parse_mode="HTML",
        )

    elif fmt == "csv":
        output = StringIO()
        writer = _csv.writer(output)
        if result.get("type") == "phone":
            writer.writerow(["field", "value"])
            num = result.get("number_info") or {}
            for k, v in num.items():
                if v: writer.writerow([k, v])
            for p in result.get("registered_platforms", []):
                writer.writerow(["platform", p])
        else:
            writer.writerow(["name", "url", "category", "metadata"])
            for acc in result.get("found", []):
                meta = "; ".join(f"{m['name']}:{m['value']}" for m in (acc.get("metadata") or []))
                writer.writerow([acc.get("name",""), acc.get("url",""), acc.get("category",""), meta])
        content = output.getvalue().encode("utf-8-sig")
        filename = f"recon_{filename_base}.csv"
        await call.message.answer_document(
            BufferedInputFile(content, filename=filename),
            caption="📊 <b>CSV экспорт</b>", parse_mode="HTML",
        )

    elif fmt == "txt":
        lines = [f"Recon OSINT — {result.get('type','').upper()} — {query}", "=" * 50]
        if result.get("type") == "phone":
            num = result.get("number_info") or {}
            for k, v in num.items():
                if v: lines.append(f"{k}: {v}")
            lines.append("")
            for p in result.get("registered_platforms", []):
                lines.append(f"Platform: {p}")
        else:
            for acc in result.get("found", []):
                lines.append(f"[{acc.get('category','')}] {acc.get('name','')} — {acc.get('url','')}")
        content = "\n".join(lines).encode("utf-8")
        filename = f"recon_{filename_base}.txt"
        await call.message.answer_document(
            BufferedInputFile(content, filename=filename),
            caption="📝 <b>TXT экспорт</b>", parse_mode="HTML",
        )


# ── /help command ─────────────────────────────────────────────────────────────
@dp.message(Command("help"))
async def cmd_help(message: Message):
    await show_instruction(message)


# ── Startup / Shutdown ────────────────────────────────────────────────────────
async def on_startup():
    global pool
    os.makedirs("logs", exist_ok=True)
    logger.info("Connecting to database...")
    pool = await db.get_pool()
    await db.init_db(pool)
    logger.info("Database ready.")
    logger.info("Bot started!")


async def on_shutdown():
    if pool:
        await pool.close()
    logger.info("Bot stopped.")


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
