import pytest
from pydantic import BaseModel, Field

from voiceover_studio.plugins import Plugin, PluginContext, Stage
from voiceover_studio.providers import registry


def test_registry_creates_registered_provider_and_names_it():
    @registry.register("asr", "fake_asr_for_test")
    class FakeASR:
        def __init__(self, model: str):
            self.model = model

    provider = registry.create("asr", "fake_asr_for_test", model="tiny")
    assert provider.model == "tiny"
    assert FakeASR.name == "fake_asr_for_test"
    assert "fake_asr_for_test" in registry.available("asr")


def test_registry_rejects_unknown_and_duplicate_names():
    with pytest.raises(registry.UnknownProviderError, match="Unknown tts provider 'nope'"):
        registry.create("tts", "nope")

    @registry.register("llm", "dup_for_test")
    class One:
        pass

    with pytest.raises(ValueError, match="already registered"):
        registry.register("llm", "dup_for_test")(One)


def test_plugin_manifest_exposes_settings_schema_for_the_ui():
    class Shout(Plugin):
        name = "shout"
        title = "Shout"
        description = "Upper-cases the script."
        stage = Stage.SCRIPT

        class Settings(BaseModel):
            exclamations: int = Field(1, ge=0, le=3, description="How many '!' to add")

        def run(self, ctx: PluginContext, settings: BaseModel) -> PluginContext:
            ctx.script = ctx.script.upper() + "!" * settings.exclamations
            return ctx

    manifest = Shout.manifest()
    assert manifest["stage"] == "script"
    assert manifest["settings_schema"]["properties"]["exclamations"]["maximum"] == 3
