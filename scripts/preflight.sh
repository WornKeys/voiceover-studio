#!/usr/bin/env bash
# Check your setup (credentials, quota, settings) without changing anything. deploy.sh runs it too.
# shellcheck source=scripts/lib/host.sh
source "$(dirname "$0")/lib/host.sh"
run_in_toolbox preflight.sh "$@"
