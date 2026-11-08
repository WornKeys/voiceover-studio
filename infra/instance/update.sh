#!/usr/bin/env bash
# Install or update the app on the instance (as root). scripts/deploy.sh extracts the release to
# /opt/voiceover/releases/<release> and starts this in the background with start-update.sh:
#   update.sh <bucket> <release>
# Steps: settings + secrets -> build the image -> download/load the models -> start -> wait until healthy.
# Safe to re-run. Log: /var/log/voiceover-update.log. Outcome ("<release> <exit code>"): /opt/voiceover/update-result
set -euo pipefail

BUCKET=$1
RELEASE=$2
ROOT=/opt/voiceover
RELEASE_DIR=$ROOT/releases/$RELEASE
COMPOSE_VERSION=v5.6.1 # installed only if the AMI has no Docker Compose plugin
APP_UID=10001          # the user the app container runs as (see Dockerfile)

exec > >(tee -a /var/log/voiceover-update.log) 2>&1
step() { echo "==> $(date -u +%H:%M:%S) $*"; }

# Pause the idle auto-stop while this runs (idle-stop.sh ignores the flag after 3 hours), and record the
# outcome for deploy.sh, which follows the log.
mkdir -p /run/voiceover
touch /run/voiceover/updating
finish() {
  local rc=$?
  rm -f /run/voiceover/updating
  echo "$RELEASE $rc" >"$ROOT/update-result"
  if ((rc != 0)); then
    echo "==> $(date -u +%H:%M:%S) Failed (exit code $rc). Disk: $(disk)"
    if (($(free_gb) < 5)); then
      echo "    The disk is full. Set ROOT_VOLUME_GB=150 (or more, up to 200) in .env, then run"
      echo "    ./scripts/deploy.sh (the plan replaces the instance with the bigger disk)"
    fi
  fi
}
trap finish EXIT

disk() { df -h --output=used,size,avail / | tail -n 1 | awk '{ print $1 " used of " $2 ", " $3 " free" }'; }
free_gb() { df --output=avail -BG / | tail -n 1 | tr -dc 0-9; }

# Read one KEY=value from the settings file (no `source`: values are data, not shell code).
setting() { sed -n "s/^$1=//p" "$ROOT/app.env" | tail -n 1; }

step "Release $RELEASE"
aws s3 cp --only-show-errors "s3://$BUCKET/deploy/$RELEASE/app.env" "$ROOT/app.env"
chmod 644 "$ROOT/app.env"
export AWS_DEFAULT_REGION
AWS_DEFAULT_REGION=$(setting AWS_REGION)
profile=$(setting COMPUTE_PROFILE)

# Secrets come from SSM Parameter Store at deploy time and stay on the instance (root-only file).
umask 077
: >"$ROOT/secrets.env"
if hf_param=$(setting HF_TOKEN_PARAM) && [[ -n "$hf_param" ]]; then
  step "Reading the Hugging Face token from $hf_param"
  token=$(aws ssm get-parameter --name "$hf_param" --with-decryption --query Parameter.Value --output text)
  printf 'HF_TOKEN=%s\n' "$token" >>"$ROOT/secrets.env"
  unset token
fi
umask 022

step "Checking Docker"
if ! command -v docker >/dev/null; then
  dnf install -y docker # Amazon Linux (cpu profile); the Deep Learning AMI has Docker already
  systemctl enable --now docker
fi
if ! docker compose version >/dev/null 2>&1; then
  step "Installing Docker Compose $COMPOSE_VERSION"
  plugin_dir=/usr/local/lib/docker/cli-plugins
  asset="docker-compose-linux-$(uname -m)"
  mkdir -p "$plugin_dir"
  curl -fsSL -o "$plugin_dir/docker-compose" \
    "https://github.com/docker/compose/releases/download/$COMPOSE_VERSION/$asset"
  expected=$(curl -fsSL "https://github.com/docker/compose/releases/download/$COMPOSE_VERSION/$asset.sha256" | cut -d' ' -f1)
  echo "$expected  $plugin_dir/docker-compose" | sha256sum -c -
  chmod +x "$plugin_dir/docker-compose"
fi
if [[ "$profile" == gpu ]]; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
fi

step "Idle auto-stop: $(setting IDLE_STOP_MINUTES) minutes"
setting IDLE_STOP_MINUTES >"$ROOT/idle-minutes"
mkdir -p "$ROOT/bin"
install -m 755 "$RELEASE_DIR/infra/instance/idle-stop.sh" "$ROOT/bin/idle-stop.sh"
install -m 644 "$RELEASE_DIR/infra/instance/voiceover-idle.service" /etc/systemd/system/
install -m 644 "$RELEASE_DIR/infra/instance/voiceover-idle.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now voiceover-idle.timer

mkdir -p "$ROOT/cache/app" "$ROOT/cache/llm"
chown "$APP_UID" "$ROOT/cache/app"
ln -sfn "$RELEASE_DIR" "$ROOT/current"

export COMPOSE_PROFILES
COMPOSE_PROFILES=$(setting COMPOSE_PROFILES)
compose=(docker compose -f "$ROOT/current/docker/compose.yaml" --env-file "$ROOT/app.env" --env-file "$ROOT/secrets.env")
if [[ "$profile" == cpu ]]; then
  compose+=(-f "$ROOT/current/docker/compose.cpu.yaml")
fi

# Enough disk for what isn't there yet? Downloading an image needs room for the compressed and the unpacked copy.
step "Disk: $(disk)"
need=15 # models (~13 GB when new), logs, room to work
while read -r image; do
  docker image inspect "$image" >/dev/null 2>&1 && continue
  case "$image" in
    vllm/*) need=$((need + 30)) ;; # ~9 GB download, ~20 GB unpacked
    *) need=$((need + 20)) ;;      # the app image: ~10 GB, plus room to build it
  esac
done < <("${compose[@]}" config --images)
if (($(free_gb) < need)); then
  echo "Not enough disk space: about $need GB free is needed, $(free_gb) GB is. Set ROOT_VOLUME_GB=150 (up to 200)" >&2
  echo "in .env, then run ./scripts/deploy.sh (the plan replaces the instance with the bigger disk)" >&2
  exit 1
fi

if [[ "$COMPOSE_PROFILES" == *local-llm* ]]; then
  step "Downloading the script writer's server image (vLLM, ~9 GB; first time only)"
  "${compose[@]}" pull --quiet llm
fi

step "Building the app image (the first build downloads ~5 GB of Python packages)"
"${compose[@]}" build --pull app
docker builder prune -f >/dev/null # leftovers from earlier builds

step "Downloading and loading the voice, speech-to-text and watermark models"
"${compose[@]}" stop app >/dev/null 2>&1 || true
"${compose[@]}" run --rm --no-deps app python -m voiceover_studio.prefetch

step "Starting (the first start of the script writer downloads its ~9 GB model; up to 30 minutes)"
"${compose[@]}" up -d --remove-orphans --wait --wait-timeout 2700
"${compose[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
curl -fsS http://127.0.0.1:7860/api/health
echo

step "Cleaning up old releases and images"
find "$ROOT/releases" -mindepth 1 -maxdepth 1 -type d ! -name "$RELEASE" -printf '%T@ %p\n' |
  sort -rn | tail -n +3 | cut -d' ' -f2- | xargs -r rm -rf
docker image prune -f >/dev/null

step "Ready. Disk: $(disk)"
