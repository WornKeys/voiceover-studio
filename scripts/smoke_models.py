#!/usr/bin/env python3
"""Smoke test with REAL models: consent check, voice cloning, watermark, render.

Runs on CPU (slow, use the 0.6B voice model) or GPU (the dry run on AWS). The LLM is not needed: the script
text is fixed. Use a synthetic reference voice or your own recording, never someone else's.

  python scripts/smoke_models.py --reference ref.wav --out outputs/smoke --device cpu \
      --tts-model Qwen/Qwen3-TTS-12Hz-0.6B-Base
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from voiceover_studio.core.audio import read_wav, read_wav_info
from voiceover_studio.core.config import load_config
from voiceover_studio.core.consent import check_sample, match_score
from voiceover_studio.core.render import render_voiceover
from voiceover_studio.core.watermark import AudioSealWatermarker
from voiceover_studio.providers import registry
from voiceover_studio.providers.base import AudioClip, VoiceReference

SCRIPT = (
    "Welcome to the lab. Today we build a voiceover studio that runs in your own AWS account. "
    "Every file it makes carries an inaudible watermark."
)


def timed(label: str, results: dict, fn):
    start = time.perf_counter()
    value = fn()
    results.setdefault("seconds", {})[label] = round(time.perf_counter() - start, 1)
    print(f"[{results['seconds'][label]:>6.1f}s] {label}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("outputs/smoke"))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--tts-model", default="Qwen/Qwen3-TTS-12Hz-1.7B-Base")
    parser.add_argument("--asr-model", default="small")
    args = parser.parse_args()

    cfg = load_config()
    results: dict = {"device": args.device, "tts_model": args.tts_model}
    sample = read_wav(args.reference)

    check = check_sample(sample, cfg.voice_sample)
    results["sample_check"] = {"ok": check.ok, "problems": check.problems, "warnings": check.warnings}

    compute = "int8" if args.device == "cpu" else "float16"
    asr = registry.create(
        "asr", "faster_whisper", model=args.asr_model, device=args.device, compute_type=compute
    )
    transcript = timed("whisper transcribe", results, lambda: asr.transcribe(args.reference, "en"))
    results["consent"] = {
        "transcript": transcript,
        "score": round(match_score(cfg.voice_sample.consent_sentence, transcript), 3),
    }

    watermarker = timed("audioseal load", results, lambda: AudioSealWatermarker(device=args.device))
    marked = timed("audioseal embed (sample)", results, lambda: watermarker.embed(sample))
    results["watermark_on_sample"] = {
        "detect_original": round(watermarker.detect(sample), 3),
        "detect_marked": round(watermarker.detect(marked), 3),
    }

    device = args.device if args.device == "cpu" else f"{args.device}:0"
    tts = registry.create("tts", "qwen3_tts", model=args.tts_model, device=device)
    voice = VoiceReference(args.reference, cfg.voice_sample.consent_sentence, consent_id="smoke-test")
    progress = []
    result = timed(
        "render (tts + watermark + files)",
        results,
        lambda: render_voiceover(
            SCRIPT, voice, "en", tts, watermarker, cfg, args.out, lambda d, t, _c: progress.append(d)
        ),
    )
    output = read_wav(result.wav_path)
    results["render"] = {
        "chunks": result.chunks,
        "audio_seconds": round(result.seconds, 2),
        "sample_rate": output.sample_rate,
        "detect_output": round(watermarker.detect(output), 3),
        "detect_output_resaved_16k": round(
            watermarker.detect(AudioClip(output.samples[:: max(1, output.sample_rate // 16000)], 16000)), 3
        ),
        "label": read_wav_info(result.wav_path).get("ICMT", ""),
    }
    tts_seconds = results["seconds"]["render (tts + watermark + files)"]
    results["render"]["real_time_factor"] = round(tts_seconds / max(result.seconds, 0.01), 2)

    (args.out / "smoke-results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
