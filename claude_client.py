from anthropic import AsyncAnthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

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


def _build_system_prompt(
    topic_name: str | None = None,
    topic_focus: str | None = None,
    global_context: str | None = None,
    referenced_topic: tuple[str, list[tuple[str, str | None, str]]] | None = None,
) -> str:
    base = load_personality()
    if global_context:
        base += f"\n\nФОН ПО ОСТАЛЬНОМУ ЧАТУ (кратко, для общей картины, не пересказывай это дословно)\n{global_context}"
    if referenced_topic:
        ref_name, ref_history = referenced_topic
        lines = []
        for role, author, content in ref_history:
            if role == "assistant":
                lines.append(f"Люмен: {content}")
            else:
                lines.append(f"{author or 'кто-то'}: {content}")
        transcript = "\n".join(lines)
        base += (
            f"\n\nПО ЗАПРОСУ - СВЕЖЕЕ ИЗ ТЕМЫ \"{ref_name}\"\n{transcript}\n\n"
            f"Похоже, человек спрашивает именно про тему \"{ref_name}\" - используй это, чтобы ответить по существу, "
            f"а не отвечать в контексте текущей ветки."
        )
    if topic_name:
        base += f"\n\nТЕКУЩАЯ ВЕТКА\nСейчас разговор происходит в теме \"{topic_name}\""
        if topic_focus:
            base += f" ({topic_focus})"
        base += ". Держи фокус ответа в контексте этой темы."
    return base


def _messages_to_claude_format(history: list[tuple[str, str | None, str]]) -> list[dict]:
    """Превращает историю (role, author, content) в формат messages для Claude API."""
    messages: list[dict] = []

    for role, author, content in history:
        text = f"{author}: {content}" if role == "user" and author else content
        claude_role = "assistant" if role == "assistant" else "user"
        if messages and messages[-1]["role"] == claude_role:
            messages[-1]["content"] += "\n" + text
        else:
            messages.append({"role": claude_role, "content": text})

    if not messages or messages[-1]["role"] != "user":
        messages.append({"role": "user", "content": "(продолжай разговор)"})

    return messages


async def _call_completion(
    system_prompt: str,
    messages: list[dict],
    max_tokens: int = 800,
    temperature: float = 0.7,
) -> str:
    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=messages,
    )
    return "".join(block.text for block in response.content if block.type == "text")


async def generate_reply(
    history: list[tuple[str, str | None, str]],
    topic_name: str | None = None,
    topic_focus: str | None = None,
    global_context: str | None = None,
    referenced_topic: tuple[str, list[tuple[str, str | None, str]]] | None = None,
) -> str:
    system_prompt = _build_system_prompt(topic_name, topic_focus, global_context, referenced_topic)
    messages = _messages_to_claude_format(history)
    return await _call_completion(system_prompt, messages, max_tokens=800, temperature=0.7)


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
    messages = [{"role": "user", "content": transcript}]
    return await _call_completion(system_prompt, messages, max_tokens=1500, temperature=0.3)


FOLLOWUP_INSTRUCTION = """
Дополнительная задача: час назад в переписке прозвучало сообщение, которое осталось без ответа. Напиши короткую (1-2 предложения) реплику в своём голосе, которая мягко возвращает внимание к нему - не отчитывай, не дави, просто аккуратно обозначь, что это всё ещё висит. Обратись к автору по имени, но не выдумывай отчество или фамилию - используй только то имя, что дано.

Сообщение: "{content}"
Автор: {author}
"""

MORNING_INSTRUCTION = """
Дополнительная задача: напиши очень короткое утреннее послание своей команде - строго приветствие плюс ОДНО предложение-напутствие или аффирмация. Не больше двух коротких предложений суммарно. В своём голосе, без дежурных пожеланий продуктивного дня и без канцелярита. Не растягивай, не добавляй второе-третье предложение.
"""

EVENING_PARAGRAPH_INSTRUCTION = """
Дополнительная задача: перед тобой кусок переписки из ветки "{topic_name}" за день. Напиши по ней ОДИН связный абзац (3-6 предложений) в своём голосе - не структурированный список, а цельное повествование о том, что происходило в этой ветке. Если переписки почти нет или она не по делу - напиши короткую фразу в духе "в этой ветке сегодня было тихо", не выдумывай содержание.
"""


async def generate_followup_nudge(author: str, content: str) -> str:
    system_prompt = load_personality() + "\n\n" + FOLLOWUP_INSTRUCTION.format(content=content, author=author)
    messages = [{"role": "user", "content": "Напиши реплику."}]
    return await _call_completion(system_prompt, messages, max_tokens=300, temperature=0.8)


async def generate_morning_message() -> str:
    system_prompt = load_personality() + "\n\n" + MORNING_INSTRUCTION
    messages = [{"role": "user", "content": "Доброе утро."}]
    return await _call_completion(system_prompt, messages, max_tokens=150, temperature=0.9)


async def generate_evening_paragraph(history: list[tuple[int, str, str | None, str]], topic_name: str) -> str:
    lines = []
    for _id, role, author, content in history:
        if role == "assistant":
            lines.append(f"Люмен: {content}")
        else:
            lines.append(f"{author or 'кто-то'}: {content}")
    transcript = "\n".join(lines)

    system_prompt = load_personality() + "\n\n" + EVENING_PARAGRAPH_INSTRUCTION.format(topic_name=topic_name)
    messages = [{"role": "user", "content": transcript}]
    return await _call_completion(system_prompt, messages, max_tokens=500, temperature=0.7)


GLOBAL_CONTEXT_INSTRUCTION = """Ты помогаешь Люмену поддерживать компактную сквозную сводку по ВСЕМ веткам командного чата - это его общий фон, периферийное зрение, а НЕ подробный отчёт.

Текущая сводка (может быть пустой, если её ещё не было):
{previous_summary}

Новые сообщения по веткам с прошлого обновления:
{new_material}

Обнови сводку: впиши туда новое по существу, убери то, что уже неактуально (закрытые темы, решённые вопросы), сохрани компактность - не больше 6-8 предложений или коротких пунктов по темам. Пиши по-русски, связным текстом или короткими пунктами, без канцелярита. Если ничего значимого не произошло - оставь сводку как есть или сократи её."""


async def generate_global_context_update(previous_summary: str, new_material: str) -> str:
    system_prompt = "Ты помогаешь вести компактную сквозную сводку по чату."
    prompt = GLOBAL_CONTEXT_INSTRUCTION.format(
        previous_summary=previous_summary or "(пока пусто)",
        new_material=new_material,
    )
    messages = [{"role": "user", "content": prompt}]
    return await _call_completion(system_prompt, messages, max_tokens=400, temperature=0.4)
