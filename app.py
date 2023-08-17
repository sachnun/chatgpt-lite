import logging
import asyncio
import os, time

import helpers.template as template

logging.basicConfig(level=logging.INFO)

from telethon import TelegramClient, events, errors, Button
from telethon.tl.custom.message import Message

from dotenv import load_dotenv
from helpers.tiktoken import count_tokens

load_dotenv()

from gptcache import cache
from gptcache.adapter import openai
from gptcache.embedding import Onnx
from gptcache.manager import CacheBase, VectorBase, get_data_manager
from gptcache.processor.post import temperature_softmax
from gptcache.similarity_evaluation.distance import SearchDistanceEvaluation

onnx = Onnx()
data_manager = get_data_manager(
    CacheBase("sqlite"), VectorBase("faiss", dimension=onnx.dimension)
)
cache.init(
    embedding_func=onnx.to_embeddings,
    data_manager=data_manager,
    similarity_evaluation=SearchDistanceEvaluation(),
    post_process_messages_func=temperature_softmax,
)
cache.set_openai_key()

import sqlite3

conn = sqlite3.connect("database.db")
c = conn.cursor()

# tabel for storing messages id and chat id
c.execute(
    """CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL
)"""
)


bot = TelegramClient(
    session="bot", api_id=os.getenv("API_ID"), api_hash=os.getenv("API_HASH")
).start(bot_token=os.getenv("BOT_TOKEN"))


async def load_history(event: Message, limit=3) -> list:
    history = []
    reply: Message = event
    while True:
        if not reply.reply_to_msg_id or len(history) >= limit:
            break

        reply: Message = await reply.get_reply_message()
        history.append(
            {
                "role": "user" if reply.out else "assistant",
                "content": reply.raw_text,
            }
        )

    history.reverse()
    return history


import random


async def generate(messages: list) -> str:
    response = await openai.ChatCompletion.acreate(
        model="gpt-3.5-turbo",
        messages=messages,
        stream=True,
        temperature=random.uniform(0.2, 1.0),
        top_p=0,
    )
    async for message in response:
        yield message["choices"][0]["delta"].get("content", "")


RESPONSE_TEMPLATE = """

**Time taken: {time:.2f}s**
**Token usage: {tokens} / 4096**
"""

CHANNEL_ID = os.getenv("CHANNEL_ID")


async def check_has_subscribe(id):
    users = await bot.get_participants(CHANNEL_ID)
    return any(user.id == id for user in users)


import string


async def chat_stream(event: Message):
    verify = await check_has_subscribe(event.sender_id)
    if not verify:
        link = f"https://t.me/{CHANNEL_ID}"
        return await event.reply(
            f"Please subscribe to the channel first. {template.hide_link(link)}",
            buttons=[(Button.url("Subscribe", link))],
        )

    async def edit_message(*args, **kwargs):
        nonlocal reply
        if reply:
            await reply.edit(*args, **kwargs)
        else:
            reply = await event.reply(*args, **kwargs)

    start_time = time.time()
    max_delay = 0.5 if event.is_private else 1.5
    memory = [
        *await load_history(event),
        {"role": "user", "content": event.text},
    ]
    async with bot.action(event.chat_id, "typing"):
        reply: Message = None
        full_message, delay = "", time.time()
        async for message in generate(memory):
            full_message += message

            try:
                if message in string.punctuation:
                    if time.time() - delay > max_delay or not reply:
                        await edit_message(full_message + " ●", link_preview=False)
                        delay = time.time()
            except errors.rpcerrorlist.MessageNotModifiedError:
                pass
            except errors.rpcerrorlist.FloodWaitError as e:
                await asyncio.sleep(e.seconds)
                await reply.edit(full_message, link_preview=False)
                delay = time.time()

        await edit_message(
            full_message
            + RESPONSE_TEMPLATE.format(
                time=time.time() - start_time,
                tokens=count_tokens(full_message) + count_tokens(memory),
            ),
            link_preview=True,
        )
    # save message id and chat id
    c.execute(
        "INSERT INTO messages (chat_id, message_id) VALUES (?, ?)",
        (event.chat_id, reply.id),
    )

    await asyncio.sleep(5)
    await edit_message(full_message, link_preview=True)


# start command
@bot.on(events.NewMessage(pattern="/start"))
async def start(event: Message):
    event.text = "Hello!"
    await chat_stream(event)
    raise events.StopPropagation


# private chat text message
@bot.on(events.NewMessage(func=lambda e: e.is_private, incoming=True))
async def echo(event: Message):
    if event.text:
        # check if not reply to message
        if not event.reply_to_msg_id:
            # check last message in database
            c.execute(
                "SELECT * FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
                (event.chat_id,),
            )
            last_message = c.fetchone()
            if last_message:
                # get message
                last_message = await bot.get_messages(
                    last_message[1], ids=last_message[2]
                )
                # set to reply
                event.reply_to = last_message

        await chat_stream(event)


# filter group chat text message
@bot.on(events.NewMessage(func=lambda e: e.is_group, incoming=True))
async def echo(event: Message):
    if event.mentioned and event.text:
        await chat_stream(event)


# run bot
bot.run_until_disconnected()
