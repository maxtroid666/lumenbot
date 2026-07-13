import aiohttp
from config import YANDEX_API_KEY, YANDEX_FOLDER_ID, YANDEX_MODEL

COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


def load_personality() -> str:
    with open("personality.txt", "r", encoding="utf-8") as f:
        return f.read()


def build_messages(history: list[tuple[str, str | None, str]]) -> list[dict]:
    """Превращает историю из БД в формат messages для YandexGPT."""
    system_prompt = load_personality()
    messages = [{"role": "system", "text": system_prompt}]

    for role, author, content in history:
        text = f"{author}: {content}" if role == "user" and author else content
        yandex_role = "assistant" if role == "assistant" else "user"
        if len(messages) > 1 and messages[-1]["role"] == yandex_role:
            messages[-1]["text"] += "\n" + text
        else:
            messages.append({"role": yandex_role, "text": text})

    if messages[-1]["role"] != "user":
        messages.append({"role": "user", "text": "(продолжай разговор)"})

    return messages


async def generate_reply(history: list[tuple[str, str | None, str]]) -> str:
    messages = build_messages(history)

    payload = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/{YANDEX_MODEL}",
        "completionOptions": {
            "stream": False,
            "temperature": 0.7,
            "maxTokens": "600",
        },
        "messages": messages,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "x-folder-id": YANDEX_FOLDER_ID,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(COMPLETION_URL, json=payload, headers=headers) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"YandexGPT error {resp.status}: {data}")

    return data["result"]["alternatives"][0]["message"]["text"]
