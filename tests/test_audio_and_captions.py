import numpy as np
import pyloudnorm

from tests.fakes import RATE, tone
from voiceover_studio.core.audio import (
    concat,
    normalize_loudness,
    peak_dbfs,
    read_wav,
    read_wav_info,
    trim_silence,
    write_wav,
)
from voiceover_studio.core.captions import Cue, make_cues, to_srt
from voiceover_studio.providers.base import AudioClip


def test_concat_inserts_pauses_and_reports_timings():
    joined, timings = concat([tone(1.0), tone(0.5)], pause_ms=250)
    assert timings == [(0.0, 1.0), (1.25, 1.75)]
    assert abs(joined.seconds - 1.75) < 1e-6


def test_loudness_is_normalized_and_peaks_are_limited():
    quiet = tone(3.0, amplitude=0.02)
    out = normalize_loudness(quiet, -16)
    measured = pyloudnorm.Meter(RATE).integrated_loudness(out.samples.astype(np.float64))
    assert abs(measured - (-16)) < 0.5

    loud = normalize_loudness(tone(3.0, amplitude=0.02), -9)  # a sine at -9 LUFS would peak above -1 dBFS
    assert peak_dbfs(loud) <= -0.99


def test_trim_silence_keeps_speech_and_padding():
    silence = np.zeros(RATE, dtype=np.float32)
    clip = AudioClip(np.concatenate([silence, tone(1.0).samples, silence]), RATE)
    trimmed = trim_silence(clip, pad_ms=100)
    assert 1.1 <= trimmed.seconds <= 1.3


def test_wav_roundtrip_with_info_metadata(tmp_path):
    path = write_wav(tone(0.5), tmp_path / "out.wav", info={"ICMT": "AI-generated voice", "ISFT": "test 1"})
    clip = read_wav(path)
    assert clip.sample_rate == RATE and abs(clip.seconds - 0.5) < 1e-3
    assert read_wav_info(path) == {"ICMT": "AI-generated voice", "ISFT": "test 1"}


def test_srt_format_and_long_text_split():
    cues = make_cues([(0.0, 2.0, "Short line."), (2.25, 8.25, "word " * 30)], max_line_chars=42, max_lines=2)
    assert cues[0] == Cue(0.0, 2.0, "Short line.")
    assert len(cues) > 2
    assert abs(cues[-1].end - 8.25) < 1e-6
    srt = to_srt(cues[:1])
    assert srt == "1\n00:00:00,000 --> 00:00:02,000\nShort line.\n"
