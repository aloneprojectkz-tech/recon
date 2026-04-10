from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton


def agree_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я согласен / I Agree", callback_data="agree_terms")],
        [InlineKeyboardButton(text="❌ Не согласен / Disagree", callback_data="disagree_terms")],
    ])


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Поиск по Username"), KeyboardButton(text="📧 Поиск по Email")],
            [KeyboardButton(text="📞 Поиск по Телефону"), KeyboardButton(text="🌐 Веб-интерфейс")],
            [KeyboardButton(text="📖 Инструкция"), KeyboardButton(text="📊 Мой профиль")],
        ],
        resize_keyboard=True,
    )


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Поиск по Username"), KeyboardButton(text="📧 Поиск по Email")],
            [KeyboardButton(text="📞 Поиск по Телефону"), KeyboardButton(text="🌐 Веб-интерфейс")],
            [KeyboardButton(text="📖 Инструкция"), KeyboardButton(text="📊 Мой профиль")],
            [KeyboardButton(text="⚙️ Админ-панель")],
        ],
        resize_keyboard=True,
    )


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users")],
        [InlineKeyboardButton(text="🔎 История поисков", callback_data="admin_searches")],
        [InlineKeyboardButton(text="🚫 Забанить пользователя", callback_data="admin_ban")],
        [InlineKeyboardButton(text="✅ Разбанить пользователя", callback_data="admin_unban")],
        [InlineKeyboardButton(text="👑 Добавить администратора", callback_data="admin_add_admin")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
    ])


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
    )


def results_keyboard(query: str, search_type: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Новый поиск", callback_data=f"new_search_{search_type}")],
    ])
