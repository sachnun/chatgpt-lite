import openai
import logging
import asyncio
import os, time

logging.basicConfig(level=logging.INFO)

from telethon import TelegramClient, events, errors
from telethon.tl.custom.message import Message

from dotenv import load_dotenv
from helpers.tiktoken import count_tokens

load_dotenv()

bot = TelegramClient(
    session="bot", api_id=os.getenv("API_ID"), api_hash=os.getenv("API_HASH")
).start(bot_token=os.getenv("BOT_TOKEN"))

openai.api_base = os.getenv("OPENAI_API_BASE")
openai.api_key = os.getenv("OPENAI_API_KEY")


async def load_history(event: Message, limit=3) -> list:
    """
    Load the chat history for a given message up to a specified limit.

    Args:
        event (Message): The message to load the history for.
        limit (int, optional): The maximum number of messages to load. Defaults to 6.

    Returns:
        list: A list of dictionaries representing the chat history, with each dictionary containing the 'role' (either 'user' or 'assistant') and 'content' of a message.
    """
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


async def generate(messages: list) -> str:
    """
    Generates a response using OpenAI's GPT-3.5-turbo model based on the user's input message.

    Args:
        event (Message): The user's input message.

    Yields:
        str: The generated response from the GPT-3.5-turbo model.
    """
    response = await openai.ChatCompletion.acreate(
        model="gpt-3.5-turbo", messages=messages, stream=True, temperature=0, top_p=0
    )
    async for message in response:
        yield message["choices"][0]["delta"].get("content", "")


RESPONSE_TEMPLATE = """
{response}

**Time taken: {time:.2f}s**
**Token usage: {tokens} / 4096**
"""


async def chat_stream(event: Message):
    start_time = time.time()
    max_delay = 0.5 if event.is_private else 1.5
    memory = [
        *await load_history(event),
        {"role": "user", "content": event.text},
    ]
    async with bot.action(event.chat_id, "typing"):
        full_message, reply, delay = "", None, time.time()
        async for message in generate(memory):
            full_message += message

            try:
                if not reply:
                    reply: Message = await event.reply(message)
                    continue
                if "\n" in message:
                    if time.time() - delay > max_delay:
                        await reply.edit(full_message, link_preview=False)
                        delay = time.time()
            except errors.rpcerrorlist.MessageNotModifiedError:
                pass
            except errors.rpcerrorlist.FloodWaitError as e:
                await asyncio.sleep(e.seconds)
                await reply.edit(full_message, link_preview=False)
                delay = time.time()

        await reply.edit(
            RESPONSE_TEMPLATE.format(
                response=full_message,
                time=time.time() - start_time,
                tokens=count_tokens(full_message) + count_tokens(memory),
            ),
            link_preview=True,
        )


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
        await chat_stream(event)


# filter group chat text message
@bot.on(events.NewMessage(func=lambda e: e.is_group, incoming=True))
async def echo(event: Message):
    if event.mentioned and event.text:
        await chat_stream(event)


# run bot
bot.run_until_disconnected()
