# Deploy to your AWS account

One GPU instance in your own AWS account runs everything: the voice model, the script writer (LLM) and the app.
Nothing is reachable from the internet. You open the studio through a private Session Manager tunnel at
`http://localhost:7860`.

```
your machine                               AWS account (us-east-1)
┌──────────────────────────┐               ┌────────────────────────────────────────────────────┐
│ browser → localhost:7860 │──SSM tunnel──▶│ EC2 g6.xlarge (no inbound ports)                   │
│ scripts/*.sh             │               │   app (voice model, watermark)  vLLM (Qwen3.5-9B)  │
│   └ toolbox container:   │──AWS APIs────▶│ S3 bucket: voices/, outputs/, deploy/              │
│     Terraform, AWS CLI   │               │ CloudWatch logs + idle alarm, budget, IAM role      │
└──────────────────────────┘               └────────────────────────────────────────────────────┘
```

## What you need

- **Docker** (Docker Desktop on Windows/macOS) and the **AWS CLI v2 ≥ 2.32**. Everything else (Terraform, the
  Session Manager plugin) runs in a toolbox container the scripts build on first use.
- **Bash**: macOS and Linux have it. On Windows, use Git Bash or WSL.
- An AWS account prepared once (below), with a **GPU quota of 4 vCPUs** approved. Request it first: approval can
  take hours to days.

## One-time AWS setup

Done once per account by an admin. Your existing AWS account works: the guardrails apply to the project's own
deploy role, not to anything else in the account. (A separate account only makes the bill easier to read. In a
shared one, set `BUDGET_MONTHLY_USD` to your usual spend plus about $30, because the project budget counts the
whole account.) It creates the guardrails that make a surprise bill very unlikely:

| Piece | What it does |
|---|---|
| Deploy role `VoiceoverStudioDeployer` (MFA required) | The scripts run as this role. It can only create this project's resources, only in us-east-1, only the four allowed instance types, no open ports, no paid images |
| Instance permissions boundary | Caps what the instance's own role can ever do: its bucket, its parameters, its logs, SSM |
| GPU quota: 4 vCPUs | At most one GPU instance can run |
| Account budget + cost anomaly alerts | Emails when spending goes up |

One command sets it all up, with an admin profile (it shows the changes and asks first; safe to re-run):

```bash
./scripts/bootstrap.sh --profile <your-admin-profile>
```

