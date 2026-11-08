#!/usr/bin/env bash
# Stop this instance when nobody has used the app for IDLE_STOP_MINUTES. Runs every 5 minutes
# (voiceover-idle.timer). The instance shuts down with "stop" behaviour: the disk and data stay.
#
# Activity = opening the UI or pressing a button in it (see ActivityTracker in voiceover_studio/api.py).
# A render in progress always counts as activity.
# Working in a shell on the instance? Pause it: sudo touch /run/voiceover/keep-awake (honoured for 8 hours,
# cleared on reboot). A CloudWatch alarm (low CPU for 60 minutes) is the backstop if this script fails.
set -uo pipefail

limit=$(cat /opt/voiceover/idle-minutes 2>/dev/null || echo 30)
[[ "$limit" =~ ^[0-9]+$ ]] || limit=30
((limit > 0)) || exit 0 # 0 turns the idle stop off (the CloudWatch alarm still applies)

# Recent flags only, so a crashed deploy or a forgotten keep-awake can't keep the GPU running for ever.
[[ -n $(find /run/voiceover/updating -mmin -180 2>/dev/null) ]] && exit 0
[[ -n $(find /run/voiceover/keep-awake -mmin -480 2>/dev/null) ]] && exit 0

uptime_minutes=$(($(cut -d. -f1 /proc/uptime) / 60))
((uptime_minutes < limit)) && exit 0 # give a fresh start time to be used

if body=$(curl -fsS --max-time 5 http://127.0.0.1:7860/api/activity); then
  read -r busy idle_seconds < <(python3 -c 'import json, sys
d = json.load(sys.stdin)
print(int(bool(d["busy"])), int(d["idle_seconds"]))' <<<"$body")
  ((busy)) && exit 0
  idle_minutes=$((idle_seconds / 60))
else
  idle_minutes=$uptime_minutes # the app isn't running: nothing to use, count from boot
fi

if ((idle_minutes >= limit)); then
  logger -t voiceover-idle "No activity for ${idle_minutes} minutes (limit ${limit}): stopping the instance."
  systemctl poweroff
fi
