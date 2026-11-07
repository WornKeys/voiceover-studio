"""Fit to length: rewrite the approved script so it fills the target duration of the video."""

from __future__ import annotations

from pydantic import BaseModel, Field

from voiceover_studio.core.script import LANGUAGE_NAMES, parse_reply
from voiceover_studio.core.text import target_words, word_count
from voiceover_studio.plugins.base import Plugin, PluginContext, Stage
from voiceover_studio.providers.base import ChatMessage

REWRITE_PROMPT = """Rewrite this voiceover script to about {target} words (it has {current} now).
Keep the meaning, the order of ideas and the tone. {direction}
Keep it easy to read aloud: no headings, lists, markdown or stage directions. Write in {language}.
Reply with the rewritten script only.

Script:
{script}"""


class FitToLength(Plugin):
    name = "fit_to_length"
    title = "Fit to length"
    description = "Rewrites the script so the voiceover matches the target length of your video."
    stage = Stage.SCRIPT

    class Settings(BaseModel):
        tolerance_percent: int = Field(10, ge=5, le=30, description="How close to the target is close enough")
        max_attempts: int = Field(3, ge=1, le=4, description="Rewrites to try before keeping the closest one")

    def run(self, ctx: PluginContext, settings: BaseModel) -> PluginContext:
        assert isinstance(settings, FitToLength.Settings)
        if not ctx.target_seconds:
            ctx.notes.append("Fit to length: no target length set, so the script was left as it is.")
            return ctx

        target = target_words(ctx.target_seconds, ctx.words_per_minute)
        tolerance = target * settings.tolerance_percent / 100
        best, best_gap = ctx.script, abs(word_count(ctx.script) - target)
        if best_gap <= tolerance:
            ctx.notes.append(f"Fit to length: already about {target} words, no change needed.")
            return ctx

        for _ in range(settings.max_attempts):
            current = word_count(best)
            reply = ctx.llm.complete(
                [
                    ChatMessage(
                        "user",
                        REWRITE_PROMPT.format(
                            target=target,
                            current=current,
                            direction="Shorten it."
                            if current > target
                            else "Expand it with relevant detail.",
                            language=LANGUAGE_NAMES.get(ctx.language, ctx.language),
                            script=best,
                        ),
                    )
                ],
                max_tokens=max(256, target * 3),
                temperature=0.4,
            )
            candidate = parse_reply(reply)
            gap = abs(word_count(candidate) - target)
            if gap < best_gap:
                best, best_gap = candidate, gap
            if best_gap <= tolerance:
                break

        ctx.notes.append(
            f"Fit to length: {word_count(ctx.script)} → {word_count(best)} words (target {target})."
            + ("" if best_gap <= tolerance else " Closest result kept; review it before generating.")
        )
        ctx.script = best
        return ctx
