#!/usr/bin/env bash
# Stop the instance. Everything is kept; only the disk is charged while stopped.
# shellcheck source=scripts/lib/host.sh
source "$(dirname "$0")/lib/host.sh"
run_in_toolbox stop.sh "$@"
