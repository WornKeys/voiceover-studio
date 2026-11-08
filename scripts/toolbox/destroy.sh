#!/usr/bin/env bash
# Remove everything this project created in AWS, then prove it. Written for "try it, then clean up".
#   1. offer to download your voices and outputs   2. terraform destroy (instance, disk, bucket, logs, alarm,
#   budget, role)   3. remove what Terraform doesn't own (secrets in SSM, snapshots, images)
#   4. verify nothing tagged project=voiceover-studio is left (exits non-zero if something is)
# Kept on purpose: the AWS account, its IAM setup (deploy role, operator user) and the GPU quota (free).
# shellcheck source=scripts/toolbox/lib.sh
source scripts/toolbox/lib.sh

yes=false keep=true purge=false
for arg in "$@"; do
  case "$arg" in
    --yes | -y) yes=true ;;
    --no-keep-outputs) keep=false ;;
    --purge-local) purge=true ;;
    -h | --help)
      echo "Usage: ./scripts/destroy.sh [--yes] [--no-keep-outputs] [--purge-local]"
      exit 0
      ;;
    *) die "Unknown option: $arg" ;;
  esac
done

load_env
tf_init

if deployed; then
  bucket=$(tf_out bucket)
  say "This deletes the instance, its disk and models, the bucket ($bucket) with all voices and outputs,"
  note "the logs, the alarm, the budget and the instance role, plus every /voiceover-studio/ secret."
  if ! $yes; then
    [[ -t 0 ]] || die "Run this in a terminal, or add --yes."
    read -r -p 'Type "destroy" to continue: ' answer
    [[ "$answer" == destroy ]] || die "Cancelled. Nothing was deleted."
  fi

  if $keep; then
    dest="backups/$(date -u +%Y%m%d-%H%M%S)"
    say "Downloading voices and outputs to $dest"
    aws s3 sync "s3://$bucket/" "$dest/" --exclude 'deploy/*' --only-show-errors
    note "Done. It contains voice recordings: keep it private and delete it when you no longer need it."
  fi

  say "Destroying the infrastructure"
  tf destroy -input=false -auto-approve
else
  say "No local Terraform state: nothing to destroy with Terraform. Cleaning up and verifying anyway."
  $yes || confirm "Continue?" || die "Cancelled."
fi

say "Removing what Terraform doesn't own"
for name in $(aws ssm describe-parameters --parameter-filters Key=Name,Option=BeginsWith,Values=/voiceover-studio/ \
  --query 'Parameters[].Name' --output text); do
  aws ssm delete-parameter --name "$name" && note "secret $name"
done
for snap in $(aws ec2 describe-snapshots --owner-ids self --filters Name=tag:project,Values=voiceover-studio \
  --query 'Snapshots[].SnapshotId' --output text); do
  aws ec2 delete-snapshot --snapshot-id "$snap" && note "snapshot $snap"
done
for image in $(aws ec2 describe-images --owners self --filters Name=tag:project,Values=voiceover-studio \
  --query 'Images[].ImageId' --output text); do
  aws ec2 deregister-image --image-id "$image" && note "image $image"
done

say "Verifying that nothing is left"
leftovers=()
for attempt in 1 2 3; do # the tagging index can lag behind deletions by a minute or two
  leftovers=()
  for arn in $(aws resourcegroupstaggingapi get-resources --tag-filters Key=project,Values=voiceover-studio \
    --query 'ResourceTagMappingList[].ResourceARN' --output text); do
    if [[ "$arn" == *:instance/* ]]; then
      state=$(instance_state "${arn##*/}" 2>/dev/null || echo terminated)
      [[ "$state" == terminated || "$state" == shutting-down ]] && continue
    fi
    leftovers+=("$arn")
  done
  # IAM roles and budgets aren't in the tagging index: check them by name.
  if aws iam get-role --role-name voiceover-studio-instance >/dev/null 2>&1; then
    leftovers+=("IAM role voiceover-studio-instance")
  fi
  account=$(aws sts get-caller-identity --query Account --output text)
  if aws budgets describe-budget --account-id "$account" --budget-name voiceover-studio-monthly >/dev/null 2>&1; then
    leftovers+=("budget voiceover-studio-monthly")
  fi
  if ((${#leftovers[@]} == 0)); then break; fi
  if ((attempt < 3)); then sleep 30; fi
done

if ((${#leftovers[@]} > 0)); then
  warn "These still exist:"
  printf '    %s\n' "${leftovers[@]}"
  die "Not everything was removed. Delete these in the console (docs/deploy.md, 'Manual clean-up')."
fi

if $purge; then
  rm -rf "$TF_DIR/.terraform" "$TF_DIR"/terraform.tfstate* build/
  note "Removed the local Terraform state and build files."
fi
say "Everything is gone. Check Billing > Bills tomorrow: charges for the last hours can show up a day later."
