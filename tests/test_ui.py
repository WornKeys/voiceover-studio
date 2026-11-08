from pathlib import Path

import gradio as gr
import pytest

from tests.test_api import make_client, sample_wav
from voiceover_studio import ui as ui_module
from voiceover_studio.ui import (
    STEP_SCRIPT,
    STEP_VOICE,
    UploadError,
    build_ui,
    component_for,
    language_choices,
    read_upload,
    script_summary,
    voice_label,
)


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch) -> Path:
    """Gradio's upload folder for the test: the UI only reads recordings from there."""
    folder = tmp_path / "gradio-uploads"
    folder.mkdir()
    monkeypatch.setenv("GRADIO_TEMP_DIR", str(folder))
    return folder


def recording_in(folder: Path, tmp_path: Path) -> str:
    path = folder / "reading.wav"
    path.write_bytes(sample_wav(tmp_path))  # synthetic: flagged as noisy
    return str(path)


def handler(ui: gr.Blocks, name: str):
    """The Python function behind a UI event, to drive the guided flow without a browser."""
    return next(f.fn for f in ui.fns.values() if f.fn and f.fn.__name__ == name)


def test_only_files_from_gradios_upload_folder_are_read(upload_dir, tmp_path, monkeypatch):
    inside = upload_dir / "sample.wav"
    inside.write_bytes(b"RIFF")
    assert read_upload(str(inside)) == b"RIFF"
    with pytest.raises(UploadError, match="didn't come from"):
        read_upload(str(Path(__file__)))  # any other file on the server
    with pytest.raises(UploadError, match="didn't come from"):
        read_upload(str(upload_dir / ".." / "elsewhere.wav"))  # climbing out of the folder
    monkeypatch.setattr(ui_module, "MAX_UPLOAD_BYTES", 3)
    with pytest.raises(UploadError, match="too large"):
        read_upload(str(inside))


def test_save_voice_refuses_a_path_outside_the_upload_folder(tmp_path):
    ui = build_ui(make_client(tmp_path).app.state.services)
    message, *_ = handler(ui, "save_voice")(str(Path(__file__)))
    assert message.startswith("**Not saved.**")


def test_plugin_settings_schema_becomes_controls():
    assert isinstance(
        component_for("n", {"type": "integer", "minimum": 1, "maximum": 4, "default": 3}), gr.Slider
    )
    assert isinstance(component_for("on", {"type": "boolean", "default": True}), gr.Checkbox)
    assert isinstance(component_for("mode", {"enum": ["a", "b"], "default": "a"}), gr.Dropdown)
    assert isinstance(component_for("text", {"type": "string"}), gr.Textbox)
    target = component_for("target_language", {"enum": ["en", "de"], "default": "de"})
    assert target.choices == [("English", "en"), ("German", "de")]  # names, not codes


def test_readable_labels():
    voice = {"voice_id": "a1b2c3d4-0000", "created_at": "2026-11-08T09:05:00+00:00"}
    assert voice_label(voice) == "Recorded 8 Nov 2026, 09:05 UTC (a1b2)"
    assert voice_label({"voice_id": "zz99", "created_at": "unknown"}) == "Recorded unknown (zz99)"
    assert language_choices(["en", "xx"]) == [("English", "en"), ("xx", "xx")]
    assert script_summary(35, 14.2, "en") == "35 words, about 14 s, English"


def test_ui_builds_with_plugins_enabled(tmp_path):
    services = make_client(tmp_path).app.state.services
    ui = build_ui(services)
    assert isinstance(ui, gr.Blocks)


def test_guided_flow_voice_then_script_then_generate(tmp_path, upload_dir):
    ui = build_ui(make_client(tmp_path).app.state.services)

    # Step 1: a saved recording with quality warnings is selected, but step 1 stays open so they get read.
    recording = recording_in(upload_dir, tmp_path)
    message, picker, actions, step1, _step2, _cleared = handler(ui, "save_voice")(recording)
    assert message.startswith("Voice saved") and "Background noise" in message and "Use this voice" in message
    voice_id = picker["value"]
    assert actions["visible"] is True and step1 == gr.update()

    # "Use this voice": step 1 collapses to a summary and step 2 opens.
    hint, step1, step2 = handler(ui, "choose_voice")(voice_id)
    assert hint == "" and step1["label"].startswith(f"✓ {STEP_VOICE}: Recorded ") and step1["open"] is False
    assert step2["open"] is True
    assert handler(ui, "choose_voice")(None)[0].startswith("Choose a saved voice")

    # No recording: a plain instruction, nothing moves on.
    assert handler(ui, "save_voice")(None)[0].startswith("Record or upload")

    # Step 2: a script is required before moving on; then step 3 opens with a summary of what will be used.
    assert handler(ui, "next_to_generate")(voice_id, "  ", "en")[0] == "Write or paste a script first."
    script = "Hello there. Welcome."
    hint, step2, step3, summary = handler(ui, "next_to_generate")(voice_id, script, "en")
    assert hint == "" and step2["label"].startswith(f"✓ {STEP_SCRIPT}: 3 words") and step3["open"] is True
    assert "**Voice:** Recorded " in summary and "**Script:** 3 words" in summary

    # Step 3: the summary names what's missing; generating streams progress and ends with the files.
    assert "a voice (step 1)" in handler(ui, "summarize")(None, script, "en")
    updates = list(handler(ui, "generate")(voice_id, script, "en", progress=lambda *a, **k: None))
    final_status, audio, files = updates[-1]
    assert final_status.startswith("**Done:**") and audio.endswith("voiceover.wav")
    names = [f.replace("\\", "/").rsplit("/", 1)[-1] for f in files]
    assert names == ["voiceover.wav", "voiceover.srt", "provenance.json"]


def test_generate_explains_what_is_missing(tmp_path):
    generate = handler(build_ui(make_client(tmp_path).app.state.services), "generate")
    assert next(generate(None, "Hi.", "en", progress=None))[0].startswith("Choose or record a voice")
    assert next(generate("some-voice", " ", "en", progress=None))[0].startswith("Write or paste a script")


def test_delete_needs_confirmation_and_hides_an_empty_picker(tmp_path, upload_dir):
    client = make_client(tmp_path)
    ui = build_ui(client.app.state.services)
    voice_id = handler(ui, "save_voice")(recording_in(upload_dir, tmp_path))[1]["value"]

    delete = handler(ui, "delete_voice")
    assert delete(None) == (gr.update(), gr.update(), gr.update())  # cancelled in the browser's confirm()
    picker, actions, message = delete(voice_id)
    assert picker["visible"] is False and actions["visible"] is False
    assert message == "Voice deleted from your bucket." and client.get("/api/voices").json() == []
