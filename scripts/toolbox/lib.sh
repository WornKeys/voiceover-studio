#!/usr/bin/env bash
# Helpers for the scripts that run inside the toolbox container (the repo is mounted at /work).
set -euo pipefail
cd /work

TF_DIR=infra/terraform
DEFAULT_LLM_MODEL=cyankiwi/Qwen3.5-9B-AWQ-4bit # keep in step with voiceover_studio/settings.py

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
warn() { printf '\033[33mWarning:\033[0m %s\n' "$*" >&2; }
die() {
  printf '\033[31mError:\033[0m %s\n' "$*" >&2
  exit 1
}

confirm() {
  [[ -t 0 ]] || die "This needs a yes/no answer: run it in a terminal, or add --yes."
  local answer
  read -r -p "$1 [y/N] " answer
  [[ "$answer" =~ ^[Yy] ]]
}

# Read .env as data (KEY=value lines), never as shell code. Tolerates Windows line endings and quotes.
load_env() {
  [[ -f .env ]] || die "No .env file. Run: cp .env.example .env, then fill in your values."
  local line n=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    n=$((n + 1))
    line=${line%$'\r'}
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
    if [[ "$line" =~ ^([A-Z][A-Z0-9_]*)=(.*)$ ]]; then
      local key=${BASH_REMATCH[1]} value=${BASH_REMATCH[2]}
      value=${value#\"}
      value=${value%\"}
      export "$key=$value"
    else
      warn ".env line $n isn't KEY=value; ignored."
    fi
  done <.env

  export AWS_REGION=${AWS_REGION:-us-east-1}
  export AWS_DEFAULT_REGION=$AWS_REGION
  unset AWS_PROFILE # inside the toolbox, credentials come from the environment
  export LLM_BASE_URL=${LLM_BASE_URL:-http://llm:8000/v1}
  export LLM_MODEL=${LLM_MODEL:-$DEFAULT_LLM_MODEL}
  export COMPUTE_PROFILE
  COMPUTE_PROFILE=$(resolve_profile)
  local default_type=g6.xlarge
  [[ "$COMPUTE_PROFILE" == cpu ]] && default_type=t3.medium
  export INSTANCE_TYPE=${INSTANCE_TYPE:-$default_type}

  export TF_VAR_region=$AWS_REGION
  export TF_VAR_compute_profile=$COMPUTE_PROFILE
  export TF_VAR_instance_type=$INSTANCE_TYPE
  export TF_VAR_root_volume_gb=${ROOT_VOLUME_GB:-100}
  export TF_VAR_idle_stop_minutes=${IDLE_STOP_MINUTES:-30}
  export TF_VAR_budget_monthly_usd=${BUDGET_MONTHLY_USD:-30}
  export TF_VAR_budget_email=${BUDGET_EMAIL:-}
  export TF_VAR_availability_zone=${AVAILABILITY_ZONE:-}
  export TF_VAR_ami_id=${AMI_ID:-}
}

llm_is_local() {
  local host
  host=$(sed -E 's#^[a-zA-Z]+://([^/:]+).*#\1#' <<<"$LLM_BASE_URL")
  [[ "$host" == llm || "$host" == localhost || "$host" == 127.0.0.1 ]]
}

# gpu if any model runs on the instance. Keep in step with Settings.resolved_compute_profile.
resolve_profile() {
  if [[ -n "${COMPUTE_PROFILE:-}" ]]; then
    [[ "$COMPUTE_PROFILE" == gpu || "$COMPUTE_PROFILE" == cpu ]] || die "COMPUTE_PROFILE must be gpu, cpu or empty."
    echo "$COMPUTE_PROFILE"
  elif [[ "${TTS_PROVIDER:-qwen3_tts}" != fish_audio ]] || llm_is_local || [[ "${ASR_DEVICE:-cpu}" == cuda ]]; then
    echo gpu
  else
    echo cpu
  fi
}

tf() { terraform -chdir="$TF_DIR" "$@"; }
tf_init() { tf init -input=false >/dev/null || die "terraform init failed (see above)."; }
tf_out() { tf output -raw "$1" 2>/dev/null; }
deployed() { [[ -n "$(tf state list 2>/dev/null)" ]]; }

instance_id() {
  local id
  id=$(tf_out instance_id) || true
  [[ -n "$id" ]] || die "Nothing is deployed yet (or the local Terraform state is missing). Run ./scripts/deploy.sh."
  echo "$id"
}

instance_state() {
  aws ec2 describe-instances --instance-ids "$1" --query 'Reservations[0].Instances[0].State.Name' --output text
}

ensure_running() {
  local id=$1 state out
  state=$(instance_state "$id")
  case "$state" in
    running) return 0 ;;
    pending) ;;
    stopping)
      say "The instance is still stopping; waiting before starting it again"
      aws ec2 wait instance-stopped --instance-ids "$id"
      ;&
    stopped)
      say "Starting the instance ($INSTANCE_TYPE)"
      if ! out=$(aws ec2 start-instances --instance-ids "$id" 2>&1); then
        if [[ "$out" == *InsufficientInstanceCapacity* ]]; then
          die "AWS has no free $INSTANCE_TYPE in this zone right now. Try again in a few minutes, or set
       AVAILABILITY_ZONE in .env and run ./scripts/deploy.sh --replace-instance."
        fi
        die "$out"
      fi
      ;;
    *) die "The instance is $state." ;;
  esac
  aws ec2 wait instance-running --instance-ids "$id"
}

