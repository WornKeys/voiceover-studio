#!/usr/bin/env bash
# Store, list or delete a secret in SSM Parameter Store: put|delete <name>, or list.
# shellcheck source=scripts/lib/host.sh
source "$(dirname "$0")/lib/host.sh"
run_in_toolbox secret.sh "$@"
