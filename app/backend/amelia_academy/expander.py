"""A person writes a little and the model writes it out. The result is a suggestion: nothing is saved until a person takes it."""

import re

from . import agents, console, projects

MAX_CHARS = 2000
SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

# What each field is for, in the agent's folder. A story may grow; anything else only says better what the person already said.
FIELDS = agents.table("text_expander", "fields")
MAY_GROW = {"identity"}
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def expand(llm, field: str, text: str, language: str = "en", context: str = "") -> str:
    if field not in FIELDS:
        raise ValueError(f"unknown field: {field}")
    text = text.strip()
    if not text:
        raise ValueError("write something first")
    may_grow = field in MAY_GROW
    background = "\n" + agents.prompt("text_expander", "context", context=context.strip()) + "\n" if context.strip() else ""
    prompt = agents.prompt("text_expander", "expand", purpose=FIELDS[field], language=projects.LANGUAGE_NAME.get(language, language),
                           rule=agents.prompt("text_expander", "keep_facts" if may_grow else "keep_meaning"), background=background, draft=text)
    result = ""
    for attempt in range(2):
        with console.acting("text_expander"):
            result = str(llm.complete_json(prompt, SCHEMA, temperature=0.4).get("text", "")).strip()
        if result and result.casefold() != text.casefold():
            break
    if result and result.casefold() == text.casefold():
        raise ValueError("Nothing to add")
    if not result:
        raise ValueError("the model wrote nothing")
    if len(result) > MAX_CHARS:
        raise ValueError(f"the model wrote {len(result)} characters; the limit is {MAX_CHARS}")
    added = set(NUMBER.findall(result)) - set(NUMBER.findall(f"{text} {context}"))
    if added and not may_grow:
        raise ValueError(f"the model added numbers you did not write: {', '.join(sorted(added))}")
    return result