wait_ssm() {
  local id=$1 status
  say "Waiting for the instance to connect to Session Manager"
  for _ in $(seq 1 60); do
    status=$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$id" \
      --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || true)
    [[ "$status" == Online ]] && return 0
    sleep 10
  done
  die "The instance didn't connect to Session Manager within 10 minutes. Check it in the EC2 console
       (Actions > Monitor > Get system log)."
}

# Run a shell command on the instance as root (SSM Run Command) and print its output.
# Returns the command's success. Usage: run_remote <instance-id> <timeout-seconds> <command> [quiet]
run_remote() {
  local id=$1 timeout=$2 cmd=$3 quiet=${4:-} params cid status err minute last=-1
  params=$(jq -n --arg c "$cmd" --arg t "$timeout" '{commands: [$c], executionTimeout: [$t]}')
  cid=$(aws ssm send-command --instance-ids "$id" --document-name AWS-RunShellScript \
    --comment voiceover-studio --parameters "$params" --query Command.CommandId --output text)
  local start=$SECONDS
  while :; do
    sleep 5
    if ! status=$(aws ssm get-command-invocation --command-id "$cid" --instance-id "$id" \
      --query Status --output text 2>/tmp/ssm-error); then
      err=$(cat /tmp/ssm-error)
      [[ "$err" == *InvocationDoesNotExist* ]] && continue # not registered yet
      [[ "$err" == *xpired* ]] && die "Your AWS session expired while waiting. The command keeps running on the
       instance: check it with ./scripts/status.sh"
      die "$err"
    fi
    case "$status" in
      Pending | InProgress | Delayed)
        minute=$(((SECONDS - start) / 60))
        if [[ -z "$quiet" && $minute -gt $last && $minute -gt 0 ]]; then
          note "... still working ($minute min)"
          last=$minute
        fi
        ;;
      *) break ;;
    esac
  done
  if [[ -z "$quiet" || "$status" != Success ]]; then
    aws ssm get-command-invocation --command-id "$cid" --instance-id "$id" \
      --query '[StandardOutputContent, StandardErrorContent]' --output text | sed 's/^/    /'
  fi
  [[ "$status" == Success ]]
}

app_healthy() {
  run_remote "$1" 30 "curl -fsS --max-time 5 http://127.0.0.1:7860/api/health" quiet >/dev/null 2>&1
}
