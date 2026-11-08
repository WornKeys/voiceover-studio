# Write your own plugin

Plugins add **new capabilities** to the studio without touching the core. They run on the server, and the UI
builds their controls from their settings, so a new plugin needs no UI code.

Two plugins ship with the app:

| Plugin | What it does | Enable |
|---|---|---|
| `fit_to_length` | Rewrites the script so the voiceover matches your video's length | `PLUGINS=fit_to_length` |
| `translate` | Translates the script into another language your voice model can speak | `PLUGINS=fit_to_length,translate` |

`PLUGINS` is set in `.env` and applied by `./scripts/deploy.sh` (or in your shell for local development).

## The contract

A plugin is a class in `voiceover_studio/plugins/` (see [`base.py`](../voiceover_studio/plugins/base.py)):

| Part | What it is |
|---|---|
| `name`, `title`, `description` | Id used in `PLUGINS` and the API; what the UI shows |
| `stage` | When it runs: `script` (after you approve the script), `audio` (after synthesis), `output` (after the files are written). v1 runs `script` plugins from the Script tab |
| `Settings` | A pydantic model. Its JSON schema becomes UI controls: a number with min/max → slider, `enum` → dropdown, bool → checkbox, text → textbox |
| `settings_schema(tts)` | Optional. Override it when choices depend on the providers |
| `run(ctx, settings)` | Does the work and returns the context. It may change `ctx.script` and `ctx.language`, and should add plain-language `ctx.notes` |

Rules that keep plugins swappable and safe:

- **Depend on ports, not models.** Use `ctx.llm` and `ctx.tts` (the provider interfaces). Never import a model
  library in a plugin: then it works with the local GPU models, Bedrock or any hosted provider.
- **Ask the providers what they can do.** Read `ctx.tts.capabilities()` instead of hard-coding languages or limits.
- **Check the model's answer.** LLMs sometimes return the input unchanged, add commentary or refuse. Raise
  `ValueError` with a message a user understands; the UI and API show it as "Not applied".
- **Guardrails stay in the core.** A plugin can't skip the consent check or the watermark: those run in
  `render_voiceover`, after every plugin.
- **Trusted code only.** Plugins ship in this repo. Nothing is downloaded or installed at runtime.

## Worked example: `translate`

The full file is [`translate.py`](../voiceover_studio/plugins/translate.py). The interesting parts:

**1. Choices from the voice model.** The target-language dropdown lists only the languages the current TTS provider
declares, so switching to a provider with more languages updates the UI with no code change:

```python
@classmethod
def settings_schema(cls, tts=None):
    schema = cls.Settings.model_json_schema()
    languages = list(tts.languages) if tts else list(LANGUAGE_NAMES)
    schema["properties"]["target_language"]["enum"] = languages
    return schema
```

**2. One call to the `llm` port.** Low temperature (a translation should be faithful, not creative), and a token
budget that allows for languages that need more tokens per word:

```python
reply = ctx.llm.complete(
    [ChatMessage("system", system), ChatMessage("user", ctx.script)],
    max_tokens=max(512, words * 4),
    temperature=0.2,
)
translated = parse_reply(reply)  # strips markdown and labels, raises on "REFUSED:"
```

**3. Checks with useful messages.** It fails if the reply is unchanged, or isn't written in the target script (for
Chinese, Japanese, Korean and Russian). It adds notes when paragraph breaks or protected terms changed, or the new
length misses the target.

**4. Changing the language.** It sets `ctx.language`, and the UI's language dropdown follows. The render then
checks that the voice model supports that language, and the captions come out in it too.

## Add yours

1. Create `voiceover_studio/plugins/<name>.py` with a `Plugin` subclass.
2. Register it in `voiceover_studio/plugins/__init__.py` (`AVAILABLE`).
3. Add tests with the fakes in `tests/fakes.py` (`FakeLLM` takes a fixed reply or a function), as in
   `tests/test_translate.py`. No GPU or network needed.
4. Enable it: `PLUGINS=fit_to_length,<name>`, then `./scripts/deploy.sh` (it only updates the app).

Ideas not built yet: tone rewrite, background music with ducking (`audio` stage), noise clean-up, muxing the
voiceover into a video file (`output` stage).
