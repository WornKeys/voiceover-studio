"""Translate: turn the approved script into another language the voice model can speak.

A worked example for docs/plugins.md. It shows the three things most plugins need:
- settings whose choices depend on the providers (the target languages come from the TTS capabilities),
- a call to the `llm` port, whatever model or vendor is behind it,
- checks on the model's answer, with plain-language notes instead of silent failures.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from voiceover_studio.core.script import LANGUAGE_NAMES, parse_reply
from voiceover_studio.core.text import estimate_seconds, word_count
from voiceover_studio.plugins.base import Plugin, PluginContext, Stage
from voiceover_studio.providers.base import ChatMessage, TTSCapabilities

SYSTEM_PROMPT = """You translate voiceover scripts. A text-to-speech voice will read your translation aloud.

Rules:
- Translate from {source} into {target}. Keep the meaning, the tone and the paragraph breaks.
- Write naturally, the way a native {target} speaker would say it, not word for word.
- Write numbers, symbols and abbreviations the way they are spoken in {target}.
- Keep these terms exactly as written: {keep_terms}.
- Reply with the translated script only: no notes, titles, quotation marks around it or explanations."""

# Letters a translation into these languages must mostly be written in (a cheap "did it translate?" check).
_SCRIPTS = {
    "zh": "[" + chr(0x4E00) + "-" + chr(0x9FFF) + chr(0x3400) + "-" + chr(0x4DBF) + "]",
    "ja": "[" + chr(0x3040) + "-" + chr(0x30FF) + chr(0x4E00) + "-" + chr(0x9FFF) + "]",
    "ko": "[" + chr(0xAC00) + "-" + chr(0xD7AF) + "]",
    "ru": "[" + chr(0x0400) + "-" + chr(0x04FF) + "]",
}
MIN_SCRIPT_SHARE = 0.3


def _paragraphs(text: str) -> int:
    return len([p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()])


def _written_in(text: str, language: str) -> bool:
    pattern = _SCRIPTS.get(language)
    if pattern is None:
        return True  # Latin-script languages: checked by "did the text change" instead
    letters = sum(ch.isalpha() for ch in text)
    return letters > 0 and len(re.findall(pattern, text)) / letters >= MIN_SCRIPT_SHARE


def _name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


class Translate(Plugin):
    name = "translate"
    title = "Translate"
    description = (
        "Translates the script into another language your voice model can speak. "
        "Your cloned voice reads it; the accent may differ from a native speaker's."
    )
    stage = Stage.SCRIPT

    class Settings(BaseModel):
        target_language: str = Field("es", description="Translate into")
        keep_terms: str = Field(
            "", max_length=500, description="Words to keep as they are, comma-separated (e.g. product names)"
        )

    @classmethod
    def settings_schema(cls, tts: TTSCapabilities | None = None) -> dict[str, Any]:
        schema = cls.Settings.model_json_schema()
        languages = list(tts.languages) if tts else list(LANGUAGE_NAMES)
        prop = schema["properties"]["target_language"]
        prop["enum"] = languages
        if prop.get("default") not in languages:
            prop["default"] = next((code for code in languages if code != "en"), languages[0])
        return schema

    def run(self, ctx: PluginContext, settings: BaseModel) -> PluginContext:
        assert isinstance(settings, Translate.Settings)
        target, source = settings.target_language, ctx.language
        languages = ctx.tts.capabilities().languages
        if target not in languages:
            raise ValueError(
                f"The voice model can't speak '{target}'. Choose one of: {', '.join(languages)}."
            )
        if target == source:
            ctx.notes.append(f"Translate: the script is already in {_name(target)}, so nothing changed.")
            return ctx

        terms = [t.strip() for t in settings.keep_terms.split(",") if t.strip()]
        system = SYSTEM_PROMPT.format(
            source=_name(source), target=_name(target), keep_terms=", ".join(terms) or "(none)"
        )
        words = word_count(ctx.script)
        reply = ctx.llm.complete(
            [ChatMessage("system", system), ChatMessage("user", ctx.script)],
            # Translations can need more tokens per word than English (e.g. Chinese, Japanese).
            max_tokens=max(512, words * 4),
            temperature=0.2,
        )
        translated = parse_reply(reply)
        if not _written_in(translated, target) or translated.casefold() == ctx.script.casefold():
            raise ValueError(f"The model didn't return a {_name(target)} translation. Try again.")

        new_words = word_count(translated)
        seconds = estimate_seconds(translated, ctx.words_per_minute)
        ctx.notes.append(
            f"Translate: {_name(source)} → {_name(target)}, {words} → {new_words} words "
            f"(about {seconds:.0f} s). Captions will be in {_name(target)} too."
        )
        if _paragraphs(translated) != _paragraphs(ctx.script):
            ctx.notes.append("The paragraph breaks changed; check where the pauses fall.")
        if missing := [t for t in terms if t not in translated]:
            ctx.notes.append(f"These terms were changed by the translation: {', '.join(missing)}.")
        if ctx.target_seconds and abs(seconds - ctx.target_seconds) > 0.15 * ctx.target_seconds:
            ctx.notes.append(
                f"It's now about {seconds:.0f} s for a {ctx.target_seconds:.0f} s target. "
                "Edit it, or translate a shorter or longer version."
            )
        if target in ("zh", "ja"):
            ctx.notes.append("Length estimates for Chinese and Japanese are rough (based on characters).")

        ctx.script, ctx.language = translated, target
        return ctx
