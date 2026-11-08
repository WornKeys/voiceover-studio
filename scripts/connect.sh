#!/usr/bin/env bash
# Open the studio in your browser through a private SSM tunnel (starts the instance if it's stopped).
#   ./scripts/connect.sh [local-port]    (default 7860)
# shellcheck source=scripts/lib/host.sh
source "$(dirname "$0")/lib/host.sh"
port=${1:-7860}
TOOLBOX_DOCKER_ARGS=(-p "127.0.0.1:$port:7860" -e "VS_LOCAL_PORT=$port")
run_in_toolbox connect.sh
