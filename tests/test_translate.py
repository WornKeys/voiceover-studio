import pytest

from tests.fakes import FakeLLM, FakeTTS
from voiceover_studio.core.script import ScriptRefusedError
from voiceover_studio.plugins import PluginContext, Translate

SCRIPT = "Welcome to the lab.\n\nToday we deploy the studio to AWS."
SPANISH = "Bienvenidos al laboratorio.\n\nHoy desplegamos el estudio en AWS."
CHINESE = "欢迎来到实验室。\n\n今天我们部署。"


def _ctx(llm: FakeLLM, languages=("en", "es", "zh"), target_seconds: float | None = None) -> PluginContext:
    return PluginContext(
        script=SCRIPT,
        language="en",
        target_seconds=target_seconds,
        words_per_minute=150,
        llm=llm,
        tts=FakeTTS(languages=languages),
    )


def _run(ctx: PluginContext, **settings) -> PluginContext:
    return Translate().run(ctx, Translate.Settings(**settings))


def test_target_languages_come_from_the_voice_model():
    schema = Translate.settings_schema(FakeTTS(languages=("en", "de")).capabilities())
    prop = schema["properties"]["target_language"]
    assert prop["enum"] == ["en", "de"] and prop["default"] == "de"
    manifest = Translate.manifest(FakeTTS(languages=("en", "es")).capabilities())
    assert manifest["settings_schema"]["properties"]["target_language"]["default"] == "es"


def test_translates_switches_the_language_and_reports_what_it_did():
    llm = FakeLLM(SPANISH)
    ctx = _run(_ctx(llm), target_language="es", keep_terms="AWS")
    assert ctx.script == SPANISH and ctx.language == "es"
    assert "English → Spanish" in ctx.notes[0] and "Captions will be in Spanish" in ctx.notes[0]
    system = llm.calls[0][0].content
    assert "into Spanish" in system and "exactly as written: AWS" in system
    assert llm.calls[0][1].content == SCRIPT


def test_notes_changed_terms_paragraphs_and_length():
    reply = "Bienvenidos al laboratorio y al estudio, hoy lo desplegamos en la nube de Amazon."
    ctx = _run(_ctx(FakeLLM(reply), target_seconds=30), target_language="es", keep_terms="AWS")
    notes = " ".join(ctx.notes)
    assert "paragraph breaks changed" in notes
    assert "changed by the translation: AWS" in notes
    assert "for a 30 s target" in notes


def test_chinese_translation_is_checked_by_script_and_flagged_as_rough():
    ctx = _run(_ctx(FakeLLM(CHINESE)), target_language="zh")
    assert ctx.language == "zh" and "rough" in ctx.notes[-1]
    with pytest.raises(ValueError, match="didn't return a Chinese translation"):
        _run(_ctx(FakeLLM(SPANISH)), target_language="zh")


def test_untranslated_reply_is_an_error_not_a_silent_success():
    with pytest.raises(ValueError, match="didn't return a Spanish translation"):
        _run(_ctx(FakeLLM(SCRIPT)), target_language="es")


def test_refusal_from_the_model_is_passed_on():
    with pytest.raises(ScriptRefusedError):
        _run(_ctx(FakeLLM("REFUSED: not something I can translate")), target_language="es")


def test_language_the_voice_model_cannot_speak_is_rejected_before_calling_the_llm():
    llm = FakeLLM("unused")
    with pytest.raises(ValueError, match="can't speak 'hi'"):
        _run(_ctx(llm), target_language="hi")
    ctx = _run(_ctx(llm), target_language="en")
    assert "already in English" in ctx.notes[0] and llm.calls == []
