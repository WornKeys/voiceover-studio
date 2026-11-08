#!/usr/bin/env bash
# Helpers for the scripts that run inside the toolbox container (the repo is mounted at /work).
set -euo pipefail
cd /work

TF_DIR=infra/terraform
# Keep in step with voiceover_studio/settings.py (the default model and PINNED_REVISIONS).
DEFAULT_LLM_MODEL=cyankiwi/Qwen3.5-9B-AWQ-4bit
DEFAULT_LLM_REVISION=e4d2d39cede8c5d1716d824cd843e2889c648083 # tested 2026-11-08

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
  # The tested version for the default model; "main" (the latest) for any other model unless you set one.
  if [[ -z "${LLM_MODEL_REVISION:-}" ]]; then
    LLM_MODEL_REVISION=main
    [[ "$LLM_MODEL" == "$DEFAULT_LLM_MODEL" ]] && LLM_MODEL_REVISION=$DEFAULT_LLM_REVISION
  fi
  export LLM_MODEL_REVISION
  export COMPUTE_PROFILE
  COMPUTE_PROFILE=$(resolve_profile)
  local default_type=g6.xlarge
  [[ "$COMPUTE_PROFILE" == cpu ]] && default_type=t3.medium
  export INSTANCE_TYPE=${INSTANCE_TYPE:-$default_type}

  export TF_VAR_region=$AWS_REGION
  export TF_VAR_compute_profile=$COMPUTE_PROFILE
  export TF_VAR_instance_type=$INSTANCE_TYPE
  export TF_VAR_root_volume_gb=${ROOT_VOLUME_GB:-150}
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

# Zones in the region that offer the instance type (capacity can still run out in any of them).
offered_zones() {
  aws ec2 describe-instance-type-offerings --location-type availability-zone \
    --filters "Name=instance-type,Values=$INSTANCE_TYPE" --query 'InstanceTypeOfferings[].Location' --output text |
    tr '\t' '\n' | sort | tr '\n' ' '
}

instance_zone() {
  aws ec2 describe-instances --instance-ids "$1" \
    --query 'Reservations[0].Instances[0].Placement.AvailabilityZone' --output text
}

ensure_running() {
  local id=$1 state out attempt zone
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
      # GPU capacity in one zone often comes back within minutes: retry for about 5 minutes.
      for attempt in $(seq 1 10); do
        out=$(aws ec2 start-instances --instance-ids "$id" 2>&1) && break
        [[ "$out" == *InsufficientInstanceCapacity* ]] || die "$out"
        if ((attempt == 10)); then
          zone=$(instance_zone "$id")
          die "AWS has no free $INSTANCE_TYPE in $zone right now (tried for 5 minutes). A stopped instance
       can only start in its own zone. Options:
         - try again later, or
         - move it: set AVAILABILITY_ZONE to another zone in .env, then ./scripts/deploy.sh --replace-instance
           Zones offering $INSTANCE_TYPE: $(offered_zones)
         - or set INSTANCE_TYPE=g5.xlarge in .env and run ./scripts/deploy.sh
       Replacing the instance keeps the bucket (voices, outputs); the models download again."
        fi
        note "No free $INSTANCE_TYPE in this zone right now; trying again in 30 seconds ($attempt/10)"
        sleep 30
      done
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

# Run a bash command on the instance as root (SSM Run Command). Returns the command's success.
# Usage: run_remote <instance-id> <timeout-seconds> <command> [mode]
#   mode "":        print stdout + stderr, indented, and a progress note every minute
#   mode "quiet":   print only if it failed
#   mode "capture": print stdout as-is (for parsing); stderr too if it failed
run_remote() {
  local id=$1 timeout=$2 cmd=$3 mode=${4:-} params cid status err minute last=-1
  # AWS-RunShellScript runs the lines with /bin/sh (dash on Ubuntu: no pipefail), so the command is written
  # to a file (quoted heredoc: passed through unchanged) and run with bash, stdin closed.
  [[ "$cmd" != *VOICEOVER_REMOTE_EOF* ]] || die "run_remote: the command contains the heredoc marker."
  cmd="f=\$(mktemp)
cat >\"\$f\" <<'VOICEOVER_REMOTE_EOF'
$cmd
VOICEOVER_REMOTE_EOF
bash \"\$f\" </dev/null
rc=\$?
rm -f \"\$f\"
exit \$rc"
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
      [[ "$err" == *xpired* ]] && die "Your AWS session expired. Anything already started keeps running on the
       instance. Sign in again, then: ./scripts/deploy.sh --follow (an install) or ./scripts/status.sh"
      die "$err"
    fi
    case "$status" in
      Pending | InProgress | Delayed)
        minute=$(((SECONDS - start) / 60))
        if [[ -z "$mode" && $minute -gt $last && $minute -gt 0 ]]; then
          note "... still working ($minute min)"
          last=$minute
        fi
        ;;
      *) break ;;
    esac
  done
  if [[ "$mode" == capture ]]; then
    aws ssm get-command-invocation --command-id "$cid" --instance-id "$id" \
      --query StandardOutputContent --output text
    if [[ "$status" != Success ]]; then
      aws ssm get-command-invocation --command-id "$cid" --instance-id "$id" \
        --query StandardErrorContent --output text >&2
    fi
  elif [[ -z "$mode" || "$status" != Success ]]; then
    aws ssm get-command-invocation --command-id "$cid" --instance-id "$id" \
      --query '[StandardOutputContent, StandardErrorContent]' --output text | sed 's/^/    /'
  fi
  [[ "$status" == Success ]]
}

