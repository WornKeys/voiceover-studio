#!/usr/bin/env bash
# Start update.sh in the background, as a transient systemd service (voiceover-update), and return at once.
# A first install takes about 25 minutes, sometimes close to an hour: too long to hold one SSM command open, and it
# could outlive the deploy role's 1-hour session. scripts/deploy.sh follows /var/log/voiceover-update.log with short SSM commands instead and
# reads the outcome from /opt/voiceover/update-result. Run by deploy.sh through SSM (as root):
#   start-update.sh <bucket> <release>
set -euo pipefail

BUCKET=$1
RELEASE=$2
ROOT=/opt/voiceover
LOG=/var/log/voiceover-update.log

if systemctl is-active --quiet voiceover-update || pgrep -f "infra/instance/update.sh" >/dev/null; then
  echo "An install is already running on the instance." >&2
  exit 3
fi

touch "$LOG"
wc -l <"$LOG" >"$ROOT/update-log-start" # deploy.sh shows the log from this line on
rm -f "$ROOT/update-result"
systemctl reset-failed voiceover-update 2>/dev/null || true

# Services start with an almost empty environment: give update.sh what a root shell would have.
systemd-run --unit=voiceover-update --collect --quiet \
  --setenv=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin \
  --setenv=HOME=/root \
  --setenv=AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:?}" \
  /bin/bash "$ROOT/releases/$RELEASE/infra/instance/update.sh" "$BUCKET" "$RELEASE"
echo "Install started ($RELEASE)."
