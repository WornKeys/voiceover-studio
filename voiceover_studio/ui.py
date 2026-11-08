"""Browser UI (Gradio): one guided page with three steps, each saying what to do and what happens next.

1. Your voice: pick a saved voice, or record the consent sentence.  2. Your script: describe the video and let
the AI draft it, or paste your own; optional tools (plugins).  3. Generate: a summary of what will be used, then
the voiceover, its captions and its provenance file.

A finished step collapses to a one-line summary and the next one opens. Steps stay clickable, so you can go back.
Plugin controls are built from each plugin's settings schema, so adding a plugin needs no UI code.
Microphone recording needs a secure context: the UI is opened as http://localhost:7860 through the SSM tunnel.
The same Services as the HTTP API do the work.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

import gradio as gr

from voiceover_studio.core.consent import ConsentError
from voiceover_studio.core.convert import ConversionError
from voiceover_studio.core.render import RenderError
from voiceover_studio.core.script import LANGUAGE_NAMES, ScriptRefusedError, ScriptRequest
from voiceover_studio.services import SampleRejectedError, Services

INTRO = """# Voiceover studio
Turn a script into a voiceover **in your own voice**, in three steps below. Everything runs in your own AWS
account. Every file is watermarked and labelled as AI-generated. Only clone **your own voice**
(see RESPONSIBLE_USE.md)."""

TONES = ["friendly and clear", "enthusiastic", "calm and reassuring", "professional", "playful", "serious"]

STEP_VOICE, STEP_SCRIPT, STEP_GENERATE = "1. Your voice", "2. Your script", "3. Generate the voiceover"

DOWNLOADS_HELP = """**Your files:** `voiceover.wav` is the audio for your video editor. `voiceover.srt` holds
captions you can upload to YouTube or add in your editor. `provenance.json` records that the audio is
AI-generated, with the watermark details."""

# A quiet look: slate greys, graphite primary buttons (light grey in dark mode), the system font (no web-font
# download through the tunnel) and a readable page width. Light and dark follow the browser's setting.
THEME = gr.themes.Base(
    primary_hue="slate",
    secondary_hue="slate",
    neutral_hue="slate",
    radius_size="md",
    font=("ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"),
    font_mono=("ui-monospace", "SFMono-Regular", "Consolas", "monospace"),
).set(
    body_background_fill="*neutral_50",
    body_background_fill_dark="*neutral_950",
    block_title_text_weight="600",
    button_primary_background_fill="*neutral_800",
    button_primary_background_fill_hover="*neutral_700",
    button_primary_border_color="*neutral_800",
    button_primary_text_color="white",
    button_primary_background_fill_dark="*neutral_200",
    button_primary_background_fill_hover_dark="*neutral_300",
    button_primary_border_color_dark="*neutral_200",
    button_primary_text_color_dark="*neutral_900",
    slider_color="*neutral_600",
    checkbox_background_color_selected="*neutral_700",
)
CSS = """
.gradio-container { max-width: 920px !important; margin: 0 auto !important; }
footer { display: none !important; }
"""


MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # a 15-second voice sample is well under 1 MB, even as uncompressed WAV


class UploadError(ValueError):
    pass


def read_upload(path: str) -> bytes:
    """Read a file the user recorded or uploaded through Gradio.

    Gradio hands the handler a path inside its own upload folder. Only such paths are read: a second check on top
    of Gradio's own (older Gradio versions had bugs that let a crafted request name any file on the server).
    """
    root = os.path.realpath(gr.utils.get_upload_folder())
    real = os.path.realpath(path)
    if not real.startswith(root + os.sep):
        raise UploadError("That file didn't come from the recorder or the upload button.")
    if os.path.getsize(real) > MAX_UPLOAD_BYTES:
        raise UploadError("That file is too large for a voice sample (20 MB at most).")
    with open(real, "rb") as f:
        return f.read()


# --- small helpers (no Gradio state; unit-tested) ----------------------------------------------------------
def voice_label(voice: dict[str, Any]) -> str:
    """'Recorded 8 Nov 2026, 11:42 UTC (a1b2)': readable, and unique even for two voices in the same minute."""
    try:
        moment = datetime.fromisoformat(voice["created_at"])
        when = f"{moment.day} {moment:%b %Y, %H:%M} UTC"
    except (TypeError, ValueError):
        when = str(voice["created_at"])
    return f"Recorded {when} ({voice['voice_id'][:4]})"


def language_choices(codes: list[str]) -> list[tuple[str, str]]:
    return [(f"{LANGUAGE_NAMES.get(code, code)}", code) for code in codes]


def done(step: str, summary: str) -> str:
    return f"✓ {step}: {summary}"


def script_summary(words: int, seconds: float, language: str) -> str:
    return f"{words} words, about {seconds:.0f} s, {LANGUAGE_NAMES.get(language, language)}"


def component_for(name: str, prop: dict[str, Any]) -> gr.components.Component:
    """Turn one JSON-schema property of a plugin's settings into a UI control."""
    label = prop.get("description") or name.replace("_", " ").capitalize()
    default = prop.get("default")
    kind = prop.get("type")
    if "enum" in prop:
        choices = language_choices(prop["enum"]) if name.endswith("language") else prop["enum"]
        return gr.Dropdown(choices=choices, value=default, label=label)
    if kind in ("integer", "number"):
        minimum, maximum = prop.get("minimum"), prop.get("maximum")
        if minimum is not None and maximum is not None:
            step = 1 if kind == "integer" else (maximum - minimum) / 100
            return gr.Slider(minimum, maximum, value=default, step=step, label=label)
        return gr.Number(value=default, label=label, precision=0 if kind == "integer" else None)
    if kind == "boolean":
        return gr.Checkbox(value=bool(default), label=label)
    return gr.Textbox(value=default or "", label=label)


