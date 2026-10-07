"""Хранилище на SQLite."""

import secrets
import sqlite3
from dataclasses import dataclass

import aiosqlite

EMOJI_POOL = (
    "🐶🐱🐭🐹🐰🦊🐻🐼🐨🐯🦁🐮🐷🐸🐵🐔🐧🐦🦆🦉🐺🐗🐴🦄🐝🐛🦋🐌🐞🐢🐍🦖🐙🦑🦀🐠🐬🐳🦈🐊"
    "🍏🍎🍐🍊🍋🍌🍉🍇🍓🍒🍑🥝🍍🥥🥑🍆🥕🌽🍄🌵🌲🌴🌻🌹🌷🍀🍁🌙⭐🔥🌈⛄💧"
    "⚽🏀🎈🎁🎲🎯🎸🎺🚀⚓💎🔔🔑🧲🎩👑🍩🍪🍕🍔🧀🍿🧁🍭"
)
EMOJIS = list(dict.fromkeys(EMOJI_POOL))
CODE_LENGTH = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL,
    message_id    INTEGER NOT NULL,
    chat_username TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS codes (
    post_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    code    TEXT    NOT NULL,
    PRIMARY KEY (post_id, user_id),
    UNIQUE (post_id, code)
);

-- Анонимные сообщения, которые бот опубликовал в чате
CREATE TABLE IF NOT EXISTS anon_messages (
    chat_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    post_id    INTEGER NOT NULL,
    author_id  INTEGER NOT NULL,
    code       TEXT    NOT NULL,
    PRIMARY KEY (chat_id, message_id)
);

-- Ответы на анонимные сообщения, о которых автор получил уведомление
CREATE TABLE IF NOT EXISTS replies (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id      INTEGER NOT NULL,
    chat_id      INTEGER NOT NULL,
    message_id   INTEGER NOT NULL,
    replier_name TEXT    NOT NULL,
    recipient_id INTEGER NOT NULL
);

-- Куда пойдёт следующее сообщение пользователя в личке
CREATE TABLE IF NOT EXISTS states (
    user_id  INTEGER PRIMARY KEY,
    post_id  INTEGER NOT NULL,
    reply_id INTEGER
);
"""


@dataclass
class Post:
    id: int
    chat_id: int
    message_id: int
    chat_username: str | None


@dataclass
class AnonMessage:
    chat_id: int
    message_id: int
    post_id: int
    author_id: int
    code: str


@dataclass
class Reply:
    id: int
    post_id: int
    chat_id: int
    message_id: int
    replier_name: str
    recipient_id: int


@dataclass
class State:
    user_id: int
    post_id: int
    reply_id: int | None


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def _fetchone(self, sql: str, params: tuple):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _insert(self, sql: str, params: tuple) -> int:
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur.lastrowid

    # --- посты ---

    async def add_post(self, chat_id: int, message_id: int, chat_username: str | None) -> int:
        await self.conn.execute(
            "INSERT OR IGNORE INTO posts (chat_id, message_id, chat_username) VALUES (?, ?, ?)",
            (chat_id, message_id, chat_username),
        )
        await self.conn.commit()
        row = await self._fetchone(
            "SELECT id FROM posts WHERE chat_id = ? AND message_id = ?", (chat_id, message_id)
        )
        return row[0]

    async def get_post(self, post_id: int) -> Post | None:
        row = await self._fetchone(
            "SELECT id, chat_id, message_id, chat_username FROM posts WHERE id = ?", (post_id,)
        )
        return Post(*row) if row else None

    # --- эмодзи-коды ---

    async def get_or_create_code(self, post_id: int, user_id: int) -> str:
        row = await self._fetchone(
            "SELECT code FROM codes WHERE post_id = ? AND user_id = ?", (post_id, user_id)
        )
        if row:
            return row[0]
        while True:
            code = "".join(secrets.choice(EMOJIS) for _ in range(CODE_LENGTH))
            try:
                await self.conn.execute(
                    "INSERT INTO codes (post_id, user_id, code) VALUES (?, ?, ?)",
                    (post_id, user_id, code),
                )
                await self.conn.commit()
                return code
            except sqlite3.IntegrityError:
                # Код уже занят в этом посте (или код пользователю уже выдан параллельно)
                row = await self._fetchone(
                    "SELECT code FROM codes WHERE post_id = ? AND user_id = ?", (post_id, user_id)
                )
                if row:
                    return row[0]

    # --- анонимные сообщения ---

    async def add_anon_message(self, msg: AnonMessage) -> None:
        await self._insert(
            "INSERT OR REPLACE INTO anon_messages (chat_id, message_id, post_id, author_id, code) "
            "VALUES (?, ?, ?, ?, ?)",
            (msg.chat_id, msg.message_id, msg.post_id, msg.author_id, msg.code),
        )

    async def get_anon_message(self, chat_id: int, message_id: int) -> AnonMessage | None:
        row = await self._fetchone(
            "SELECT chat_id, message_id, post_id, author_id, code FROM anon_messages "
            "WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        )
        return AnonMessage(*row) if row else None

    # --- ответы ---

    async def add_reply(
        self, post_id: int, chat_id: int, message_id: int, replier_name: str, recipient_id: int
    ) -> int:
        return await self._insert(
            "INSERT INTO replies (post_id, chat_id, message_id, replier_name, recipient_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (post_id, chat_id, message_id, replier_name, recipient_id),
        )

    async def get_reply(self, reply_id: int) -> Reply | None:
        row = await self._fetchone(
            "SELECT id, post_id, chat_id, message_id, replier_name, recipient_id FROM replies "
            "WHERE id = ?",
            (reply_id,),
        )
        return Reply(*row) if row else None

    # --- состояние пользователя ---

    async def set_state(self, user_id: int, post_id: int, reply_id: int | None) -> None:
        await self._insert(
            "INSERT OR REPLACE INTO states (user_id, post_id, reply_id) VALUES (?, ?, ?)",
            (user_id, post_id, reply_id),
        )

    async def get_state(self, user_id: int) -> State | None:
        row = await self._fetchone(
            "SELECT user_id, post_id, reply_id FROM states WHERE user_id = ?", (user_id,)
        )
        return State(*row) if row else None

    async def clear_state(self, user_id: int) -> None:
        await self._insert("DELETE FROM states WHERE user_id = ?", (user_id,))
