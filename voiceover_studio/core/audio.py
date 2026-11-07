"""Audio helpers: joining chunks, loudness, silence trimming, and WAV files with an "AI-generated" label.

WAV reading/writing uses only the standard library (16-bit PCM). Other formats (browser webm, mp3) are
converted with ffmpeg at the edges of the app, not here.
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import numpy as np
import pyloudnorm

from voiceover_studio.providers.base import AudioClip


def concat(clips: list[AudioClip], pause_ms: int) -> tuple[AudioClip, list[tuple[float, float]]]:
    """Join clips with a pause between them. Returns the joined clip and each clip's (start, end) seconds."""
    if not clips:
        raise ValueError("Nothing to join: no audio clips.")
    rate = clips[0].sample_rate
    if any(c.sample_rate != rate for c in clips):
        raise ValueError("All clips must have the same sample rate.")
    pause = np.zeros(int(rate * pause_ms / 1000), dtype=np.float32)
    parts: list[np.ndarray] = []
    timings: list[tuple[float, float]] = []
    position = 0
    for i, clip in enumerate(clips):
        if i:
            parts.append(pause)
            position += len(pause)
        samples = np.asarray(clip.samples, dtype=np.float32)
        timings.append((position / rate, (position + len(samples)) / rate))
        parts.append(samples)
        position += len(samples)
    return AudioClip(np.concatenate(parts), rate), timings


def peak_dbfs(clip: AudioClip) -> float:
    peak = float(np.max(np.abs(clip.samples))) if len(clip.samples) else 0.0
    return 20 * np.log10(peak) if peak > 0 else float("-inf")


def rms_dbfs(samples: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64)))) if len(samples) else 0.0
    return 20 * np.log10(rms) if rms > 0 else float("-inf")


def normalize_loudness(clip: AudioClip, target_lufs: float, peak_ceiling_db: float = -1.0) -> AudioClip:
    """Match a loudness target (online video: about -16 LUFS), then make sure peaks stay below the ceiling."""
    samples = np.asarray(clip.samples, dtype=np.float64)
    if len(samples) < int(0.4 * clip.sample_rate):  # the loudness meter needs at least 400 ms
        return clip
    loudness = pyloudnorm.Meter(clip.sample_rate).integrated_loudness(samples)
    if not np.isfinite(loudness):  # silence
        return clip
    out = samples * (10 ** ((target_lufs - loudness) / 20))
    ceiling = 10 ** (peak_ceiling_db / 20)
    peak = float(np.max(np.abs(out)))
    if peak > ceiling:
        out *= ceiling / peak
    return AudioClip(out.astype(np.float32), clip.sample_rate)


def trim_silence(
    clip: AudioClip, relative_db: float = 30.0, floor_db: float = -70.0, frame_ms: int = 20, pad_ms: int = 150
) -> AudioClip:
    """Remove leading and trailing silence, keeping a little padding.

    "Silence" is relative to the loudest part of the recording (so a quiet recording is trimmed, not erased,
    and the quality check can then say "too quiet" instead of "no speech").
    """
    frame = max(1, int(clip.sample_rate * frame_ms / 1000))
    samples = np.asarray(clip.samples, dtype=np.float32)
    starts = range(0, len(samples), frame)
    levels = [rms_dbfs(samples[i : i + frame]) for i in starts]
    finite = [level for level in levels if np.isfinite(level)]
    if not finite or max(finite) <= floor_db:
        return AudioClip(samples[:0], clip.sample_rate)
    threshold = max(max(finite) - relative_db, floor_db)
    loud = [i for i, level in zip(starts, levels, strict=True) if level > threshold]
    if not loud:
        return AudioClip(samples[:0], clip.sample_rate)
    pad = int(clip.sample_rate * pad_ms / 1000)
    start = max(0, loud[0] - pad)
    end = min(len(samples), loud[-1] + frame + pad)
    return AudioClip(samples[start:end], clip.sample_rate)


def read_wav(path: Path) -> AudioClip:
    """Read a 16-bit PCM WAV file as mono float32."""
    with wave.open(str(path), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise ValueError(
                "Only 16-bit PCM WAV is supported here; convert other formats with ffmpeg first."
            )
        channels, rate = wav.getnchannels(), wav.getframerate()
        data = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return AudioClip(data, rate)


def _info_chunk(info: dict[str, str]) -> bytes:
    """RIFF LIST/INFO chunk: metadata most audio tools show (title, comment, software...)."""
    body = b"INFO"
    for key, value in info.items():
        if len(key) != 4:
            raise ValueError(f"INFO keys are 4 characters (e.g. ICMT), got {key!r}")
        data = value.encode("utf-8") + b"\x00"
        body += (
            key.encode("ascii") + struct.pack("<I", len(data)) + data + (b"\x00" if len(data) % 2 else b"")
        )
    return b"LIST" + struct.pack("<I", len(body)) + body


def write_wav(clip: AudioClip, path: Path, info: dict[str, str] | None = None) -> Path:
    """Write mono 16-bit PCM WAV, with optional INFO metadata (ICMT comment, ISFT software, INAM title...)."""
    pcm = (np.clip(clip.samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    fmt = struct.pack("<HHIIHH", 1, 1, clip.sample_rate, clip.sample_rate * 2, 2, 16)
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    if info:
        chunks += _info_chunk(info)
    chunks += b"data" + struct.pack("<I", len(pcm)) + pcm + (b"\x00" if len(pcm) % 2 else b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks)
    return path


def read_wav_info(path: Path) -> dict[str, str]:
    """Read the INFO metadata written by write_wav (used by tests and the provenance check)."""
    data = path.read_bytes()
    info: dict[str, str] = {}
    pos = 12
    while pos + 8 <= len(data):
        chunk_id, size = data[pos : pos + 4], struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        if chunk_id == b"LIST" and data[pos + 8 : pos + 12] == b"INFO":
            sub = pos + 12
            while sub < pos + 8 + size:
                key, length = (
                    data[sub : sub + 4].decode("ascii"),
                    struct.unpack("<I", data[sub + 4 : sub + 8])[0],
                )
                info[key] = data[sub + 8 : sub + 8 + length].rstrip(b"\x00").decode("utf-8")
                sub += 8 + length + (length % 2)
        pos += 8 + size + (size % 2)
    return info
