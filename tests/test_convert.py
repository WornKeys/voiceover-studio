import shutil
import subprocess

import pytest

from tests.fakes import tone
from voiceover_studio.core.audio import read_wav, write_wav
from voiceover_studio.core.convert import ConversionError, to_wav_pcm16
from voiceover_studio.providers.base import AudioClip

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def test_converts_other_rates_and_formats_to_mono_pcm16(tmp_path):
    source = write_wav(AudioClip(tone(1.0, rate=44100).samples, 44100), tmp_path / "in.wav")
    mp3 = tmp_path / "in.mp3"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(source), str(mp3)], check=True)

    out = tmp_path / "out.wav"
    out.write_bytes(to_wav_pcm16(mp3.read_bytes(), 24000))
    clip = read_wav(out)
    assert clip.sample_rate == 24000
    assert 0.9 < clip.seconds < 1.2  # mp3 adds a little padding


def test_non_audio_is_rejected_with_a_plain_message():
    with pytest.raises(ConversionError, match="doesn't look like audio"):
        to_wav_pcm16(b"this is not audio at all", 24000)
