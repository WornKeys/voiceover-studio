#!/usr/bin/env bash
# Host side of every command (sourced by scripts/*.sh). It only needs Docker and the AWS CLI v2:
# it gets short-lived credentials for the deploy role, then runs the real script inside the toolbox container
# (Terraform, AWS CLI, Session Manager plugin). Works with macOS's bash 3.2, Linux and Git Bash on Windows.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TOOLBOX_DOCKER_ARGS=() # extra `docker run` options, e.g. a published port for connect.sh

die() {
  echo "Error: $*" >&2
  exit 1
}

# One value from .env (without running it as shell code).
env_value() {
  sed -n "s/^$1=//p" "$ROOT/.env" | tail -n 1 | tr -d '\r"'
}

# Git Bash on Windows rewrites arguments that look like Unix paths (/work -> C:/Program Files/Git/work) when it
# starts a Windows program such as docker.exe. So: Windows paths for the host side, conversion switched off, and
# no bare /path arguments in the docker command (the mount uses --mount, the working directory is the image's).
HOST_ROOT=$ROOT
case "${OSTYPE:-}" in
  msys* | cygwin*)
    HOST_ROOT=$(cd "$ROOT" && pwd -W)
    export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"
    ;;
esac

toolbox_image() {
  local tag
  tag="voiceover-toolbox:$(cksum <"$ROOT/toolbox/Dockerfile" | cut -d' ' -f1)"
  if ! docker image inspect "$tag" >/dev/null 2>&1; then
    echo "Building the toolbox image (first run only, about a minute)..." >&2
    docker build -t "$tag" "$HOST_ROOT/toolbox" >&2
  fi
  echo "$tag"
}

run_in_toolbox() {
  local script=$1
  shift
  [ -f "$ROOT/.env" ] || die "No .env file. Run: cp .env.example .env, then fill in your values."
  command -v docker >/dev/null || die "Docker isn't installed: https://docs.docker.com/get-docker/"
  docker info >/dev/null 2>&1 || die "Docker isn't running. Start Docker Desktop (or the Docker service) and try again."
  command -v aws >/dev/null ||
    die "The AWS CLI v2 isn't installed: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"

  local profile creds key value
  # The deploy role's profile from .env, unless a command needs another one (bootstrap.sh: an admin).
  profile=${TOOLBOX_PROFILE:-$(env_value AWS_PROFILE)}
  profile=${profile:-voiceover}
  # Short-lived credentials of that profile. The CLI asks for your MFA code when its cached session expired.
  if ! creds=$(aws configure export-credentials --profile "$profile" --format env-no-export); then
    if [ -n "${TOOLBOX_PROFILE:-}" ]; then
      die "No credentials for profile '$profile'. Sign in with it first (e.g. aws login --profile $profile)."
    fi
    die "No credentials for profile '$profile'. Sign in first: aws login --profile voiceover-operator"
  fi
  while IFS='=' read -r key value; do
    value=${value%$'\r'}
    case "$key" in
      AWS_ACCESS_KEY_ID | AWS_SECRET_ACCESS_KEY | AWS_SESSION_TOKEN | AWS_CREDENTIAL_EXPIRATION)
        export "$key=$value"
        ;;
    esac
  done <<EOF
$creds
EOF

  local image args prefix
  image=$(toolbox_image)
  prefix=()
  # The Git Bash window (mintty) isn't a Windows console, so docker.exe needs winpty for an interactive terminal.
  # Git Bash started from PowerShell or Windows Terminal runs in a real console and doesn't.
  if [ "${TERM_PROGRAM:-}" = mintty ] && [ -t 0 ] && command -v winpty >/dev/null; then prefix=(winpty); fi

  # Credentials are passed by name (-e VAR), so their values don't appear in the process list.
  # The image's working directory is /work, where the repo is mounted.
  args=(run --rm --init -i --mount "type=bind,source=$HOST_ROOT,target=/work"
    -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN -e AWS_CREDENTIAL_EXPIRATION)
  if [ -t 0 ] && [ -t 1 ]; then args+=(-t); fi
  if [ "$(uname -s)" = Linux ]; then args+=(--user "$(id -u):$(id -g)"); fi # files in the repo stay yours
  args+=(${TOOLBOX_DOCKER_ARGS[@]+"${TOOLBOX_DOCKER_ARGS[@]}"})

  ${prefix[@]+"${prefix[@]}"} docker "${args[@]}" "$image" bash "scripts/toolbox/$script" "$@"
}
