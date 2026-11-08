#!/usr/bin/env bash
# What's deployed and what it's doing.
# shellcheck source=scripts/toolbox/lib.sh
source scripts/toolbox/lib.sh
load_env

id=$(instance_id)
read -r state type zone launched < <(aws ec2 describe-instances --instance-ids "$id" \
  --query 'Reservations[0].Instances[0].[State.Name, InstanceType, Placement.AvailabilityZone, LaunchTime]' \
  --output text)
say "Instance $id: $state ($type, $zone, last started $launched)"
note "Bucket: $(tf_out bucket)   Logs: CloudWatch > Log groups > $(tf_out log_group)"
[[ "$state" == running ]] || exit 0

run_remote "$id" 60 "set +e
echo \"App health:   \$(curl -fsS --max-time 5 http://127.0.0.1:7860/api/health || echo 'not answering')\"
echo \"Activity:     \$(curl -fsS --max-time 5 http://127.0.0.1:7860/api/activity || echo '-')\"
echo \"Idle stop:    after \$(cat /opt/voiceover/idle-minutes 2>/dev/null || echo '?') idle minutes\"
echo \"Install:      \$(systemctl is-active voiceover-update 2>/dev/null) (last result: \$(cat /opt/voiceover/update-result 2>/dev/null || echo none); release exit code)\"
command -v nvidia-smi >/dev/null && echo \"GPU memory:   \$(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader)\"
docker ps --format '{{.Names}}: {{.Status}}' 2>/dev/null
echo 'Last deploy log lines:'
tail -n 5 /var/log/voiceover-update.log 2>/dev/null" || true
