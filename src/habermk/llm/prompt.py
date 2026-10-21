"""The prompt. Instructions in English, output in Macedonian Cyrillic.

The few-shot examples are hand-written illustrations of the format only.
Their Macedonian should be checked by a native speaker before going live.
"""
from __future__ import annotations

import json

SYSTEM_PROMPT = """\
You write for a Macedonian anti-clickbait news channel.
You get a HEADLINE (often clickbait) and the FULL ARTICLE TEXT.

Task: find the concrete fact the headline withholds — who, what number, what \
decision, where — and state it as ONE declarative sentence in standard \
Macedonian (Cyrillic script).

Rules:
- Use ONLY facts explicitly stated in the article text. Never add knowledge, \
names, numbers, dates or places from elsewhere.
- Attribute claims and accusations to their source ("според МВР", "тврди \
Мицкоски", "соопшти Обвинителството"). Never present an accusation as fact.
- Name suspects and victims exactly as the text does (usually initials).
- One sentence, at most 220 characters, ending with a period.
- No introduction ("Оваа вест…", "Според статијата…", "Во текстот…"), no \
question, no emoji, no hashtags, no quotes around the whole sentence.
- Standard Macedonian literary language, Cyrillic. Latin only for proper names \
that the text itself writes in Latin.
- "evidence": copy, character for character, the ONE sentence from the \
article text that proves your answer.
- "scope": MK if the story is about North Macedonia, REGION if about another \
Balkan country, WORLD otherwise.
- Return status "SKIP" (with an empty sentence) if the withheld fact is not in \
the text, the text is not a news article, or it is only a teaser/video/gallery.

Reply with JSON only:
{"status": "OK" or "SKIP", "sentence": "...", "evidence": "...", \
"scope": "MK" or "REGION" or "WORLD", "reason": "short English note"}
"""

# (headline, article excerpt, expected JSON). Illustrative, not real events.
FEW_SHOT = [
    (
        "Познат скопски ресторан затворен – ова е причината",
        "Државниот пазарен инспекторат го затвори ресторанот „Кај Јане“ во "
        "Карпош. Според инспекторатот, објектот работел без санитарна "
        "дозвола. Забраната важи 30 дена.",
        {
            "status": "OK",
            "sentence": "Пазарниот инспекторат го затвори ресторанот „Кај Јане“ "
                        "во Карпош на 30 дена поради работа без санитарна дозвола.",
            "evidence": "Според инспекторатот, објектот работел без санитарна дозвола.",
            "scope": "MK",
            "reason": "reason for closure withheld in headline",
        },
    ),
    (
        "Погледнете што се случи на патот кон Тетово",
        "Погледнете го видеото подолу. Возачите се замолени да возат внимателно.",
        {
            "status": "SKIP",
            "sentence": "",
            "evidence": "",
            "scope": "MK",
            "reason": "the text does not say what happened",
        },
    ),
]


def user_message(headline: str, outlet: str, text: str) -> str:
    return f"HEADLINE: {headline}\nOUTLET: {outlet}\n\nFULL ARTICLE TEXT:\n{text}"


def build_messages(headline: str, outlet: str, text: str) -> list[dict[str, str]]:
    """Chat messages: few-shot pairs first, then the real article."""
    messages: list[dict[str, str]] = []
    for ex_headline, ex_text, ex_answer in FEW_SHOT:
        messages.append({"role": "user", "content": user_message(ex_headline, "пример", ex_text)})
        messages.append({"role": "assistant", "content": json.dumps(ex_answer, ensure_ascii=False)})
    messages.append({"role": "user", "content": user_message(headline, outlet, text)})
    return messages


RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["OK", "SKIP"]},
        "sentence": {"type": "string"},
        "evidence": {"type": "string"},
        "scope": {"type": "string", "enum": ["MK", "REGION", "WORLD"]},
        "reason": {"type": "string"},
    },
    "required": ["status", "sentence", "evidence", "scope", "reason"],
    "additionalProperties": False,
}
