"""Download and load the local models once, at deploy time: `python -m voiceover_studio.prefetch`.

Without it, the first voice check or render would wait for several GB of downloads. Loading (not only
downloading) also proves the models fit and run on this machine before anyone opens the UI.
The LLM is not handled here: its server (vLLM) downloads and loads it when it starts.
"""

from __future__ import annotations

import logging
import sys
import time

from voiceover_studio.core.watermark import AudioSealWatermarker
from voiceover_studio.settings import HOSTED_TTS, Settings, build_asr, build_tts

log = logging.getLogger("prefetch")


def _step(label: str, fn) -> None:
    start = time.perf_counter()
    log.info("%s...", label)
    fn()
    log.info("%s: done in %.0f s", label, time.perf_counter() - start)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    s = Settings.from_env()
    if s.tts_provider not in HOSTED_TTS:
        tts = build_tts(s)
        _step(f"Voice model {s.tts_model}", tts._load)  # type: ignore[attr-defined]
    if s.asr_provider == "faster_whisper":
        asr = build_asr(s)
        _step(f"Speech-to-text (Whisper {s.asr_model}, {s.asr_device})", asr._load)  # type: ignore[attr-defined]
    _step("Watermark (AudioSeal)", lambda: AudioSealWatermarker(device=s.device))
    return 0


if __name__ == "__main__":
    sys.exit(main())