A few steps need you or your phone (root MFA, the operator's password and MFA device); the script lists what's
still missing. Details, the policy files and the console-only alternative: [infra/bootstrap/README.md](../infra/bootstrap/README.md).

You end up with two AWS CLI profiles: `voiceover-operator` (you sign in with `aws login`) and `voiceover` (assumes
the deploy role with your MFA code). `.env` only names the second one.

## Deploy

```bash
cp .env.example .env          # then set BUDGET_EMAIL (and anything else you want to change)
aws login --profile voiceover-operator
./scripts/deploy.sh           # asks for your MFA code, shows the plan, asks before creating anything
./scripts/connect.sh          # opens the tunnel: browse to http://localhost:7860
```

The first deploy takes **about 25 minutes** (measured: 26), up to an hour on a slow day: Terraform (~3 min), building the app image (~5 GB of Python
packages), the vLLM image (~10 GB), then the models (voice ~4 GB, script writer ~9 GB). Later deploys take a
few minutes. The install runs in the background on the instance and `deploy.sh` shows its log as it goes. Ctrl+C
only stops the watching; `./scripts/deploy.sh --follow` picks it up again.

`deploy.sh` is safe to re-run: it updates only what changed, and always ships your current working copy
(including uncommitted changes; `.env`, recordings and anything else in `.gitignore` are never included).

## Daily use

| Command | What it does |
|---|---|
| `./scripts/connect.sh [port]` | Starts the instance if it's stopped, waits for the app, opens the tunnel |
| `./scripts/stop.sh` | Stops the instance. Everything is kept; only the disk is charged (~$12/month for 150 GB) |
| `./scripts/start.sh` | Starts it and waits for the app |
| `./scripts/status.sh` | State, app health, GPU memory, last deploy log lines |
| `./scripts/secret.sh put /voiceover-studio/hf-token` | Stores a secret (typed in, never shown) in SSM Parameter Store |
| `./scripts/destroy.sh` | Removes everything, see below |

**Auto-stop.** The instance stops itself after `IDLE_STOP_MINUTES` (default 30) without anyone using the app.
Rendering counts as use; an open browser tab doesn't. If that timer ever fails, a CloudWatch alarm stops the
instance after 60 minutes of near-zero CPU. Working in a shell on the instance? Pause the timer with
`sudo touch /run/voiceover/keep-awake` (it expires after 8 hours).

## What it costs

us-east-1 on-demand prices; check current prices for your region.

| Item | Price |
|---|---|
| g6.xlarge (L4 24 GB) while running | ≈ $0.80 / hour |
| 150 GB gp3 disk, running or stopped | ≈ $12 / month |
| Public IPv4 address while running | ≈ $0.005 / hour |
| S3, logs, alarm, budget | cents |

A one-time try (deploy, two hours of use, destroy) costs about **$2 to $4**. Left running by mistake for a month,
it would be ≈ $600; that's what the auto-stop, the alarm and the budget emails are for.

**Measured** (g6.xlarge, us-east-1, 2026-11-08):

| What | Time | Cost |
|---|---|---|
| First deploy on a fresh instance (image build + ~25 GB of downloads) | 26 minutes | ≈ $0.35 |
| A 66-second voiceover (about 165 words) | under 1 minute, faster than real time | ≈ $0.01 |
| GPU memory with both models loaded | 15.8 of 23 GB | |

So a minute of finished voiceover costs about one cent of GPU time. What you pay for is mostly the time the
instance is on, which is why it stops itself when idle.

## Remove everything

```bash
./scripts/destroy.sh
```

1. Offers to download your voices and outputs to `backups/` first (skip with `--no-keep-outputs`).
2. Deletes the instance, disk, bucket, logs, alarm, budget, instance role and every `/voiceover-studio/` secret.
3. Checks that nothing tagged `project=voiceover-studio` is left, and fails loudly if something is. AWS's tag
   index keeps listing deleted resources for a while (even hours), so each one it lists is confirmed with its own
   service first: EC2 for instances and disks, S3 for the bucket, and so on.

Kept: your AWS account, its one-time setup and the GPU quota (none of them cost anything). Add `--purge-local` to
also remove the local Terraform state and the toolbox image. Check **Billing > Bills** the next day.

### Manual clean-up

If `destroy.sh` stopped halfway or the local state is lost, remove these in the AWS console (us-east-1). Each
carries the tag `project=voiceover-studio`, so **Resource Groups > Tag Editor** (tag `project`) lists them:

- EC2: the instance `voiceover-studio` (terminate), then the security group `voiceover-studio`
- S3: bucket `voiceover-studio-<account>-us-east-1` (empty it, then delete)
- IAM: role `voiceover-studio-instance` and its instance profile
- CloudWatch: log group `/voiceover-studio/app`, alarm `voiceover-studio-idle-stop`
- Budgets: `voiceover-studio-monthly`
- Systems Manager > Parameter Store: anything under `/voiceover-studio/`

## When something goes wrong

| Symptom | Fix |
|---|---|
| `No credentials for profile 'voiceover'` | `aws login --profile voiceover-operator`, then try again |
| `GPU quota is 0 vCPUs` | Service Quotas > Amazon EC2 > "Running On-Demand G and VT instances" > request 4 |
| `AWS has no free g6.xlarge in <zone>` (`InsufficientInstanceCapacity`) | AWS has no spare GPU of that type in that zone right now; the scripts already retried for 5 minutes. A stopped instance can only start in its own zone. Try later, or set `AVAILABILITY_ZONE` to another zone from the list the message (and preflight) shows and run `./scripts/deploy.sh --replace-instance`. `INSTANCE_TYPE=g5.xlarge` is the fallback type |
| The instance stopped while you weren't using it, or right after a failed install | The idle auto-stop working as intended: with no app running and no install in progress, it stops the instance after `IDLE_STOP_MINUTES`. `connect.sh`, `start.sh` and `deploy.sh` start it again |
| `AccessDenied` from Terraform | The deploy role doesn't allow that action. That's the guardrails working: check what you changed |
| Deploy fails on the instance | The output shows the failing step. Full log: `/var/log/voiceover-update.log` (`aws ssm start-session --target <instance-id>` as the deploy role), or CloudWatch log group `/voiceover-studio/app` |
| `Not enough disk space`, `no space left on device`, `failed to extract layer` | Raise `ROOT_VOLUME_GB` in `.env` (150 is the default, 200 the maximum), then `./scripts/deploy.sh`. The plan replaces the instance: a disk can't be resized in place by the deploy role |
| The app says the voice model is out of memory | Lower `LLM_GPU_MEMORY` (e.g. 0.45) and `LLM_MAX_MODEL_LEN`, then deploy |
| Your AWS session expired during a long deploy | The install keeps running on the instance. Sign in again and run `./scripts/deploy.sh --follow` |
| `An install is already running on the instance` | Follow it: `./scripts/deploy.sh --follow` |
| Docker on Windows: "the input device is not a TTY" | Use Git Bash (the scripts use `winpty` there) or WSL |
| Recording: the timer doesn't move, playback doesn't work, the page freezes (Brave) | Brave's fingerprinting protection alters audio data that pages read, which makes the recorder's audio encoding very slow ([gradio#13898](https://github.com/gradio-app/gradio/issues/13898)). Use Firefox, Chrome or Edge, or turn off Shields → "Block fingerprinting" for `localhost`. Or upload a recording made with another app |

## How it fits together

- `infra/terraform/`: the AWS resources. State is local (`infra/terraform/terraform.tfstate`): keep it, it's how
  `destroy.sh` knows what to delete.
- `infra/instance/`: what runs on the instance: `update.sh` (install/update, run by `deploy.sh` through SSM) and the
  idle auto-stop.
- `docker/compose.yaml`: the two containers. The app image (`Dockerfile`) is built on the instance; vLLM is the
  official image.
- `scripts/`: the commands above. `scripts/lib/host.sh` gets short-lived credentials on your machine and runs the
  real script (`scripts/toolbox/`) inside the toolbox container, which never sees `~/.aws`.
