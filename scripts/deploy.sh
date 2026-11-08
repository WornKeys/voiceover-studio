#!/usr/bin/env bash
# Create or update everything: infrastructure, then the app. Safe to re-run. Options: --help
# shellcheck source=scripts/lib/host.sh
source "$(dirname "$0")/lib/host.sh"
run_in_toolbox deploy.sh "$@"
