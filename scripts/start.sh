#!/usr/bin/env bash
# Start the stopped instance and wait for the app.
# shellcheck source=scripts/lib/host.sh
source "$(dirname "$0")/lib/host.sh"
run_in_toolbox start.sh "$@"
