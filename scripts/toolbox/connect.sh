#!/usr/bin/env bash
# Open a private tunnel to the studio (SSM Session Manager port forwarding): no open ports, no public URL.
# The browser sees http://localhost:<port>, a secure context, so microphone recording works.
# shellcheck source=scripts/toolbox/lib.sh
source scripts/toolbox/lib.sh
load_env

id=$(instance_id)
ensure_running "$id"
wait_ssm "$id"

say "Checking the app"
for i in $(seq 1 30); do
  app_healthy "$id" && break
  ((i == 1)) && note "Not answering yet (it takes a few minutes after a start). Waiting up to 10 minutes..."
  sleep 15
done
app_healthy "$id" || warn "The app still isn't answering. Opening the tunnel anyway; see ./scripts/status.sh"

# The Session Manager plugin listens on the container's loopback; socat makes it reachable through the
# port Docker publishes on your machine (127.0.0.1 only).
socat TCP-LISTEN:7860,fork,reuseaddr TCP:127.0.0.1:17860 &

say "Open http://localhost:${VS_LOCAL_PORT:-7860} in your browser. Press Ctrl+C here to close the tunnel."
note "Closing the tunnel doesn't stop the instance: it stops after ${IDLE_STOP_MINUTES:-30} idle minutes, or run ./scripts/stop.sh"
aws ssm start-session --target "$id" --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["7860"],"localPortNumber":["17860"]}'
