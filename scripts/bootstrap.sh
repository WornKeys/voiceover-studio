#!/usr/bin/env bash
# One-time AWS account setup (guardrails, deploy role, operator user, budget, alerts, GPU quota request).
# Runs with an ADMIN profile, not the deploy role. Shows the changes and asks first; safe to re-run.
#   ./scripts/bootstrap.sh --profile <admin-profile> [--yes]
#   ./scripts/bootstrap.sh --profile <admin-profile> --remove      (after ./scripts/destroy.sh)
# What each piece is for: infra/bootstrap/README.md
# shellcheck source=scripts/lib/host.sh
source "$(dirname "$0")/lib/host.sh"

args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --profile)
      [ $# -ge 2 ] || die "--profile needs a profile name"
      TOOLBOX_PROFILE=$2
      shift 2
      ;;
    --profile=*)
      TOOLBOX_PROFILE=${1#--profile=}
      shift
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done
[ -n "${TOOLBOX_PROFILE:-}" ] ||
  die "Name your admin profile: ./scripts/bootstrap.sh --profile <admin-profile> (not the deploy role's profile)"
export TOOLBOX_PROFILE
run_in_toolbox bootstrap.sh ${args[@]+"${args[@]}"}
