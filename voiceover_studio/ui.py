"""Browser UI (Gradio): voice → script → plugins → generate. Calls the same Services as the HTTP API.

Plugin controls are built from each plugin's settings schema, so adding a plugin needs no UI code.
Microphone recording needs a secure context: the UI is opened as http://localhost:7860 through the SSM tunnel.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import gradio as gr

from voiceover_studio.core.consent import ConsentError
from voiceover_studio.core.convert import ConversionError
from voiceover_studio.core.render import RenderError
from voiceover_studio.core.script import ScriptRefusedError, ScriptRequest
from voiceover_studio.services import SampleRejectedError, Services

INTRO = """# Voiceover studio
Your own voice, your script, your AWS account. Every file is watermarked and labelled as AI-generated.
Only clone **your own voice** (see RESPONSIBLE_USE.md)."""


def component_for(name: str, prop: dict[str, Any]) -> gr.components.Component:
    """Turn one JSON-schema property of a plugin's settings into a UI control."""
    label = prop.get("description") or name.replace("_", " ").capitalize()
    default = prop.get("default")
    kind = prop.get("type")
    if "enum" in prop:
        return gr.Dropdown(choices=prop["enum"], value=default, label=label)
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

    def voice_choices() -> list[tuple[str, str]]:
        return [(f"Voice recorded {v['created_at']}", v["voice_id"]) for v in services.list_voices()]

    # --- step 1: voice ---------------------------------------------------------------
    def save_voice(audio_path: str | None):
        if not audio_path:
            return "Record or upload your reading of the sentence first.", gr.update()
        try:
            voice = services.add_voice(Path(audio_path).read_bytes())
        except SampleRejectedError as exc:
            return "**Please record again:**\n" + "\n".join(f"- {p}" for p in exc.problems), gr.update()
        except (ConsentError, ConversionError) as exc:
            return f"**Not saved.** {exc}", gr.update()
        note = "\n".join(f"- {w}" for w in voice.warnings)
        message = f"Voice saved ({voice.seconds} s, sentence match {voice.consent_score:.0%})."
        return message + (f"\n\n{note}" if note else ""), gr.update(
            choices=voice_choices(), value=voice.voice_id
        )

    def delete_voice(voice_id: str | None):
        if voice_id:
            services.delete_voice(voice_id)
        return gr.update(choices=voice_choices(), value=None), "Voice deleted from storage."

    # --- step 2: script --------------------------------------------------------------
    def estimate(script: str) -> str:
        draft = services.estimate(script or "")
        return f"{draft.words} words, about {draft.estimated_seconds:.0f} seconds when read aloud."

    def write_script(description, audience, tone, seconds, language):
        try:
            draft = services.draft_script(
                ScriptRequest(description or "", float(seconds), audience, tone, language)
            )
        except (ScriptRefusedError, ValueError) as exc:
            return gr.update(), f"**Not written.** {exc}"
        return draft.text, estimate(draft.text)

    # --- step 4: generate ------------------------------------------------------------
    def generate(voice_id, script, language):
        if not voice_id:
            yield "Choose or save a voice first.", None, None
            return
        try:
            job = services.submit_render(voice_id, script or "", language)
        except (RenderError, KeyError, FileNotFoundError) as exc:
            yield f"**Can't generate.** {exc}", None, None
            return
        while job.status in ("queued", "running"):
            total = job.total or "?"
            yield f"Generating... {job.done}/{total} sentences. {job.message}", None, None
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
        yield f"Done: {job.result['seconds']} s of audio. Watermarked and labelled.", files[0], files

    with gr.Blocks(title="Voiceover studio") as ui:
        gr.Markdown(INTRO)
        if info["voice_leaves_account"]:
            gr.Markdown(
                "> **Note:** the selected voice provider is a hosted service: "
                "your voice sample is sent to it."
            )

        with gr.Tab("1. Your voice"):
            gr.Markdown(
                f"Read this sentence aloud, clearly, in a quiet room "
                f"({info['sample_seconds']['min']:.0f} to {info['sample_seconds']['max']:.0f} seconds):"
            )
            gr.Markdown(f'### "{info["consent_sentence"]}"')
            recording = gr.Audio(sources=["microphone", "upload"], type="filepath", label="Your reading")
            save = gr.Button("Check and save my voice", variant="primary")
            voice_status = gr.Markdown()
            voice = gr.Dropdown(choices=voice_choices(), label="Voice to use", interactive=True)
            remove = gr.Button("Delete this voice", variant="stop", size="sm")

        with gr.Tab("2. Script"):
            description = gr.Textbox(lines=4, label="Describe your video")
            with gr.Row():
                audience = gr.Textbox(value="general viewers", label="Audience")
                tone = gr.Textbox(value="friendly and clear", label="Tone")
            with gr.Row():
                seconds = gr.Slider(
                    10, info["max_target_seconds"], value=60, step=5, label="Target length (s)"
                )
                language = gr.Dropdown(
                    choices=info["languages"], value=info["languages"][0], label="Language"
                )
            write = gr.Button("Write a draft", variant="primary")
            script = gr.Textbox(lines=12, label="Script (edit freely before generating)")
            script_info = gr.Markdown()

            for manifest in info["plugins"]:
                with gr.Accordion(manifest["title"], open=False):
                    gr.Markdown(manifest["description"])
                    props = manifest["settings_schema"].get("properties", {})
                    controls = [component_for(n, p) for n, p in props.items()]
                    apply = gr.Button(f"Apply: {manifest['title']}")
                    notes = gr.Markdown()

                    def run(script_text, lang, target, *values, _name=manifest["name"], _keys=tuple(props)):
                        result = services.run_plugin(_name, script_text or "", lang, float(target),
                                                     dict(zip(_keys, values, strict=True)))  # fmt: skip
                        return result["script"], estimate(result["script"]), "\n".join(result["notes"])

                    apply.click(run, [script, language, seconds, *controls], [script, script_info, notes])

        with gr.Tab("3. Generate"):
            go = gr.Button("Generate voiceover", variant="primary")
            status = gr.Markdown()
            player = gr.Audio(label="Voiceover", interactive=False)
            downloads = gr.File(label="Downloads: audio, captions, provenance", file_count="multiple")

        save.click(save_voice, recording, [voice_status, voice])
        remove.click(delete_voice, voice, [voice, voice_status])
        write.click(write_script, [description, audience, tone, seconds, language], [script, script_info])
        script.change(estimate, script, script_info)
        go.click(generate, [voice, script, language], [status, player, downloads])

    return ui
