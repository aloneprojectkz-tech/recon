import asyncpg
import logging
import os

logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_PUBLIC_URL")


async def get_pool():
    return await asyncpg.create_pool(DB_URL, min_size=1, max_size=10)


async def init_db(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                agreed_terms BOOLEAN DEFAULT FALSE,
                is_banned BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                last_active TIMESTAMP DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS searches (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                search_type TEXT NOT NULL,  -- 'username' or 'email'
                query TEXT NOT NULL,
                results_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY,
                added_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Insert default admins from env
        admin_ids_raw = os.getenv("ADMIN_IDS", "")
        if admin_ids_raw:
            for aid in admin_ids_raw.split(","):
                aid = aid.strip()
                if aid.isdigit():
                    await conn.execute("""
                        INSERT INTO admins (user_id) VALUES ($1)
                        ON CONFLICT DO NOTHING
                    """, int(aid))

        logger.info("Database initialized successfully")


async def get_or_create_user(pool, user_id: int, username: str, full_name: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not row:
            await conn.execute("""
                INSERT INTO users (user_id, username, full_name)
                VALUES ($1, $2, $3)
            """, user_id, username, full_name)
            return await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        else:
            await conn.execute("""
                UPDATE users SET last_active = NOW(), username = $2, full_name = $3
                WHERE user_id = $1
            """, user_id, username, full_name)
            return row


async def has_agreed_terms(pool, user_id: int) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT agreed_terms FROM users WHERE user_id = $1", user_id)
        return row["agreed_terms"] if row else False


async def set_agreed_terms(pool, user_id: int):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET agreed_terms = TRUE WHERE user_id = $1", user_id)


async def is_banned(pool, user_id: int) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_banned FROM users WHERE user_id = $1", user_id)
        return row["is_banned"] if row else False


async def is_admin(pool, user_id: int) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id FROM admins WHERE user_id = $1", user_id)
        return row is not None


async def save_search(pool, user_id: int, search_type: str, query: str, results_count: int):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO searches (user_id, search_type, query, results_count)
            VALUES ($1, $2, $3, $4)
        """, user_id, search_type, query, results_count)


async def get_all_users(pool):
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM users ORDER BY created_at DESC")


async def get_all_searches(pool, limit=50):
    async with pool.acquire() as conn:
        return await conn.fetch("""
            SELECT s.*, u.username, u.full_name
            FROM searches s
            JOIN users u ON s.user_id = u.user_id
            ORDER BY s.created_at DESC
            LIMIT $1
        """, limit)


async def get_stats(pool):
    async with pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        agreed_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE agreed_terms = TRUE")
        total_searches = await conn.fetchval("SELECT COUNT(*) FROM searches")
        username_searches = await conn.fetchval("SELECT COUNT(*) FROM searches WHERE search_type = 'username'")
        email_searches = await conn.fetchval("SELECT COUNT(*) FROM searches WHERE search_type = 'email'")
        phone_searches = await conn.fetchval("SELECT COUNT(*) FROM searches WHERE search_type = 'phone'")
        banned_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE")
        return {
            "total_users": total_users,
            "agreed_users": agreed_users,
            "total_searches": total_searches,
            "username_searches": username_searches,
            "email_searches": email_searches,
            "phone_searches": phone_searches,
            "banned_users": banned_users,
        }


async def ban_user(pool, user_id: int):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_banned = TRUE WHERE user_id = $1", user_id)


async def unban_user(pool, user_id: int):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_banned = FALSE WHERE user_id = $1", user_id)


async def add_admin(pool, user_id: int):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)


async def remove_admin(pool, user_id: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM admins WHERE user_id = $1", user_id)
