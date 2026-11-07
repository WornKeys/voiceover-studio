import numpy as np
import pytest

from tests.fakes import RATE, tone
from voiceover_studio.core.config import load_config
from voiceover_studio.core.consent import ConsentError, check_sample, match_score, record_consent
from voiceover_studio.providers.base import AudioClip

CFG = load_config(environ={}).voice_sample


def test_consent_matches_despite_small_transcription_differences():
    heard = "i am recording my own voice and i agree to it being used to create voice overs for my own videos"
    assert match_score(CFG.consent_sentence, heard) > 0.85
    record = record_consent(CFG.consent_sentence, heard, b"audio-bytes", CFG.consent_match_threshold)
    assert record.consent_id and len(record.sample_sha256) == 64


def test_consent_fails_for_a_different_recording():
    with pytest.raises(ConsentError, match="doesn't match"):
        record_consent(
            CFG.consent_sentence, "hello this is a podcast intro", b"x", CFG.consent_match_threshold
        )


def test_good_sample_passes():
    rng = np.random.default_rng(0)
    speechy = tone(8.0).samples * (0.5 + 0.5 * np.sign(np.sin(np.arange(8 * RATE) / RATE * 6)))
    speechy += rng.normal(0, 1e-4, len(speechy)).astype(np.float32)
    assert check_sample(AudioClip(speechy.astype(np.float32), RATE), CFG).ok


def test_short_quiet_and_clipped_samples_are_rejected():
    assert any("Too short" in p for p in check_sample(tone(2.0), CFG).problems)
    assert any("quiet" in p for p in check_sample(tone(8.0, amplitude=0.01), CFG).problems)
    clipped = AudioClip(np.clip(tone(8.0, amplitude=2.0).samples, -1, 1), RATE)
    assert any("distorted" in p for p in check_sample(clipped, CFG).problems)


def test_silence_is_reported():
    assert check_sample(AudioClip(np.zeros(RATE * 6, dtype=np.float32), RATE), CFG).problems


def test_config_env_override():
    cfg = load_config(environ={"VS__SCRIPT__WORDS_PER_MINUTE": "140"})
    assert cfg.script.words_per_minute == 140
