"""Check the model's answer before anything is posted.

Every check is conservative: when in doubt the story is skipped. A missed
story costs nothing; an invented fact can cost a defamation case.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

CYRILLIC = re.compile(r"[Ѐ-ӿ]")
UPPER = "A-ZА-ЯЃЌЉЊЏЅЈЀЍ"
# Tokens that end with a dot but do not end a sentence.
ABBREVIATIONS = {
    "г.", "гр.", "д-р.", "др.", "м-р.", "проф.", "ул.", "бр.", "св.", "т.е.",
    "т.н.", "сл.", "с.", "мил.", "илј.", "ден.", "мин.", "км.", "ст.", "пр.",
}
# Common words that start a sentence with a capital letter but are not names.
SENTENCE_STARTERS = {
    "во", "на", "од", "за", "со", "по", "пред", "кај", "според", "иако",
    "откако", "поради", "така", "денеска", "вчера", "утре", "сите", "двајца",
    "тројца", "еден", "една", "едно", "над", "околу", "уште", "без", "меѓу",
}
BANNED_OPENERS = [
    r"^ов(а|аа|ој|ие) (вест|статија|напис|текст)",
    r"^(веста|написот|статијата|текстот|насловот)\b",
    r"^(според|во|од) (веста|написот|статијата|текстот|насловот)\b",
    r"^(накратко|резиме|одговор|факт|вест)\s*:",
]
BANNED_ANYWHERE = [r"кликн", r"#"]


class LLMFormatError(ValueError):
    """The model did not return usable JSON."""


def parse_llm_json(raw: str) -> dict[str, Any]:
    """Pull the JSON object out of a model reply (tolerates ``` fences, <think>)."""
    raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise LLMFormatError("no JSON object in reply")
    try:
        data = json.loads(raw[start : end + 1])
    except ValueError as e:
        raise LLMFormatError(f"invalid JSON: {e}") from e
    if not isinstance(data, dict) or data.get("status") not in ("OK", "SKIP"):
        raise LLMFormatError("missing or bad 'status'")
    for key in ("sentence", "evidence", "scope", "reason"):
        data[key] = str(data.get(key) or "").strip()
    return data


def normalize(text: str) -> str:
    """Lower-case, unify quotes/dashes/spaces so copied text compares equal."""
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[„“”«»\"‘’'`]", '"', text)
    text = re.sub(r"[–—−‑]", "-", text)
    text = text.replace(" ", " ").replace("…", "...")
    return re.sub(r"\s+", " ", text).strip()


def count_graphemes(text: str) -> int:
    """Approximate user-visible characters (ignores combining marks)."""
    return sum(1 for ch in unicodedata.normalize("NFC", text)
               if not unicodedata.category(ch).startswith("M"))


def _numbers(text: str) -> set[str]:
    return {re.sub(r"\D", "", n) for n in re.findall(r"\d+(?:[.,]\d+)*", text)}


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return cp >= 0x1F000 or 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF


def sentence_errors(sentence: str, max_chars: int, min_cyrillic: float) -> list[str]:
    """Format rules: one sentence, Cyrillic, length, no intro/emoji/question."""
    errors: list[str] = []
    s = sentence.strip()
    if not s:
        return ["empty sentence"]
    if len(s) > max_chars:
        errors.append(f"too long ({len(s)} > {max_chars} chars)")
    if "\n" in s:
        errors.append("contains a line break")
    if "?" in s:
        errors.append("contains a question mark")
    if not re.search(r"[.!][\"“”»’)]*$", s):
        errors.append("does not end with . or !")
    for m in re.finditer(rf"[.!…][\"“”»’)]*\s+(?=[\"„“«(]?[{UPPER}])", s):
        token = s[: m.start() + 1].split()[-1].lstrip("(\"„“«").lower()
        if token in ABBREVIATIONS or re.fullmatch(r"(\w\.)+", token):
            continue  # abbreviation or initials like "Б.А."
        errors.append("more than one sentence")
        break
    letters = [c for c in s if c.isalpha()]
    if letters:
        ratio = sum(1 for c in letters if CYRILLIC.match(c)) / len(letters)
        if ratio < min_cyrillic:
            errors.append(f"not enough Cyrillic ({ratio:.0%})")
    low = s.lower()
    if any(re.search(p, low) for p in BANNED_OPENERS):
        errors.append("starts with a banned intro")
    if any(re.search(p, low) for p in BANNED_ANYWHERE):
        errors.append("contains a banned word/hashtag")
    if any(_is_emoji(c) for c in s):
        errors.append("contains emoji")
    return errors


def _name_in_article(word: str, article: str, art_norm: str) -> bool:
    if len(word) > 1 and word.isupper():  # acronym (МВР, ЕУ): exact match
        return word in article
    # Macedonian inflects names and places ("Тетово" / "Тетовско",
    # "Бугарија" / "Бугарите"), so compare a stem: drop up to 3 trailing
    # letters, keep at least 4.
    stem = word.lower() if len(word) <= 4 else word.lower()[: max(4, len(word) - 3)]
    return re.search(rf"(?<!\w){re.escape(stem)}", art_norm) is not None


def unsupported_facts(sentence: str, article: str) -> list[str]:
    """Numbers and names in the sentence that do not appear in the article.

    The first word is skipped: it is capitalized even when it is a verb
    ("Уапсени…"). See first_word_warning().
    """
    errors: list[str] = []
    missing_numbers = _numbers(sentence) - _numbers(article)
    if missing_numbers:
        errors.append(f"numbers not in article: {sorted(missing_numbers)}")
    art = normalize(article)
    words = re.findall(r"[\w-]+", sentence)
    missing = [w for w in words[1:]
               if w[0].isupper() and not w.isdigit() and not _name_in_article(w, article, art)]
    if missing:
        errors.append(f"names not in article: {missing}")
    return errors


def first_word_warning(sentence: str, article: str) -> str | None:
    """A note for the human reviewer (not a rejection): the opening word is not
    in the article. Harmless for a verb, but it could be an invented name."""
    words = re.findall(r"[\w-]+", sentence)
    if not words or words[0].lower() in SENTENCE_STARTERS or words[0].isdigit():
        return None
    if _name_in_article(words[0], article, normalize(article)):
        return None
    return f"check first word '{words[0]}' (not in article)"


def check(result: dict[str, Any], article: str, cfg: dict[str, Any]) -> list[str]:
    """All checks for an OK answer. Empty list = safe to draft."""
    if result.get("status") != "OK":
        return [f"model SKIP: {result.get('reason', '')}"]
    errors = sentence_errors(
        result["sentence"], cfg["max_sentence_chars"], cfg["min_cyrillic_ratio"]
    )
    evidence = normalize(result.get("evidence", "")).rstrip(" .!…")
    if len(evidence) < cfg["min_evidence_chars"]:
        errors.append("evidence missing or too short")
    elif evidence not in normalize(article):
        errors.append("evidence not found verbatim in article")
    errors += unsupported_facts(result["sentence"], article)
    if result.get("scope") == "WORLD":
        errors.append("world news (out of scope)")
    return errors
