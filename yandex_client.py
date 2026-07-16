import aiohttp
from config import YANDEX_API_KEY, YANDEX_FOLDER_ID, YANDEX_MODEL

COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

SUMMARY_SYSTEM_PROMPT = """Ты - ассистент, который делает саммари рабочей переписки команды в Telegram.

На вход тебе дают кусок переписки чата (реплики с указанием автора) из ветки "{topic_name}". Составь структурированную сводку на русском языке в следующем формате:

**Обсуждали:** коротко, о чём вообще был разговор (1-2 пункта или предложения).

**Решения и договорённости:** что было решено или на чём сошлись. Если решений не было - напиши "решений не было".

**Задачи и поручения:** кто что должен сделать, если это прозвучало в переписке (формат: "Имя - что сделать"). Если задач не звучало - напиши "задач не звучало".

**Открытые вопросы:** что осталось не решено или требует уточнения. Если таких нет - напиши "открытых вопросов нет".

Пиши по существу, без вводных фраз и воды. Если переписки слишком мало для содержательного саммари (например, пара реплик не по делу) - так и скажи коротко, не выдумывай содержание."""


def load_personality() -> str:
    with open("personality.txt", "r", encoding="utf-8") as f:
        return f.read()


def _build_system_prompt(topic_name: str | None = None, topic_focus: str | None = None) -> str:
    base = load_personality()
    if topic_name:
        base += f"\n\nТЕКУЩАЯ ВЕТКА\nСейчас разговор происходит в теме \"{topic_name}\""
        if topic_focus:
            base += f" ({topic_focus})"
        base += ". Держи фокус ответа в контексте этой темы."
    return base


def _messages_to_yandex_format(system_prompt: str, history: list[tuple[str, str | None, str]]) -> list[dict]:
    """Превращает историю (role, author, content) в формат messages для YandexGPT."""
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


async def _call_completion(messages: list[dict], max_tokens: str = "600", temperature: float = 0.7) -> str:
    payload = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/{YANDEX_MODEL}",
        "completionOptions": {
            "stream": False,
            "temperature": temperature,
            "maxTokens": max_tokens,
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


async def generate_reply(
    history: list[tuple[str, str | None, str]],
    topic_name: str | None = None,
    topic_focus: str | None = None,
) -> str:
    system_prompt = _build_system_prompt(topic_name, topic_focus)
    messages = _messages_to_yandex_format(system_prompt, history)
    return await _call_completion(messages)


async def generate_summary(
    history: list[tuple[int, str, str | None, str]],
    topic_name: str = "Общее",
) -> str:
    """history - список (id, role, author, content), как из get_messages_since."""
    if not history:
        return "С прошлого саммари новых сообщений не было."

    lines = []
    for _id, role, author, content in history:
        if role == "assistant":
            lines.append(f"Люмен (бот): {content}")
        else:
            lines.append(f"{author or 'кто-то'}: {content}")

    transcript = "\n".join(lines)
    system_prompt = SUMMARY_SYSTEM_PROMPT.format(topic_name=topic_name)
    messages = [
        {"role": "system", "text": system_prompt},
        {"role": "user", "text": transcript},
    ]
    return await _call_completion(messages, max_tokens="1200", temperature=0.3)


FOLLOWUP_INSTRUCTION = """
Дополнительная задача: час назад в переписке прозвучало сообщение, которое осталось без ответа. Напиши короткую (1-2 предложения) реплику в своём голосе, которая мягко возвращает внимание к нему - не отчитывай, не дави, просто аккуратно обозначь, что это всё ещё висит. Обратись к автору по имени, но не выдумывай отчество или фамилию - используй только то имя, что дано.

Сообщение: "{content}"
Автор: {author}
"""

MORNING_INSTRUCTION = """
Дополнительная задача: напиши короткое утреннее послание (2-4 предложения) своей команде - приветствие и напутствие на день, можно с лёгкой аффирмацией. В своём голосе, без дежурных пожеланий продуктивного дня и без канцелярита.
"""

EVENING_PARAGRAPH_INSTRUCTION = """
Дополнительная задача: перед тобой кусок переписки из ветки "{topic_name}" за день. Напиши по ней ОДИН связный абзац (3-6 предложений) в своём голосе - не структурированный список, а цельное повествование о том, что происходило в этой ветке. Если переписки почти нет или она не по делу - напиши короткую фразу в духе "в этой ветке сегодня было тихо", не выдумывай содержание.
"""


async def generate_followup_nudge(author: str, content: str) -> str:
    system_prompt = load_personality() + "\n\n" + FOLLOWUP_INSTRUCTION.format(content=content, author=author)
    messages = [
        {"role": "system", "text": system_prompt},
        {"role": "user", "text": "Напиши реплику."},
    ]
    return await _call_completion(messages, max_tokens="300", temperature=0.8)


async def generate_morning_message() -> str:
    system_prompt = load_personality() + "\n\n" + MORNING_INSTRUCTION
    messages = [
        {"role": "system", "text": system_prompt},
        {"role": "user", "text": "Доброе утро."},
    ]
    return await _call_completion(messages, max_tokens="300", temperature=0.9)


async def generate_evening_paragraph(history: list[tuple[int, str, str | None, str]], topic_name: str) -> str:
    lines = []
    for _id, role, author, content in history:
        if role == "assistant":
            lines.append(f"Люмен: {content}")
        else:
            lines.append(f"{author or 'кто-то'}: {content}")
    transcript = "\n".join(lines)

    system_prompt = load_personality() + "\n\n" + EVENING_PARAGRAPH_INSTRUCTION.format(topic_name=topic_name)
    messages = [
        {"role": "system", "text": system_prompt},
        {"role": "user", "text": transcript},
    ]
    return await _call_completion(messages, max_tokens="500", temperature=0.7)
