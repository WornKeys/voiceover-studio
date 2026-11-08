# voiceover-studio

**Your own voice, your script, your AWS account.**

Describe your video, let an open-weight LLM draft the script, edit it, and get a voiceover read in **your own
cloned voice**, with captions. Everything runs on a GPU server in your own AWS account: your voice sample and
scripts never leave it (unless you choose a hosted provider).

> **Status: work in progress.** Not ready to use yet. The walkthrough is the *AI Voiceover Studio* series on
> [wornkeys.dev](https://wornkeys.dev) (coming soon).

## How it works

```
record / upload your voice ─▶ consent + quality check ─┐
describe the video ─▶ LLM drafts script ─▶ you edit + approve ─▶ plugins ─▶ text-to-speech in your voice
                                                                                       │
                          voiceover.wav / .mp3 + captions.srt ◀─ watermark + loudness ─┘
```

- **Voice:** [Qwen3-TTS](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base) (Apache-2.0), cloned from a short
  recording of you reading a consent sentence.
- **Script:** Qwen3.5 (Apache-2.0) served on the same GPU, or any OpenAI-compatible endpoint.
- **Core + providers + plugins:** the core workflow stays fixed. Models and vendors are *providers* you pick in
  `.env`. New features are server-side *plugins* the UI discovers automatically.
- **Guardrails built into the core:** a consent recording before any cloning, an
  [AudioSeal](https://github.com/facebookresearch/audioseal) watermark and an "AI-generated" label on every file.

## Use it responsibly

Clone **only your own voice**, or a voice whose owner has agreed. Tell your audience the voice is AI-generated.
See [RESPONSIBLE_USE.md](RESPONSIBLE_USE.md).

## Layout

| Path | What |
|---|---|
| `voiceover_studio/providers/` | Provider interfaces (TTS, LLM, speech-to-text, storage) and the registry |
| `voiceover_studio/plugins/` | Plugins: `fit_to_length`, `translate`. Write your own: [docs/plugins.md](docs/plugins.md) |
| `config.yaml`, `.env.example` | App settings and deployment settings |
| `scripts/check_no_audio.py` | Keeps voice recordings out of git (pre-commit + CI) |

## Development

```bash
uv sync                      # Python 3.12 + dev tools
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv tool install pre-commit && pre-commit install
```

## License

MIT for this code. Models are downloaded at deploy time under their own licences (listed per provider).
