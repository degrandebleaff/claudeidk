"""Обработчики: посты канала в группе обсуждения, анонимные комментарии и ответы."""

import asyncio
import html
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyParameters,
)

from . import texts
from .db import AnonMessage, Database

log = logging.getLogger(__name__)
router = Router()

GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}
ALBUM_WAIT_SECONDS = 1.5
PREVIEW_LIMIT = 300

# (chat_id, media_group_id) -> id сообщений альбома, пришедших за время ожидания
_pending_albums: dict[tuple[int, str], list[int]] = {}


def message_link(chat_id: int, chat_username: str | None, message_id: int) -> str | None:
    if chat_username:
        return f"https://t.me/{chat_username}/{message_id}"
    chat = str(chat_id)
    if chat.startswith("-100"):
        return f"https://t.me/c/{chat[4:]}/{message_id}"
    return None


def preview(message: Message) -> str:
    raw = message.text or message.caption or texts.NON_TEXT_PLACEHOLDER
    if len(raw) > PREVIEW_LIMIT:
        raw = raw[:PREVIEW_LIMIT] + "…"
    return html.escape(raw)


def sender_name(message: Message) -> str:
    if message.sender_chat:
        return message.sender_chat.title or "Канал"
    return message.from_user.full_name


async def notify_author(
    bot: Bot,
    db: Database,
    target: AnonMessage,
    reply_message_id: int,
    replier_name: str,
    reply_preview: str,
    chat_username: str | None,
) -> None:
    """Сообщить автору анонимного сообщения, что ему ответили."""
    reply_id = await db.add_reply(
        target.post_id, target.chat_id, reply_message_id, replier_name, target.author_id
    )
    buttons = [[InlineKeyboardButton(text=texts.BTN_REPLY_ANON, callback_data=f"r:{reply_id}")]]
    link = message_link(target.chat_id, chat_username, reply_message_id)
    if link:
        buttons.append([InlineKeyboardButton(text=texts.BTN_OPEN, url=link)])
    text = (
        texts.REPLY_NOTIFICATION.format(name=html.escape(replier_name))
        + f"\n<blockquote>{reply_preview}</blockquote>"
    )
    try:
        await bot.send_message(
            target.author_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        log.info("Не удалось уведомить пользователя %s: %s", target.author_id, e)


# ---------------------------------------------------------------- группа


@router.message(F.chat.type.in_(GROUP_TYPES), F.is_automatic_forward)
async def on_channel_post(message: Message, bot: Bot, db: Database, bot_username: str) -> None:
    """Новый пост канала автоматически переслан в группу обсуждения."""
    target_id = message.message_id
    if message.media_group_id:
        # Альбом приходит несколькими сообщениями — комментируем его один раз
        key = (message.chat.id, message.media_group_id)
        if key in _pending_albums:
            _pending_albums[key].append(message.message_id)
            return
        _pending_albums[key] = [message.message_id]
        await asyncio.sleep(ALBUM_WAIT_SECONDS)
        target_id = min(_pending_albums.pop(key))

    post_id = await db.add_post(message.chat.id, target_id, message.chat.username)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.BTN_WRITE_COMMENT,
                    url=f"https://t.me/{bot_username}?start=c{post_id}",
                )
            ]
        ]
    )
    await bot.send_message(
        message.chat.id,
        texts.WAITING_FOR_COMMENTS,
        reply_parameters=ReplyParameters(message_id=target_id),
        reply_markup=keyboard,
    )


@router.message(F.chat.type.in_(GROUP_TYPES), F.reply_to_message)
async def on_group_reply(message: Message, bot: Bot, db: Database) -> None:
    """Кто-то в чате ответил на анонимное сообщение бота."""
    replied = message.reply_to_message
    if not replied.from_user or replied.from_user.id != bot.id:
        return
    target = await db.get_anon_message(message.chat.id, replied.message_id)
    if not target:
        return
    if not message.sender_chat and message.from_user.id == target.author_id:
        return  # автор ответил сам себе
    await notify_author(
        bot,
        db,
        target,
        reply_message_id=message.message_id,
        replier_name=sender_name(message),
        reply_preview=preview(message),
        chat_username=message.chat.username,
    )


