"""Local text-to-speech with voice cloning: Qwen3-TTS (Apache-2.0), running on the instance's GPU.

Cloning works best with the exact transcript of the reference clip. Our reference clip is the user reading the
consent sentence, so the transcript is always known.
"""

from __future__ import annotations

import numpy as np

from voiceover_studio.providers.base import AudioClip, TTSCapabilities, TTSProvider, VoiceReference
from voiceover_studio.providers.registry import register

# Language codes used in the app -> names the model expects.
LANGUAGES = {
    "en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "de": "German",
    "fr": "French", "ru": "Russian", "pt": "Portuguese", "es": "Spanish", "it": "Italian",
}  # fmt: skip


@register("tts", "qwen3_tts")
class Qwen3TTS(TTSProvider):
    def __init__(
        self,
        model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        device: str = "cuda:0",
        attention: str = "sdpa",  # flash_attention_2 is faster but needs a matching prebuilt wheel
        max_chars_per_call: int = 250,
        revision: str | None = None,  # a Hugging Face commit; None = the latest
    ):
        self.model_id = model
        self.revision = revision
        self.device = device
        self.attention = attention
        self.max_chars_per_call = max_chars_per_call
        self._model = None
        self._sample_rate = 24000  # replaced by the real rate after the first generation

    def _load(self):
        if self._model is None:
            import torch
            from huggingface_hub import snapshot_download
            from qwen_tts import Qwen3TTSModel

            # Download the whole repo at one commit, then load from that folder: qwen-tts passes a revision to
            # the model but not to its text processor, so loading by name could mix files from two versions.
            local_dir = snapshot_download(self.model_id, revision=self.revision)
            self._model = Qwen3TTSModel.from_pretrained(
                local_dir,
                device_map=self.device,
                dtype=torch.bfloat16,
                attn_implementation=self.attention,
            )
        return self._model

    def capabilities(self) -> TTSCapabilities:
        return TTSCapabilities(
            languages=tuple(LANGUAGES),
            cloning=True,
            min_reference_seconds=3,
            max_reference_seconds=15,
            uses_reference_transcript=True,
            sample_rate=self._sample_rate,
            max_chars_per_call=self.max_chars_per_call,
            builtin_watermark=False,
            runs_locally=True,
        )

    def synthesize(self, text: str, voice: VoiceReference, language: str, **settings: float) -> AudioClip:
        if language not in LANGUAGES:
            raise ValueError(f"Qwen3-TTS doesn't support '{language}'")
        wavs, sample_rate = self._load().generate_voice_clone(
            text=text,
            language=LANGUAGES[language],
            ref_audio=str(voice.audio_path),
            ref_text=voice.transcript,
        )
        self._sample_rate = int(sample_rate)
        samples = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
        return AudioClip(samples, self._sample_rate)
