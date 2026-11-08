# voiceover-studio

**Your own voice, your script, your AWS account.**

Describe your video, let an open-weight LLM draft the script, edit it, and get a voiceover read in **your own
cloned voice**, with captions. Everything runs on a GPU server in your own AWS account: your voice sample and
scripts never leave it (unless you choose a hosted provider).

> **Status:** tested end to end on AWS in November 2026 (set up, record, write, generate, remove everything). The
> walkthrough is the *AI Voiceover Studio* series on [wornkeys.dev](https://wornkeys.dev), being published now.

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

## Run it in your AWS account

```bash
cp .env.example .env                       # set BUDGET_EMAIL
./scripts/bootstrap.sh --profile <admin>   # once per AWS account: guardrails, deploy role, GPU quota
aws login --profile voiceover-operator
./scripts/deploy.sh                        # first time: about 25 minutes
./scripts/connect.sh                       # then open http://localhost:7860
./scripts/destroy.sh                       # when you're done: removes everything and checks
```

Needs Docker and the AWS CLI v2. The account setup is explained in [infra/bootstrap/](infra/bootstrap/README.md). Costs, auto-stop and
troubleshooting: [docs/deploy.md](docs/deploy.md). Every AWS service involved: [docs/aws-services.md](docs/aws-services.md).

## Layout

How it's built and how to work on it: [docs/architecture.md](docs/architecture.md). To learn from the code itself,
follow the guided tour in [docs/learn/](docs/learn/README.md): how a voiceover is made, the UI, the Terraform, and
what the deploy scripts do.

| Path | What |
|---|---|
| `voiceover_studio/core/` | The fixed workflow: script, chunking, consent, watermark, render |
| `voiceover_studio/providers/` | Provider interfaces (TTS, LLM, speech-to-text, storage) and the registry |
| `voiceover_studio/plugins/` | Plugins: `fit_to_length`, `translate`. Write your own: [docs/plugins.md](docs/plugins.md) |
| `config.yaml`, `.env.example` | App settings and deployment settings |
| `Dockerfile`, `docker/compose.yaml` | The app image and the two containers on the instance (app + vLLM) |
| `infra/bootstrap/` | One-time account setup: guardrail policies, deploy role, operator user (`scripts/bootstrap.sh`) |
| `infra/terraform/`, `infra/instance/` | AWS resources; install/update and idle auto-stop on the instance |
| `scripts/*.sh`, `toolbox/` | Bootstrap, deploy, connect, start, stop, status, secrets, destroy (run in a toolbox container) |
| `scripts/check_no_audio.py` | Keeps voice recordings out of git (pre-commit + CI) |

## Development

```bash
uv sync                      # Python 3.12 + dev tools
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv tool install pre-commit && pre-commit install
uv sync --extra gpu          # optional: the real models (Linux + NVIDIA GPU; CPU works, slowly)
```

## How this was built

Built by Shailendra Karambe with [Claude Code](https://claude.com/claude-code) as an AI pair programmer.
I designed the system and its guardrails, made the decisions and tested everything on a real AWS account;
Claude Code wrote much of the code and documentation under my direction and review. Commits it helped with
carry a `Co-Authored-By` line.

## License

MIT for this code. Models are downloaded at deploy time under their own licences (listed per provider).
