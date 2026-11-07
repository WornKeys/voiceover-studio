"""Script writing: turn a video description into a voiceover script the user can edit and approve."""

from __future__ import annotations

import re
from dataclasses import dataclass

from voiceover_studio.core.text import estimate_seconds, target_words, word_count
from voiceover_studio.providers.base import ChatMessage, LLMProvider

LANGUAGE_NAMES = {
    "en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "de": "German",
    "fr": "French", "ru": "Russian", "pt": "Portuguese", "es": "Spanish", "it": "Italian",
}  # fmt: skip

SYSTEM_PROMPT = (
    "You write voiceover scripts that a person will read aloud, in their own voice, over their own video."
    + """

Rules:
- Write only the words to be spoken. No titles, headings, bullet points, markdown, emojis, scene or camera
  directions, sound effects or speaker labels.
- Use short, clear sentences that are easy to say out loud. Write numbers, symbols and abbreviations the way
  they should be spoken.
- Aim for about {words} words ({seconds} seconds at {wpm} words per minute).
- Write in {language}.
- The narrator speaks as themselves. Never impersonate or put words in the mouth of a real, named person, and
  never write deceptive content such as fake news, scams or fabricated quotes. If the request asks for that,
  reply with exactly one line: REFUSED: <short reason>"""
)

USER_PROMPT = """Video description:
{description}

Audience: {audience}
Tone: {tone}
Target length: about {seconds} seconds."""

# Checked before calling the model: obvious requests to speak as someone else.
_IMPERSONATION = re.compile(
    r"\b(impersonat\w*|pretend(?:ing)? to be|posing as|in the voice of|as if (?:i|you) (?:were|was))\b",
    re.IGNORECASE,
)


class ScriptRefusedError(ValueError):
    """The request asks for something the tool doesn't do (e.g. speaking as a real, named person)."""


@dataclass(frozen=True)
class ScriptRequest:
    description: str
    target_seconds: float
    audience: str = "general viewers"
    tone: str = "friendly and clear"
    language: str = "en"


@dataclass(frozen=True)
class ScriptDraft:
    text: str
    words: int
    estimated_seconds: float


def check_request(request: ScriptRequest) -> None:
    text = " ".join([request.description, request.audience, request.tone])
    if match := _IMPERSONATION.search(text):
        raise ScriptRefusedError(
            f"This tool writes scripts you read as yourself, so it can't help with '{match.group(0)}'."
        )


def build_messages(request: ScriptRequest, words_per_minute: int) -> list[ChatMessage]:
    seconds = round(request.target_seconds)
    system = SYSTEM_PROMPT.format(
        words=target_words(request.target_seconds, words_per_minute),
        seconds=seconds,
        wpm=words_per_minute,
        language=LANGUAGE_NAMES.get(request.language, request.language),
    )
    user = USER_PROMPT.format(
        description=request.description.strip(),
        audience=request.audience,
        tone=request.tone,
        seconds=seconds,
    )
    return [ChatMessage("system", system), ChatMessage("user", user)]


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_SPEAKER_LABEL = re.compile(r"^\s*(?:narrator|voice[- ]?over|vo|speaker|host)\s*:\s*", re.IGNORECASE)
_LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_DIRECTION = re.compile(r"\[[^\]]*\]")


def clean_script(raw: str) -> str:
    """Strip what a model sometimes adds around the spoken words (reasoning, markdown, labels, directions)."""
    text = _THINK.sub("", raw)
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("#"):
            continue
        stripped = stripped.replace("**", "").replace("__", "")
        stripped = _LIST_MARKER.sub("", stripped)
        stripped = _SPEAKER_LABEL.sub("", stripped)
        stripped = _DIRECTION.sub("", stripped)
        lines.append(" ".join(stripped.split()))
    paragraphs = re.split(r"\n{2,}", "\n".join(lines).strip())
    return "\n\n".join(" ".join(p.split()) for p in paragraphs if p.strip())


def parse_reply(raw: str) -> str:
    text = clean_script(raw)
    if text.upper().startswith("REFUSED:"):
        raise ScriptRefusedError(text.split(":", 1)[1].strip() or "The request was refused.")
    if not text:
        raise ValueError("The model returned an empty script. Try again or adjust the description.")
    return text


def draft_from_text(text: str, words_per_minute: int) -> ScriptDraft:
    return ScriptDraft(text, word_count(text), estimate_seconds(text, words_per_minute))


def generate_script(
    llm: LLMProvider, request: ScriptRequest, *, words_per_minute: int, temperature: float
) -> ScriptDraft:
    check_request(request)
    words = target_words(request.target_seconds, words_per_minute)
    raw = llm.complete(
        build_messages(request, words_per_minute),
        max_tokens=max(256, words * 3),
        temperature=temperature,
    )
    return draft_from_text(parse_reply(raw), words_per_minute)
