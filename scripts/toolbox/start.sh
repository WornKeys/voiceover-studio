#!/usr/bin/env bash
# Start a stopped instance and wait until the app answers (models load from disk: a few minutes).
# shellcheck source=scripts/toolbox/lib.sh
source scripts/toolbox/lib.sh
load_env

id=$(instance_id)
ensure_running "$id"
wait_ssm "$id"
say "Waiting for the app"
for _ in $(seq 1 40); do
  if app_healthy "$id"; then
    say "Running. Open it with: ./scripts/connect.sh"
    exit 0
  fi
  sleep 15
done
die "The app didn't answer within 10 minutes. See ./scripts/status.sh"
