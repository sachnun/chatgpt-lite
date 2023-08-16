import tiktoken as token
import typing as t

ENCODING = token.encoding_for_model("gpt-3.5-turbo-0613")


def count_tokens(messages: t.Union[str, t.List[t.Dict], t.List[str]]):
    if isinstance(messages, str):
        return len(ENCODING.encode(messages))

    if isinstance(messages, list) and isinstance(messages[0], str):
        return sum(len(ENCODING.encode(x)) for x in messages)

    tokens_per_message = 3
    tokens_per_name = 1

    num_tokens = 0
    try:
        for message in messages:
            num_tokens += tokens_per_message
            for key, value in message.items():
                num_tokens += len(ENCODING.encode(value))
                if key == "name":
                    num_tokens += tokens_per_name
        num_tokens += 3
        return num_tokens
    except:
        return num_tokens
