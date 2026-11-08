"""Text helpers: sentence splitting, chunking for text-to-speech, word counts and duration estimates."""

from __future__ import annotations

import re

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs",
    "etc", "e.g", "i.e", "approx", "fig", "no", "inc", "ltd",
}  # fmt: skip
# Typographic characters that LLMs often produce, built with chr() so the source stays plain ASCII.
APOSTROPHE = chr(0x2019)  # right single quote
CLOSE_QUOTE = chr(0x201D)  # right double quote
DASHES = chr(0x2013) + chr(0x2014)  # en dash, em dash
CLOSERS = "\"')]" + APOSTROPHE + CLOSE_QUOTE

# Chinese and Japanese: full-width punctuation, written without a space after it.
CJK_SENTENCE_END = chr(0x3002) + chr(0xFF01) + chr(0xFF1F)  # ideographic full stop, full-width ! and ?
CJK_CLAUSE = chr(0xFF0C) + chr(0x3001) + chr(0xFF1B) + chr(0xFF1A)  # full-width comma, ideographic comma, ; :
CJK_CLOSERS = chr(0x300D) + chr(0x300F) + chr(0xFF09) + CLOSE_QUOTE  # corner brackets, full-width ), quote
# Kana and CJK ideographs. Hangul is not included: Korean puts spaces between words.
_CJK_CHAR = re.compile(
    "[" + chr(0x3040) + "-" + chr(0x30FF) + chr(0x3400) + "-" + chr(0x4DBF)
    + chr(0x4E00) + "-" + chr(0x9FFF) + chr(0xF900) + "-" + chr(0xFAFF) + "]"
)  # fmt: skip

_SENTENCE_END = re.compile(
    r"([.!?]+[" + re.escape(CLOSERS) + r"]*)\s+"
    r"|([" + CJK_SENTENCE_END + r"]+[" + re.escape(CJK_CLOSERS) + r"]*)\s*"
)
_CLAUSE_BREAK = re.compile(r"(?<=[,;:" + DASHES + r"])\s+|(?<=[" + CJK_CLAUSE + r"])\s*")
_WORD = re.compile(r"[\w'" + APOSTROPHE + r"]+(?:-[\w'" + APOSTROPHE + r"]+)*")


def word_count(text: str) -> int:
    """Spoken words. Chinese and Japanese have no spaces, so about two characters count as one word."""
    cjk_chars = len(_CJK_CHAR.findall(text))
    return len(_WORD.findall(_CJK_CHAR.sub(" ", text))) + (cjk_chars + 1) // 2


def _ends_cjk(text: str) -> bool:
    last = text[-1:]
    return bool(last) and (last in CJK_SENTENCE_END + CJK_CLAUSE + CJK_CLOSERS or bool(_CJK_CHAR.match(last)))


def _join(left: str, right: str) -> str:
    """Join two pieces of a sentence: with a space, except after Chinese or Japanese text."""
    return left + right if _ends_cjk(left) else f"{left} {right}"


def estimate_seconds(text: str, words_per_minute: int) -> float:
    return word_count(text) * 60.0 / words_per_minute


def target_words(seconds: float, words_per_minute: int) -> int:
    return max(1, round(seconds * words_per_minute / 60.0))


def _is_abbreviation(sentence: str) -> bool:
    words = sentence.split()
    if not words:
        return False
    last = words[-1].rstrip(CLOSERS).lower()
    if not last.endswith("."):
        return False
    stem = last.rstrip(".")
    return stem in _ABBREVIATIONS or (len(stem) == 1 and stem.isalpha())


def split_sentences(text: str) -> list[str]:
    """Split text into sentences. Blank lines always end a sentence (e.g. a line without punctuation)."""
    sentences: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = " ".join(paragraph.split())
        start = 0
        for match in _SENTENCE_END.finditer(paragraph):
            latin = match.group(1)
            candidate = paragraph[start : match.end(1) if latin else match.end(2)]
            if latin and latin.startswith(".") and _is_abbreviation(candidate):
                continue
            sentences.append(candidate.strip())
            start = match.end()
        if tail := paragraph[start:].strip():
            sentences.append(tail)
    return sentences


def _split_words(text: str, max_chars: int) -> list[str]:
    out: list[str] = []
    current = ""
    for word in text.split():
        while len(word) > max_chars:  # a single "word" longer than the limit (e.g. a URL)
            if current:
                out.append(current)
                current = ""
            out.append(word[:max_chars])
            word = word[max_chars:]
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= max_chars:
            current = f"{current} {word}"
        else:
            out.append(current)
            current = word
    if current:
        out.append(current)
    return out


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    out: list[str] = []
    current = ""
    for part in _CLAUSE_BREAK.split(sentence):
        if not part:
            continue
        if len(part) > max_chars:
            if current:
                out.append(current)
                current = ""
            out.extend(_split_words(part, max_chars))
        elif not current:
            current = part
        elif len(_join(current, part)) <= max_chars:
            current = _join(current, part)
        else:
            out.append(current)
            current = part
    if current:
        out.append(current)
    return out


def chunk_text(text: str, max_chars: int) -> list[str]:
    """One sentence per chunk (natural pauses, one caption each); long sentences split at clause breaks."""
    chunks: list[str] = []
    for sentence in split_sentences(text):
        if len(sentence) <= max_chars:
            chunks.append(sentence)
        else:
            chunks.extend(_split_long_sentence(sentence, max_chars))
    return chunks
