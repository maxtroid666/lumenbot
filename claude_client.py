from anthropic import AsyncAnthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


def load_personality() -> str:
    with open("personality.txt", "r", encoding="utf-8") as f:
        return f.read()


def build_messages(history: list[tuple[str, str | None, str]]) -> list[dict]:
    """Превращает историю из БД в формат messages для Claude API.
    Подряд идущие сообщения с одинаковой ролью Claude API не любит,
    поэтому склеиваем их в один блок при необходимости."""
    messages: list[dict] = []
    for role, author, content in history:
        text = f"{author}: {content}" if role == "user" and author else content
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n" + text
        else:
            messages.append({"role": role, "content": text})

    if not messages or messages[-1]["role"] != "user":
        messages.append({"role": "user", "content": "(продолжай разговор)"})

    return messages


async def generate_reply(history: list[tuple[str, str | None, str]]) -> str:
    system_prompt = load_personality()
    messages = build_messages(history)

    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=600,
        system=system_prompt,
        messages=messages,
    )

    return "".join(block.text for block in response.content if block.type == "text")
