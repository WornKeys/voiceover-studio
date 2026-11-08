#!/usr/bin/env bash
# Remove everything this project created in AWS and verify it. Options: --help
# shellcheck source=scripts/lib/host.sh
source "$(dirname "$0")/lib/host.sh"
run_in_toolbox destroy.sh "$@"

case " $* " in
  *" --purge-local "*)
    images=$(docker images -q voiceover-toolbox)
    if [ -n "$images" ]; then
      echo "$images" | xargs docker rmi -f >/dev/null
      echo "Removed the toolbox image."
    fi
    ;;
esac
