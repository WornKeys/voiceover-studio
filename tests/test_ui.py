import gradio as gr

from tests.test_api import make_client
from voiceover_studio.ui import build_ui, component_for


def test_plugin_settings_schema_becomes_controls():
    assert isinstance(
        component_for("n", {"type": "integer", "minimum": 1, "maximum": 4, "default": 3}), gr.Slider
    )
    assert isinstance(component_for("on", {"type": "boolean", "default": True}), gr.Checkbox)
    assert isinstance(component_for("mode", {"enum": ["a", "b"], "default": "a"}), gr.Dropdown)
    assert isinstance(component_for("text", {"type": "string"}), gr.Textbox)


def test_ui_builds_with_plugins_enabled(tmp_path):
    services = make_client(tmp_path).app.state.services
    ui = build_ui(services)
    assert isinstance(ui, gr.Blocks)
