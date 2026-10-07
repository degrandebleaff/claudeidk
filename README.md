# Anonymous comments bot for Telegram

A bot that lives in a channel's discussion group and lets people comment on channel posts anonymously. All user-facing texts are in Russian (see `anonbot/texts.py`).

## How it works

1. A new post is published in the channel and Telegram forwards it into the linked discussion group automatically. The bot comments under it with «💬 Ожидаем анонимные комментарии...» and a button «✍️ Написать анонимный комментарий».
2. The button opens a private chat with the bot. The user gets their code for this post: 4 random emojis in a quote block. Each user gets a new code for every post, and no two users share a code under the same post. Then the bot asks «Напишите ваш анонимный комментарий сюда 👇».
3. The user's next message is posted in the comments under the post as the emoji code in a quote, followed by the message. Text keeps its formatting. Photos, videos, GIFs, files, audio and voice messages are posted with the code in the caption.
4. When someone in the chat replies to an anonymous comment, the author gets a private message «💬 Пользователь <имя> ответил на ваш комментарий:» with a preview, a «↩️ Ответить анонимно» button and a link to the reply. If several people reply, the author gets a separate notification with its own button for each one. The author's anonymous answer is posted as a reply to the message whose button they clicked, and it keeps the same emoji code.
5. If one anonymous user replies to another, the original author is notified as «Аноним 🦊🌵🎈🔥».

## Setup

1. In @BotFather, **revoke the old token and generate a new one** (the old one was shared in plain text).
2. Add the bot to the channel's **discussion group** and **make it an admin**. Without admin rights the bot can't see the channel posts that are forwarded into the group. Alternatively, turn off privacy mode with `/setprivacy` → Disable in @BotFather, then re-add the bot to the group.
3. Run it:

```bash
pip install -r requirements.txt
cp .env.example .env        # then put the new token into BOT_TOKEN
python -m anonbot
```

The data is stored in SQLite (`anonbot.db` by default; you can change it with `DB_PATH`).