def build_ui(services: Services) -> gr.Blocks:
    info = services.info()
    wpm = info["words_per_minute"]
    languages = language_choices(info["languages"])

    def voice_choices() -> list[tuple[str, str]]:
        return [(voice_label(v), v["voice_id"]) for v in services.list_voices()]

    def voice_name(voice_id: str | None) -> str:
        return next((label for label, vid in voice_choices() if vid == voice_id), "none chosen")

    def estimate(script: str) -> str:
        draft = services.estimate(script or "")
        if not draft.words:
            return "Write a draft with AI, or paste your own script here."
        return f"{draft.words} words, about {draft.estimated_seconds:.0f} seconds when read aloud."

    saved = voice_choices()

    with gr.Blocks(title="Voiceover studio") as ui:
        gr.Markdown(INTRO)
        if info["voice_leaves_account"]:
            gr.Markdown(
                "> **Note:** the selected voice provider is a hosted service: "
                "your voice sample is sent to it."
            )

        # --- step 1: voice -----------------------------------------------------------------------------
        # With a saved voice, step 1 starts done (the newest voice) and step 2 starts open.
        first_label = done(STEP_VOICE, saved[0][0]) if saved else STEP_VOICE
        with gr.Accordion(first_label, open=not saved) as step_voice:
            if saved:
                gr.Markdown("Use a voice you saved before, or record a new one below.")
            voice = gr.Dropdown(
                choices=saved,
                value=saved[0][1] if saved else None,
                label="Saved voices",
                info="Voices are stored only in your own S3 bucket.",
                interactive=True,
                visible=bool(saved),
            )
            with gr.Row(visible=bool(saved)) as voice_actions:
                use_voice = gr.Button("Use this voice →", variant="primary")
                remove = gr.Button("Delete this voice", variant="stop", size="sm")

            gr.Markdown(
                "**Record a new voice.** Click the microphone, read the sentence below aloud in a quiet room, "
                "then stop. Listen back, and save it. "
                f"It should take {info['sample_seconds']['min']:.0f} to {info['sample_seconds']['max']:.0f} "
                "seconds. Use Firefox, Chrome or Edge: in Brave, fingerprinting protection freezes the recorder."
            )
            gr.Markdown(f'> ### "{info["consent_sentence"]}"')
            gr.Markdown(
                "*Why this sentence?* It is your consent to clone your voice, and the voice model uses the "
                "recording and these exact words to learn how you sound."
            )
            recording = gr.Audio(sources=["microphone", "upload"], type="filepath", label="Your reading")
            save = gr.Button("Save this recording as my voice", variant="primary")
            voice_status = gr.Markdown()

        # --- step 2: script ----------------------------------------------------------------------------
        with gr.Accordion(STEP_SCRIPT, open=bool(saved)) as step_script:
            gr.Markdown(
                "Describe your video and let the AI write a first draft, **or paste your own script** into the "
                "box below. Then edit it until it reads well aloud."
            )
            description = gr.Textbox(
                lines=3,
                label="What is the video about?",
                info="A sentence or two: the topic, what viewers will see, anything the voiceover must mention.",
                placeholder="A short intro for my desk-setup video: three habits that keep my workspace tidy.",
            )
            with gr.Row():
                seconds = gr.Slider(
                    5, info["max_target_seconds"], value=30, step=5,
                    label="Target length (seconds)",
                    info=f"At a natural pace that's about {wpm / 60:.1f} words per second.",
                )  # fmt: skip
                language = gr.Dropdown(
                    choices=languages,
                    value=info["languages"][0],
                    label="Language of the voiceover",
                    info="Your cloned voice can speak these; in a language you don't speak, the accent may differ.",
                )
            with gr.Row():
                tone = gr.Dropdown(
                    choices=TONES, value=TONES[0], allow_custom_value=True,
                    label="Tone", info="How it should sound. Pick one or type your own.",
                )  # fmt: skip
                audience = gr.Textbox(
                    value="general viewers",
                    label="Who will watch it?",
                    info="Shapes the wording, e.g. beginners, developers, customers.",
                )
            write = gr.Button("Write a draft with AI", variant="secondary")
            write_status = gr.Markdown()
            script = gr.Textbox(
                lines=10,
                label="Script: exactly what will be read aloud",
                info="Edit freely. It's spoken one sentence at a time, so short sentences sound best.",
                placeholder="Write a draft with AI above, or paste your own script here.",
            )
            script_info = gr.Markdown(estimate(""))

            if info["plugins"]:
                gr.Markdown(
                    "**Optional tools.** Each one changes the script above; check the result before you go on."
                )
            for manifest in info["plugins"]:
                with gr.Accordion(manifest["title"], open=False):
                    gr.Markdown(manifest["description"])
                    props = manifest["settings_schema"].get("properties", {})
                    controls = [component_for(n, p) for n, p in props.items()]
                    apply = gr.Button(f"Apply {manifest['title'].lower()}")
                    notes = gr.Markdown()

                    def run(script_text, lang, target, *values, _name=manifest["name"], _keys=tuple(props)):
                        try:
                            result = services.run_plugin(_name, script_text or "", lang, float(target),
                                                         dict(zip(_keys, values, strict=True)))  # fmt: skip
                        except (ValueError, LookupError) as exc:  # includes refusals and bad settings
                            return gr.update(), gr.update(), gr.update(), f"**Not applied.** {exc}"
                        return (result["script"], result["language"], estimate(result["script"]),
                                "\n".join(result["notes"]))  # fmt: skip

                    apply.click(
                        run, [script, language, seconds, *controls], [script, language, script_info, notes]
                    )

            to_generate = gr.Button("Next: generate the voiceover →", variant="primary")
            script_status = gr.Markdown()

        # --- step 3: generate --------------------------------------------------------------------------
        with gr.Accordion(STEP_GENERATE, open=False) as step_generate:
            summary = gr.Markdown("Choose a voice (step 1) and write a script (step 2) first.")
            go = gr.Button("Generate voiceover", variant="primary")
            status = gr.Markdown()
            player = gr.Audio(label="Your voiceover", interactive=False)
            downloads = gr.File(label="Download", file_count="multiple")
            gr.Markdown(DOWNLOADS_HELP)
            back = gr.Button("← Change the script", size="sm")

        # --- handlers ----------------------------------------------------------------------------------
        def save_voice(audio_path: str | None):
            keep = gr.update()
            if not audio_path:
                return "Record or upload your reading of the sentence first.", keep, keep, keep, keep, keep
            try:
                data = read_upload(audio_path)
            except (UploadError, OSError) as exc:
                return f"**Not saved.** {exc}", keep, keep, keep, keep, keep
            try:
                saved_voice = services.add_voice(data)
            except SampleRejectedError as exc:
                message = "**Please record again:**\n" + "\n".join(f"- {p}" for p in exc.problems)
                return message, keep, keep, keep, keep, keep
            except (ConsentError, ConversionError) as exc:
                return f"**Not saved.** {exc}", keep, keep, keep, keep, keep
            choices = voice_choices()
            picker = gr.update(choices=choices, value=saved_voice.voice_id, visible=True)
            message = (
                f"Voice saved ({saved_voice.seconds} s, sentence match {saved_voice.consent_score:.0%})."
            )
            if saved_voice.warnings:  # stay here so the warnings are read
                tips = "\n".join(f"- {w}" for w in saved_voice.warnings)
                message += f"\n\n{tips}\n\nRecord again for a better result, or **Use this voice →**."
                return message, picker, gr.update(visible=True), keep, keep, keep
            label = done(STEP_VOICE, voice_name(saved_voice.voice_id))
            return (message, picker, gr.update(visible=True), gr.update(label=label, open=False),
                    gr.update(open=True), None)  # fmt: skip

        def choose_voice(voice_id: str | None):
            if not voice_id:
                return "Choose a saved voice, or record a new one.", gr.update(), gr.update()
            return (
                "",
                gr.update(label=done(STEP_VOICE, voice_name(voice_id)), open=False),
                gr.update(open=True),
            )

        def delete_voice(voice_id: str | None):
            if not voice_id:  # nothing chosen, or the confirmation was cancelled
                return gr.update(), gr.update(), gr.update()
            services.delete_voice(voice_id)
            choices = voice_choices()
            picker = gr.update(
                choices=choices, value=choices[0][1] if choices else None, visible=bool(choices)
            )
            return picker, gr.update(visible=bool(choices)), "Voice deleted from your bucket."

        def write_script(description, audience, tone, seconds, language):
            try:
                draft = services.draft_script(
                    ScriptRequest(description or "", float(seconds), audience, tone, language)
                )
            except (ScriptRefusedError, ValueError) as exc:
                return gr.update(), f"**Not written.** {exc}"
            return draft.text, "Draft written. Edit it below, or try the optional tools."

        def summarize(voice_id, script_text, lang) -> str:
            draft = services.estimate(script_text or "")
            missing = []
            if not voice_id:
                missing.append("a voice (step 1)")
            if not draft.words:
                missing.append("a script (step 2)")
            if missing:
                return "**Still needed:** " + " and ".join(missing) + "."
            return (f"**Voice:** {voice_name(voice_id)}  \n"
                    f"**Script:** {script_summary(draft.words, draft.estimated_seconds, lang)}  \n"
                    "Press **Generate voiceover**. Each sentence is spoken in turn; the first one also loads the "
                    "voice model, so it takes longest.")  # fmt: skip

        def next_to_generate(voice_id, script_text, lang):
            draft = services.estimate(script_text or "")
            if not draft.words:
                return "Write or paste a script first.", gr.update(), gr.update(), gr.update()
            label = done(STEP_SCRIPT, script_summary(draft.words, draft.estimated_seconds, lang))
            return ("", gr.update(label=label, open=False), gr.update(open=True),
                    summarize(voice_id, script_text, lang))  # fmt: skip

        def generate(voice_id, script_text, lang, progress=gr.Progress()):  # noqa: B008 (Gradio's idiom)
            if not voice_id:
                yield "Choose or record a voice in step 1 first.", None, None
                return
            if not (script_text or "").strip():
                yield "Write or paste a script in step 2 first.", None, None
                return
            try:
                job = services.submit_render(voice_id, script_text, lang)
            except (RenderError, KeyError, FileNotFoundError) as exc:
                yield f"**Can't generate.** {exc}", None, None
                return
            while job.status in ("queued", "running"):
                if job.total:
                    progress((job.done, job.total), desc="Sentences spoken", unit="sentences")
                    yield f"Speaking sentence {min(job.done + 1, job.total)} of {job.total}...", None, None
                else:
                    yield job.message or "Starting...", None, None
                time.sleep(1)
            if job.status == "failed":
                yield f"**Failed:** {job.error}", None, None
                return
            output_id = job.result["output_id"]
            files = []
            for name in job.result["files"]:
                path = services.workdir / "downloads" / output_id / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(services.output_file(output_id, name))
                files.append(str(path))
            yield (f"**Done:** {job.result['seconds']} s of audio, watermarked and labelled as AI-generated. "
                   "Listen below, then download.", files[0], files)  # fmt: skip

        save.click(
            save_voice, recording, [voice_status, voice, voice_actions, step_voice, step_script, recording]
        )
        use_voice.click(choose_voice, voice, [voice_status, step_voice, step_script])
        remove.click(
            delete_voice, voice, [voice, voice_actions, voice_status],
            js="(v) => (v && confirm('Delete this voice? The recording is removed from your bucket.')) ? v : null",
        )  # fmt: skip
        write.click(write_script, [description, audience, tone, seconds, language], [script, write_status])
        script.change(estimate, script, script_info)
        to_generate.click(
            next_to_generate, [voice, script, language], [script_status, step_script, step_generate, summary]
        )
        step_generate.expand(summarize, [voice, script, language], summary)
        go.click(generate, [voice, script, language], [status, player, downloads])
        back.click(lambda: (gr.update(open=True), gr.update(open=False)), None, [step_script, step_generate])

    return ui
