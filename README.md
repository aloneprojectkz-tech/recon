# 🦅 Blackbird OSINT Telegram Bot

Telegram-бот на базе [Blackbird OSINT](https://github.com/p1ngul1n0/blackbird) с поддержкой PostgreSQL и aiogram 3.

## 📁 Структура проекта

```
blackbird_bot/
├── bot.py                  # Главный файл бота
├── db.py                   # Работа с PostgreSQL
├── blackbird_runner.py     # Обёртка над Blackbird для запуска поисков
├── keyboards.py            # Клавиатуры Telegram
├── .env                    # Конфигурация (токен, БД, и т.д.)
├── requirements.txt        # Зависимости
├── src/                    # Исходный код Blackbird
├── data/                   # Данные (email-data.json, wmn-data.json)
└── assets/                 # Ресурсы (шрифты, изображения)
```

## ⚙️ Настройка

### 1. Создайте Telegram-бота

1. Напишите @BotFather в Telegram
2. Отправьте /newbot и следуйте инструкциям
3. Скопируйте токен бота

### 2. Настройте .env

```env
BOT_TOKEN=1234567890:ABCDEFabcdef...
DATABASE_PUBLIC_URL=postgresql://postgres:password@host:port/dbname
ADMIN_IDS=123456789,987654321
BLACKBIRD_WEB_URL=http://127.0.0.1:5000
INSTAGRAM_SESSION_ID=
API_URL=
```

### 3. Установите зависимости

```bash
pip install -r requirements.txt
```

### 4. Запустите бота

```bash
python bot.py
```

## 🤖 Функционал бота

### Пользователи:
- /start — начало работы, показ условий использования
- Поиск по Username — поиск аккаунтов на 600+ сайтах
- Поиск по Email — поиск аккаунтов по email
- Инструкция — справка по использованию
- Веб-интерфейс — ссылка на веб-версию Blackbird
- Мой профиль — статистика поисков

### Администраторы (дополнительно):
- Админ-панель: статистика, список пользователей, история поисков, бан/разбан, назначение администраторов

## 🗃️ База данных

Бот автоматически создаёт таблицы при первом запуске:
- users — пользователи бота
- searches — история поисков
- admins — список администраторов

## 🌐 Веб-интерфейс Blackbird

```bash
python blackbird.py --web
```

Затем укажите URL в .env:
```env
BLACKBIRD_WEB_URL=http://your-server:5000
```

## ⚠️ Важно

- Бот использует только открытые источники
- Поиск может занимать 1–2 минуты
- Пользователи должны принять условия использования перед началом работы

## 📄 Лицензия

Основан на Blackbird by Lucas Antoniaci (p1ngul1n0).
