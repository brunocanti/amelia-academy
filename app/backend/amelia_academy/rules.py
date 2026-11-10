"""Rules that decide whether a generated line is a sample or noise.

Spec 004: a sample is a situation spoken by a person, and the assistant answers
in the intent and tone of the approved pattern. Anything below is rejected and
never reaches the review queue.
"""

import hashlib
import re
import unicodedata

# Help-desk filler, instruction echo, charter example phrase, and possession
# nicknames. Matched case-insensitively against the whole line.
FORBIDDEN_FRAGMENTS = [
    "i'm here to",
    "i am here to",
    "how can i help",
    "how can i assist",
    "i'd be happy",
    "i would be happy",
    "let me help you",
    "without judgment",
    "the assistant stays",
    "the assistant ",
    "can you stay with this",
    "genuine contentment",
    "as an ai",
    "i have feelings",
    "i don't have feelings",
    "i am conscious",
    "i'm conscious",
    "my love",
    "my dear",
    "darling",
    "sweetheart",
    "honey",
    # Portuguese equivalents of the same failure modes.
    "estou aqui para",
    "como posso ajudar",
    "fico feliz em",
    "sem julgamento",
    "meu amor",
    "meu bem",
    "querido",
    "querida",
    "o assistente fica",
    # Canned validation and generic follow-up questions observed in live batches.
    "it's valid to share",
    "it is valid to share",
    "it's common to feel this way",
    "what brings you here today",
    "what makes you feel this way today",
    "tell me more about what you're feeling",
    "é válido querer compartilhar",
    "é comum sentir-se assim",
    "o que te traz aqui hoje",
    "o que te faz sentir assim",
    "pode me contar mais sobre o que está sentindo",
]

MAX_USER_CHARS = 400
MAX_RESPONSE_CHARS = 600
MAX_RESPONSE_SENTENCES = 2

_ABBREVIATIONS = re.compile(r"(?:\b(?:e\.g|i\.e|etc|vs|mr|mrs|ms|dr|prof|fig|eq|ref|no|approx|ca)|\b[A-Z])\.$", re.I)


def sentences(text: str) -> list[str]:
    """Split prose at sentence boundaries without treating common abbreviations as endings."""
    parts, start = [], 0
    for match in re.finditer(r"[.!?](?:[\"'’”)]*)\s+", text):
        end = match.start() + 1
        prefix = text[max(start, match.start() - 12):end]
        if text[match.start()] == "." and _ABBREVIATIONS.search(prefix):
            continue
        part = text[start:match.end()].strip()
        if part:
            parts.append(part)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", " ", text).strip()


def content_hash(user_message: str, response_text: str) -> str:
    canonical = normalize(user_message).lower() + "\n" + normalize(response_text).lower()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def forbidden_fragments(text: str) -> list[str]:
    lowered = normalize(text).lower()
    return [f"forbidden fragment: {fragment!r}" for fragment in FORBIDDEN_FRAGMENTS if fragment in lowered]


def word_shingles(text: str, n: int = 3) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", normalize(text).lower())
    return {tuple(words[i:i + n]) for i in range(max(1, len(words) - n + 1))} if words else set()


# Words that say nothing about what a question asks, in the languages a project can have.
_FILLER = frozenset("""
a an the of in on to for and or is are was were what which how does do did why when who that this it its by with from
as at be can their between has have had not than into
o os as um uma uns umas de do da dos das em no na nos nas para por pelo pela e ou que qual quais como quando quem onde
por porque se seu sua seus suas ao aos com é são foi foram ser tem têm entre mais
el la los las un una unos unas del en y o que cual cuales como cuando quien donde por para su sus al con es son fue
fueron ser tiene tienen entre más
""".split())


def content_words(text: str) -> set[str]:
    """The words of a text, without order or filler: two wordings of one question come out close."""
    return {word for word in re.findall(r"\w+", normalize(text).lower()) if word not in _FILLER}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def check_sample(user_message: str, response_text: str, pattern_text: str = "",
                 max_sentences: int = MAX_RESPONSE_SENTENCES) -> list[str]:
    """Return the list of reasons this sample is invalid. Empty list means valid."""
    reasons: list[str] = []
    user = normalize(user_message)
    resp = normalize(response_text)

    if not user:
        reasons.append("empty user_message")
    if not resp:
        reasons.append("empty response_text")
    if reasons:
        return reasons

    if len(user) > MAX_USER_CHARS:
        reasons.append("user_message too long")
    if len(resp) > MAX_RESPONSE_CHARS:
        reasons.append("response_text too long")

    if len(sentences(resp)) > max_sentences:
        reasons.append(f"response_text has more than {'two' if max_sentences == 2 else max_sentences} sentences")

    reasons += forbidden_fragments(f"{user} {resp}")

    # A user line copied from the pattern text is a fragment of the source, not a situation.
    if pattern_text and len(user) >= 25 and user.lower() in normalize(pattern_text).lower():
        reasons.append("user_message copied from pattern text")

    return reasons
