#!/usr/bin/env bash
# Create or update everything. Safe to re-run: it only changes what's different.
#   1. preflight checks   2. infrastructure (Terraform, asks before changing anything)
#   3. package this repo -> S3   4. on the instance: build, download models, start, health check
#      (runs in the background there; this script follows its log)
# shellcheck source=scripts/toolbox/lib.sh
source scripts/toolbox/lib.sh

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy.sh [options]
  --yes               don't ask before applying infrastructure changes
  --infra-only        only run Terraform (don't update the app)
  --replace-instance  create a new instance (newest AMI, or after changing AVAILABILITY_ZONE).
                      The bucket (voices, outputs) is kept; models are downloaded again.
  --follow            only follow an install that's already running on the instance
                      (after Ctrl+C or an expired AWS session)
EOF
  exit 0
}

yes=false infra_only=false replace=false follow=false
for arg in "$@"; do
  case "$arg" in
    --yes | -y) yes=true ;;
    --infra-only) infra_only=true ;;
    --replace-instance) replace=true ;;
    --follow) follow=true ;;
    -h | --help) usage ;;
    *) die "Unknown option: $arg (see --help)" ;;
  esac
done

finish_install() {
  if follow_update "$1"; then
    say "Deployed. Open the studio with: ./scripts/connect.sh"
    note "The instance stops by itself after ${IDLE_STOP_MINUTES:-30} idle minutes. Stop it now: ./scripts/stop.sh"
  else
    die "The install failed (log above; full log on the instance: /var/log/voiceover-update.log).
       Fix the cause, then run ./scripts/deploy.sh again."
  fi
}

if $follow; then
  load_env
  tf_init
  id=$(instance_id)
  say "Following the install on the instance (Ctrl+C stops watching, not the install)"
  finish_install "$id"
  exit 0
fi

bash scripts/toolbox/preflight.sh
load_env

# --- 2. infrastructure --------------------------------------------------------------------------------
say "Infrastructure ($COMPUTE_PROFILE profile, $INSTANCE_TYPE, $AWS_REGION)"
tf_init
plan_args=(plan -input=false -out=deploy.tfplan -detailed-exitcode)
$replace && plan_args+=(-replace=aws_instance.app)
set +e
tf "${plan_args[@]}"
plan_status=$?
set -e
case "$plan_status" in
  0) note "No infrastructure changes." ;;
  2)
    if ! $yes; then confirm "Apply these changes?" || die "Cancelled. Nothing was changed."; fi
    tf apply -input=false deploy.tfplan
    ;;
  *) die "terraform plan failed (see above)." ;;
esac
rm -f "$TF_DIR/deploy.tfplan"
$infra_only && exit 0

id=$(instance_id)
bucket=$(tf_out bucket)

# --- 3. package ------------------------------------------------------------------------------------------
say "Packaging the app"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "Deploy from a git clone of the repository."
release="$(date -u +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD)"
[[ -z "$(git status --porcelain)" ]] || release+="-local" # includes your uncommitted changes
mkdir -p build
# Tracked and new files, minus everything .gitignore excludes: .env, voice recordings, state, caches.
git ls-files -z --cached --others --exclude-standard |
  tar --null --files-from=- --ignore-failed-read -czf build/app.tar.gz
note "$release ($(du -h build/app.tar.gz | cut -f1))"

# Settings for the app on the instance: only non-secret values (secrets stay in SSM Parameter Store).
device=cuda
[[ "$COMPUTE_PROFILE" == cpu ]] && device=cpu
compose_profiles=""
llm_is_local && compose_profiles=local-llm
{
  echo "# Written by scripts/deploy.sh from .env ($release). Settings only, no secrets."
  printf '%s=%s\n' AWS_REGION "$AWS_REGION" COMPUTE_PROFILE "$COMPUTE_PROFILE" DEVICE "$device" \
    COMPOSE_PROFILES "$compose_profiles" STORAGE_PROVIDER s3 STORAGE_BUCKET "$bucket" \
    IDLE_STOP_MINUTES "${IDLE_STOP_MINUTES:-30}" LLM_BASE_URL "$LLM_BASE_URL" LLM_MODEL "$LLM_MODEL"
  for key in TTS_PROVIDER TTS_MODEL TTS_API_KEY_PARAM LLM_PROVIDER LLM_AUTH LLM_API_KEY_PARAM \
    LLM_DISABLE_THINKING LLM_GPU_MEMORY LLM_MAX_MODEL_LEN ASR_PROVIDER ASR_MODEL ASR_DEVICE HF_TOKEN_PARAM PLUGINS; do
    if [[ -n "${!key:-}" ]]; then printf '%s=%s\n' "$key" "${!key}"; fi
  done
} >build/app.env

aws s3 cp --only-show-errors build/app.tar.gz "s3://$bucket/deploy/$release/app.tar.gz"
aws s3 cp --only-show-errors build/app.env "s3://$bucket/deploy/$release/app.env"

# --- 4. install on the instance --------------------------------------------------------------------------
ensure_running "$id"
wait_ssm "$id"
say "Starting the install on the instance"
remote="set -euo pipefail
export AWS_DEFAULT_REGION=$AWS_REGION
dir=/opt/voiceover/releases/$release
mkdir -p \"\$dir\"
aws s3 cp --only-show-errors s3://$bucket/deploy/$release/app.tar.gz - | tar -xz -C \"\$dir\"
bash \"\$dir/infra/instance/start-update.sh\" $bucket $release"
run_remote "$id" 600 "$remote" ||
  die "Couldn't start the install (output above). If one is already running: ./scripts/deploy.sh --follow"

say "Installing (first time: 30 to 60 minutes, about 25 GB of downloads; later: a few minutes)"
note "Ctrl+C stops watching, not the install. Pick it up again with: ./scripts/deploy.sh --follow"
finish_install "$id"
