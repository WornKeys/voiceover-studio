import pytest

from tests.fakes import FakeLLM
from voiceover_studio.core.script import (
    ScriptRefusedError,
    ScriptRequest,
    build_messages,
    clean_script,
    generate_script,
)


def test_clean_script_strips_reasoning_markdown_labels_and_directions():
    raw = """<think>The user wants a short intro...</think>
# Intro
**Narrator:** Welcome to the lab. [upbeat music]
- Today we build a voiceover studio.

VO: Let's get started."""
    assert clean_script(raw) == "Welcome to the lab. Today we build a voiceover studio.\n\nLet's get started."


def test_generate_script_returns_draft_with_estimate():
    llm = FakeLLM("Welcome to the lab. Today we build a voiceover studio.")
    draft = generate_script(
        llm, ScriptRequest("Intro to the series", target_seconds=30), words_per_minute=150, temperature=0.7
    )
    assert draft.words == 10
    assert draft.estimated_seconds == 4.0
    system = llm.calls[0][0].content
    assert "about 75 words" in system and "English" in system


def test_model_refusal_is_surfaced():
    llm = FakeLLM("REFUSED: it asks for a real person's fabricated statement")
    with pytest.raises(ScriptRefusedError, match="fabricated statement"):
        generate_script(llm, ScriptRequest("anything", 30), words_per_minute=150, temperature=0.7)


def test_obvious_impersonation_is_refused_before_calling_the_model():
    llm = FakeLLM("should not be called")
    with pytest.raises(ScriptRefusedError, match="in the voice of"):
        generate_script(
            llm,
            ScriptRequest("A message in the voice of a famous CEO", 30),
            words_per_minute=150,
            temperature=0.7,
        )
    assert llm.calls == []


def test_prompt_uses_requested_language_and_audience():
    messages = build_messages(ScriptRequest("demo", 60, audience="developers", language="de"), 150)
    assert "Write in German." in messages[0].content
    assert "Audience: developers" in messages[1].content
