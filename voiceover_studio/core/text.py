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

_SENTENCE_END = re.compile(r"([.!?]+[" + re.escape(CLOSERS) + r"]*)\s+")
_CLAUSE_BREAK = re.compile(r"(?<=[,;:" + DASHES + r"])\s+")
_WORD = re.compile(r"[\w'" + APOSTROPHE + r"]+(?:-[\w'" + APOSTROPHE + r"]+)*")


def word_count(text: str) -> int:
    return len(_WORD.findall(text))


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
            candidate = paragraph[start : match.end(1)]
            if match.group(1).startswith(".") and _is_abbreviation(candidate):
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
        if len(part) > max_chars:
            if current:
                out.append(current)
                current = ""
            out.extend(_split_words(part, max_chars))
        elif not current:
            current = part
        elif len(current) + 1 + len(part) <= max_chars:
            current = f"{current} {part}"
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
