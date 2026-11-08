#!/usr/bin/env bash
# Show the instance state, app health, GPU memory and the last deploy log lines.
# shellcheck source=scripts/lib/host.sh
source "$(dirname "$0")/lib/host.sh"
run_in_toolbox status.sh "$@"
