import importlib.util
import struct
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "check_no_audio", Path(__file__).parents[1] / "scripts" / "check_no_audio.py"
)
check_no_audio = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_no_audio)


def wav_header() -> bytes:
    return b"RIFF" + struct.pack("<I", 36) + b"WAVEfmt "


def test_detects_audio_by_content_even_when_renamed(tmp_path):
    disguised = tmp_path / "notes.txt"
    disguised.write_bytes(wav_header() + b"\x00" * 64)
    found = check_no_audio.check_files([str(disguised)])
    assert len(found) == 1
    assert "wav" in found[0]


def test_detects_audio_by_extension(tmp_path):
    clip = tmp_path / "my-voice.m4a"
    clip.write_bytes(b"not really audio")
    assert check_no_audio.check_files([str(clip)])


def test_plain_files_pass(tmp_path):
    for name, data in [
        ("a.py", b"print('hi')\n"),
        ("b.png", b"\x89PNG\r\n\x1a\n"),
        ("c.jpg", b"\xff\xd8\xff\xe0"),
    ]:
        (tmp_path / name).write_bytes(data)
    assert check_no_audio.check_files([str(p) for p in tmp_path.iterdir()]) == []


def test_demo_voice_is_allowed():
    assert check_no_audio.problem("samples/demo-voice.wav", wav_header()) is None
    assert check_no_audio.problem("samples/other-voice.wav", wav_header()) is not None


def test_sniff_formats():
    assert check_no_audio.sniff(b"fLaC" + b"\x00" * 12) == "flac"
    assert check_no_audio.sniff(b"OggS" + b"\x00" * 12) == "ogg/opus"
    assert check_no_audio.sniff(b"ID3\x04" + b"\x00" * 12) == "mp3"
    assert check_no_audio.sniff(b"\x1a\x45\xdf\xa3" + b"\x00" * 12) == "webm/mka"
    assert check_no_audio.sniff(b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 4) == "m4a/mp4"