# ---------------------------------------------------------------- личка


async def start_writing(bot: Bot, db: Database, user_id: int, post_id: int) -> None:
    post = await db.get_post(post_id)
    if not post:
        await bot.send_message(user_id, texts.POST_NOT_FOUND)
        return
    code = await db.get_or_create_code(post.id, user_id)
    await db.set_state(user_id, post.id, None)
    await bot.send_message(
        user_id, texts.YOUR_CODE.format(code=code) + "\n\n" + texts.WRITE_COMMENT_PROMPT
    )


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def on_start(message: Message, command: CommandObject, bot: Bot, db: Database) -> None:
    args = command.args or ""
    if args.startswith("c") and args[1:].isdigit():
        await start_writing(bot, db, message.from_user.id, int(args[1:]))
    else:
        await message.answer(texts.START_NO_PAYLOAD)


@router.callback_query(F.data.startswith("c:"))
async def on_write_more(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    await callback.answer()
    await start_writing(bot, db, callback.from_user.id, int(callback.data[2:]))


@router.callback_query(F.data.startswith("r:"))
async def on_reply_button(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    reply = await db.get_reply(int(callback.data[2:]))
    if not reply or reply.recipient_id != callback.from_user.id:
        await callback.answer(texts.REPLY_NOT_FOUND, show_alert=True)
        return
    await callback.answer()
    code = await db.get_or_create_code(reply.post_id, callback.from_user.id)
    await db.set_state(callback.from_user.id, reply.post_id, reply.id)
    await bot.send_message(
        callback.from_user.id,
        texts.YOUR_CODE.format(code=code)
        + "\n\n"
        + texts.WRITE_REPLY_PROMPT.format(name=html.escape(reply.replier_name)),
    )


@router.message(F.chat.type == ChatType.PRIVATE)
async def on_private_message(message: Message, bot: Bot, db: Database) -> None:
    """Пользователь прислал анонимный комментарий или ответ."""
    if message.text and message.text.startswith("/"):
        await message.answer(texts.START_NO_PAYLOAD)
        return  # неизвестные команды не публикуем

    user_id = message.from_user.id
    state = await db.get_state(user_id)
    post = await db.get_post(state.post_id) if state else None
    if not post:
        await message.answer(texts.NO_ACTIVE_TARGET)
        return

    reply = await db.get_reply(state.reply_id) if state.reply_id else None
    reply_to = reply.message_id if reply else post.message_id
    code = await db.get_or_create_code(post.id, user_id)
    body = texts.ANON_MESSAGE.format(code=code, body=message.html_text)
    reply_parameters = ReplyParameters(message_id=reply_to)

    try:
        if message.text:
            sent = await bot.send_message(post.chat_id, body, reply_parameters=reply_parameters)
        elif (
            message.photo
            or message.video
            or message.animation
            or message.document
            or message.audio
            or message.voice
        ):
            sent = await message.copy_to(
                post.chat_id, caption=body, parse_mode="HTML", reply_parameters=reply_parameters
            )
        else:
            await message.answer(texts.UNSUPPORTED_CONTENT)
            return
    except TelegramBadRequest as e:
        log.warning("Не удалось опубликовать анонимное сообщение: %s", e)
        too_long = "too long" in e.message.lower()
        await message.answer(texts.TOO_LONG if too_long else texts.SEND_FAILED)
        return

    await db.add_anon_message(AnonMessage(post.chat_id, sent.message_id, post.id, user_id, code))
    await db.clear_state(user_id)

    # Если ответили анонимно на чужое анонимное сообщение — уведомляем его автора
    target = await db.get_anon_message(post.chat_id, reply_to)
    if target and target.author_id != user_id:
        await notify_author(
            bot,
            db,
            target,
            reply_message_id=sent.message_id,
            replier_name=texts.ANON_NAME.format(code=code),
            reply_preview=preview(message),
            chat_username=post.chat_username,
        )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_WRITE_MORE, callback_data=f"c:{post.id}")]
        ]
    )
    await message.answer(texts.REPLY_SENT if reply else texts.COMMENT_SENT, reply_markup=keyboard)
