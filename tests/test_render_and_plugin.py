import json
from pathlib import Path

import pytest

from tests.fakes import FakeLLM, FakeTTS, FakeWatermarker
from voiceover_studio.core.audio import read_wav, read_wav_info
from voiceover_studio.core.config import load_config
from voiceover_studio.core.render import RenderError, render_voiceover
from voiceover_studio.core.text import word_count
from voiceover_studio.plugins import FitToLength, PluginContext, UnknownPluginError, enabled_plugins
from voiceover_studio.providers.base import VoiceReference

CFG = load_config(environ={})
VOICE = VoiceReference(Path("voice.wav"), "consent sentence", consent_id="c-123")
SCRIPT = "Welcome to the lab. Today we build a voiceover studio. It runs in your own AWS account."


def test_render_writes_watermarked_labelled_audio_captions_and_manifest(tmp_path):
    tts, wm = FakeTTS(), FakeWatermarker()
    progress = []
    result = render_voiceover(
        SCRIPT, VOICE, "en", tts, wm, CFG, tmp_path, lambda d, t, _: progress.append((d, t))
    )

    assert result.chunks == 3 and tts.spoken[0] == "Welcome to the lab."
    assert progress[-1] == (3, 3)
    assert "AI-generated" in read_wav_info(result.wav_path)["ICMT"]
    assert wm.detect(read_wav(result.wav_path)) == 1.0
    assert result.srt_path.read_text(encoding="utf-8").count("-->") == 3
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["voice_consent_id"] == "c-123" and manifest["watermark"]["method"] == "fake"


def test_render_refuses_without_consent_or_with_unsupported_language(tmp_path):
    no_consent = VoiceReference(Path("v.wav"), "t", consent_id="")
    with pytest.raises(RenderError, match="consent"):
        render_voiceover(SCRIPT, no_consent, "en", FakeTTS(), FakeWatermarker(), CFG, tmp_path)
    with pytest.raises(RenderError, match="doesn't support 'hi'"):
        render_voiceover(SCRIPT, VOICE, "hi", FakeTTS(), FakeWatermarker(), CFG, tmp_path)


def _ctx(script: str, llm: FakeLLM, target_seconds: float | None = 20) -> PluginContext:
    return PluginContext(
        script=script,
        language="en",
        target_seconds=target_seconds,
        words_per_minute=150,
        llm=llm,
        tts=FakeTTS(),
    )


def test_fit_to_length_expands_until_close_to_target():
    replies = iter(["word " * 30 + ".", "word " * 48 + "."])  # target: 20 s at 150 wpm = 50 words
    ctx = FitToLength().run(_ctx(SCRIPT, FakeLLM(lambda _m: next(replies))), FitToLength.Settings())
    assert word_count(ctx.script) == 48
    assert "target 50" in ctx.notes[-1]


def test_fit_to_length_keeps_closest_attempt_and_says_so():
    ctx = FitToLength().run(_ctx(SCRIPT, FakeLLM("word " * 25 + ".")), FitToLength.Settings(max_attempts=2))
    assert word_count(ctx.script) == 25
    assert "review it" in ctx.notes[-1]


def test_fit_to_length_skips_without_target_or_when_already_close():
    llm = FakeLLM("unused")
    assert "no target" in FitToLength().run(_ctx(SCRIPT, llm, None), FitToLength.Settings()).notes[-1]
    close = "word " * 50 + "."
    assert "no change" in FitToLength().run(_ctx(close, llm), FitToLength.Settings()).notes[-1]
    assert llm.calls == []


def test_plugins_setting_is_parsed_and_validated():
    assert enabled_plugins(" fit_to_length ") == [FitToLength]
    assert enabled_plugins("") == []
    with pytest.raises(UnknownPluginError, match="translate"):
        enabled_plugins("fit_to_length,translate")
