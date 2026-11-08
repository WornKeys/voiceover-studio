# Learn from the code

The blog series on [wornkeys.dev](https://wornkeys.dev) explains the ideas and the decisions. These chapters are
the other half: a guided tour of the actual code, so you can see how each idea is built and change it with
confidence.

Read them with the files open next to you. Each chapter follows one path through the code, quotes the important
lines and links to the files. You don't need to know Gradio or Terraform beforehand; basic Python and a rough
idea of what AWS is are enough.

| Chapter | Follows | Goes with |
|---|---|---|
| [1. How a voiceover is made](01-how-a-voiceover-is-made.md) | One voice, one script and one render, from the app's entry point through the core, the providers and the storage | Parts 1 and 2 |
| [2. The UI](02-the-ui.md) | How the guided page is built with Gradio: steps, events, plugins, progress, and how it's tested without a browser | Part 2 |
| [3. The infrastructure (Terraform)](03-terraform.md) | Every file in `infra/terraform/`: what it creates, why, and how it fits the account's guardrails | Part 3 |
| [4. Deploying and running it](04-deploy-and-run.md) | What `deploy.sh`, `connect.sh` and `destroy.sh` actually do: the toolbox, SSM, the install on the instance, the idle stop | Part 3 |

Related reference pages:

- [architecture.md](../architecture.md): the overview, configuration, pinned versions and known gaps
- [plugins.md](../plugins.md): writing your own plugin, with `translate` as the worked example
- [deploy.md](../deploy.md): setup, costs, daily use and troubleshooting
- [aws-services.md](../aws-services.md): every AWS service used and what it costs
- [../../infra/bootstrap/README.md](../../infra/bootstrap/README.md): the one-time account setup

## A few ways to learn by changing things

The tests run in about 15 seconds without a GPU (`uv run pytest`), so it's cheap to experiment:

- Change `pause_between_sentences_ms` in `config.yaml` and watch the caption timings in
  `tests/test_audio_and_captions.py` move.
- Make the consent check stricter (`consent_match_threshold`) and see which test catches it.
- Add a tiny plugin that upper-cases the script, following [plugins.md](../plugins.md). The UI picks it up with
  no UI code.
- Read `tests/fakes.py`: the fake voice model speaks every word as 0.4 seconds of tone. It's how the whole
  pipeline is tested without downloading a model.