# Follow the background install (infra/instance/start-update.sh): print new lines of its log every 15 seconds
# until it ends. Succeeds if update.sh finished with exit code 0. Ctrl+C stops watching, not the install.
follow_update() {
  local id=$1 shown=0 out state result lines count new_lines
  while :; do
    # SSM returns at most 24,000 characters of output: 60 lines per poll, and long lines shortened in the
    # middle (the end of an error message is usually the important part).
    out=$(run_remote "$id" 60 "start=\$(cat /opt/voiceover/update-log-start 2>/dev/null || echo 0)
echo \"STATE \$(systemctl is-active voiceover-update 2>/dev/null || true)\"
echo \"RESULT \$(cat /opt/voiceover/update-result 2>/dev/null || true)\"
tail -n +\$((start + $shown + 1)) /var/log/voiceover-update.log 2>/dev/null | head -n 60 |
  awk '{ if (length(\$0) > 360) print substr(\$0, 1, 180) \" [...] \" substr(\$0, length(\$0) - 169); else print }'" capture) ||
      die "Couldn't read the install log (see above)."
    state=$(sed -n 's/^STATE //p' <<<"$out" | head -n 1)
    result=$(sed -n 's/^RESULT //p' <<<"$out" | head -n 1)
    lines=$(tail -n +3 <<<"$out")
    count=0
    if [[ -n "$lines" ]]; then
      mapfile -t new_lines <<<"$lines"
      printf '    %s\n' "${new_lines[@]}"
      count=${#new_lines[@]}
      shown=$((shown + count))
    fi
    if [[ "$state" != active && "$state" != activating ]]; then
      ((count == 60)) && continue # finished, but there are more lines to show
      break
    fi
    ((count == 60)) || sleep 15
  done
  [[ -n "$result" ]] || die "The install stopped without finishing (the instance may have been stopped).
       Log on the instance: /var/log/voiceover-update.log. Run ./scripts/deploy.sh again."
  [[ "${result##* }" == 0 ]]
}

app_healthy() {
  run_remote "$1" 30 "curl -fsS --max-time 5 http://127.0.0.1:7860/api/health" quiet >/dev/null 2>&1
}
