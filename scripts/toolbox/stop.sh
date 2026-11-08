#!/usr/bin/env bash
# Stop the instance. Everything is kept (disk, models, bucket); only the disk is charged (~$8/month for 100 GB).
# To remove everything instead: ./scripts/destroy.sh
# shellcheck source=scripts/toolbox/lib.sh
source scripts/toolbox/lib.sh
load_env

id=$(instance_id)
state=$(instance_state "$id")
if [[ "$state" == stopped ]]; then
  say "Already stopped."
  exit 0
fi
say "Stopping the instance"
aws ec2 stop-instances --instance-ids "$id" >/dev/null
aws ec2 wait instance-stopped --instance-ids "$id"
say "Stopped. Start again with ./scripts/start.sh or ./scripts/connect.sh"
