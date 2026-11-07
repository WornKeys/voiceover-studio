"""Render an approved script into a voiceover: chunk → speak → join → loudness → watermark → label → files."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from voiceover_studio import __version__
from voiceover_studio.core.audio import concat, normalize_loudness, write_wav
from voiceover_studio.core.captions import make_cues, to_srt
from voiceover_studio.core.config import AppConfig
from voiceover_studio.core.text import chunk_text
from voiceover_studio.core.watermark import MESSAGE, Watermarker
from voiceover_studio.providers.base import TTSProvider, VoiceReference

Progress = Callable[[int, int, str], None]  # (done, total, chunk text)


class RenderError(ValueError):
    pass


@dataclass(frozen=True)
class RenderResult:
    wav_path: Path
    srt_path: Path
    manifest_path: Path
    seconds: float
    chunks: int


def _check(script: str, voice: VoiceReference, language: str, tts: TTSProvider) -> None:
    if not voice.consent_id:
        raise RenderError("No consent record for this voice. Record the consent sentence first.")
    caps = tts.capabilities()
    if not caps.cloning:
        raise RenderError(f"The '{tts.name}' provider can't clone voices.")
    if language not in caps.languages:
        raise RenderError(
            f"The '{tts.name}' provider doesn't support '{language}'. Supported: {caps.languages}"
        )
    if not script.strip():
        raise RenderError("The script is empty.")


def render_voiceover(
    script: str,
    voice: VoiceReference,
    language: str,
    tts: TTSProvider,
    watermarker: Watermarker,
    cfg: AppConfig,
    out_dir: Path,
    progress: Progress | None = None,
) -> RenderResult:
    _check(script, voice, language, tts)
    caps = tts.capabilities()
    chunks = chunk_text(script, min(cfg.synthesis.max_chunk_chars, caps.max_chars_per_call))

    clips = []
    for i, chunk in enumerate(chunks):
        clips.append(tts.synthesize(chunk, voice, language))
        if progress:
            progress(i + 1, len(chunks), chunk)

    joined, timings = concat(clips, cfg.synthesis.pause_between_sentences_ms)
    leveled = normalize_loudness(joined, cfg.output.loudness_lufs)
    marked = watermarker.embed(leveled)

    created = datetime.now(UTC).isoformat(timespec="seconds")
    label = cfg.output.provenance_label
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_path = write_wav(
        marked,
        out_dir / "voiceover.wav",
        info={
            "INAM": "Voiceover",
            "ICMT": f"{label}. Watermark: {watermarker.method} 0x{MESSAGE:04X}.",
            "ISFT": f"voiceover-studio {__version__}",
            "ICRD": created[:10],
        },
    )

    srt_path = out_dir / "voiceover.srt"
    cues = make_cues([(start, end, text) for (start, end), text in zip(timings, chunks, strict=True)])
    srt_path.write_text(to_srt(cues), encoding="utf-8")

    manifest_path = out_dir / "provenance.json"
    manifest = {
        "label": label,
        "generator": f"voiceover-studio {__version__}",
        "created_at": created,
        "language": language,
        "tts_provider": tts.name,
        "tts_runs_locally": caps.runs_locally,
        "voice_consent_id": voice.consent_id,
        "watermark": {"method": watermarker.method, "message": f"0x{MESSAGE:04X}"},
        "loudness_lufs": cfg.output.loudness_lufs,
        "seconds": round(marked.seconds, 2),
        "chunks": len(chunks),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return RenderResult(wav_path, srt_path, manifest_path, marked.seconds, len(chunks))
