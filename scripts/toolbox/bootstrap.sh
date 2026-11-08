#!/usr/bin/env bash
# One-time account setup, run with an ADMIN profile (not the deploy role):
#   ./scripts/bootstrap.sh --profile <admin-profile> [--yes]
#   ./scripts/bootstrap.sh --profile <admin-profile> --remove     (after ./scripts/destroy.sh)
#
# Sets up everything the deploy scripts rely on (infra/bootstrap/README.md explains each piece):
#   S3 Block Public Access for the account, an account budget, cost anomaly alerts, the GPU quota request,
#   the four IAM policies, the operator user and the deploy role.
# It checks what already exists, lists what it would create or update, and asks first. Safe to re-run.
# Stays manual (needs you or your phone): root MFA, IAM access to billing, the operator's console password and
# MFA device, and `aws login`. The script tells you which of these are still missing.
# shellcheck source=scripts/toolbox/lib.sh
source scripts/toolbox/lib.sh

POLICY_DIR=infra/bootstrap/policies
ROLE=VoiceoverStudioDeployer
OPERATOR=voiceover-operator
ACCOUNT_BUDGET="account-monthly"
MONITOR_NAME=voiceover-account-services
SUBSCRIPTION_NAME=voiceover-account-alerts
GPU_QUOTA=L-DB2E81BA # EC2 "Running On-Demand G and VT instances" (vCPUs)
# Not "voiceover-studio": destroy.sh proves the project is gone by finding nothing with that tag.
SETUP_TAG=("Key=project,Value=voiceover-studio-account")
declare -A POLICY_FILES=(
  [voiceover-studio-instance-boundary]=instance-boundary.json
  [voiceover-studio-deployer-compute]=deployer-compute-policy.json
  [voiceover-studio-deployer-services]=deployer-services-policy.json
  [voiceover-studio-guardrails]=guardrails-policy.json
)
POLICY_ORDER=(voiceover-studio-instance-boundary voiceover-studio-deployer-compute voiceover-studio-deployer-services
  voiceover-studio-guardrails)
ROLE_POLICIES=(voiceover-studio-deployer-compute voiceover-studio-deployer-services voiceover-studio-guardrails)

yes=false remove=false
for arg in "$@"; do
  case "$arg" in
    --yes | -y) yes=true ;;
    --remove) remove=true ;;
    -h | --help)
      echo "Usage: ./scripts/bootstrap.sh --profile <admin-profile> [--yes] [--remove]"
      exit 0
      ;;
    *) die "Unknown option: $arg" ;;
  esac
done

load_env
arn=$(aws sts get-caller-identity --query Arn --output text)
account=$(aws sts get-caller-identity --query Account --output text)
partition=$(cut -d: -f2 <<<"$arn")
case "$arn" in
  *":assumed-role/$ROLE/"* | *":user/$OPERATOR") die "Run this with an admin profile, not the deploy role or the operator ($arn)." ;;
  *":root") warn "You're using the root user. An IAM admin user is better (root should only do what only root can)." ;;
esac
say "Account $account, region $AWS_REGION, as $arn"
[[ "$AWS_REGION" == us-east-1 ]] ||
  warn "The guardrails deny every region except $AWS_REGION, including IAM's own (us-east-1): deploys from another
       region need a NotAction exception for global services in guardrails-policy.json."

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# A policy file with this account's ID and region filled in.
render() {
  sed -e "s/ACCOUNT_ID/$account/g" -e "s/REGION/$AWS_REGION/g" "$POLICY_DIR/$1" >"$WORK/$1"
  echo "$WORK/$1"
}
same_json() { diff -q <(jq -S . "$1") <(jq -S . <<<"$2") >/dev/null; }
policy_arn() { echo "arn:$partition:iam::$account:policy/$1"; }
exists() { "$@" >/dev/null 2>&1; }
ce() { aws ce --region us-east-1 "$@"; } # Cost Explorer only answers in us-east-1

ok() { printf '    \033[32m✓\033[0m %s\n' "$*"; }
todo() { printf '    \033[33m%s\033[0m %s\n' "$1" "$2"; }

# ==========================================================================================================
# Remove
# ==========================================================================================================
if $remove; then
  say "Checking that the project itself is gone"
  left=$(aws resourcegroupstaggingapi get-resources --tag-filters Key=project,Values=voiceover-studio \
    --query 'ResourceTagMappingList[].ResourceARN' --output text)
  for item in $left; do
    # The tagging index lags behind deletions: confirm with the resource's own service (lib.sh).
    still_exists "$item" || continue
    die "Project resources still exist ($item). Run ./scripts/destroy.sh first."
  done
  ok "Nothing tagged project=voiceover-studio is left"

  say "This removes the account setup:"
  note "the deploy role $ROLE, the user $OPERATOR (with its password and MFA device), the four"
  note "voiceover-studio-* policies, the budget $ACCOUNT_BUDGET and the anomaly alerts $SUBSCRIPTION_NAME."
  note "Kept: S3 Block Public Access (a good default), the GPU quota and Cost Explorer (both free)."
  if ! $yes; then
    [[ -t 0 ]] || die "Run this in a terminal, or add --yes."
    read -r -p 'Type "remove" to continue: ' answer
    [[ "$answer" == remove ]] || die "Cancelled. Nothing was removed."
  fi

  if exists aws iam get-role --role-name "$ROLE"; then
    for name in $(aws iam list-attached-role-policies --role-name "$ROLE" \
      --query 'AttachedPolicies[].PolicyArn' --output text); do
      aws iam detach-role-policy --role-name "$ROLE" --policy-arn "$name"
    done
    aws iam delete-role --role-name "$ROLE" && ok "Deleted the role $ROLE"
  fi

  if exists aws iam get-user --user-name "$OPERATOR"; then
    aws iam delete-login-profile --user-name "$OPERATOR" 2>/dev/null || true
    for serial in $(aws iam list-mfa-devices --user-name "$OPERATOR" --query 'MFADevices[].SerialNumber' --output text); do
      aws iam deactivate-mfa-device --user-name "$OPERATOR" --serial-number "$serial"
      aws iam delete-virtual-mfa-device --serial-number "$serial" 2>/dev/null || true
    done
    for key in $(aws iam list-access-keys --user-name "$OPERATOR" --query 'AccessKeyMetadata[].AccessKeyId' --output text); do
      aws iam delete-access-key --user-name "$OPERATOR" --access-key-id "$key"
    done
    for name in $(aws iam list-user-policies --user-name "$OPERATOR" --query 'PolicyNames[]' --output text); do
      aws iam delete-user-policy --user-name "$OPERATOR" --policy-name "$name"
    done
    for name in $(aws iam list-attached-user-policies --user-name "$OPERATOR" \
      --query 'AttachedPolicies[].PolicyArn' --output text); do
      aws iam detach-user-policy --user-name "$OPERATOR" --policy-arn "$name"
    done
    aws iam delete-user --user-name "$OPERATOR" && ok "Deleted the user $OPERATOR"
  fi

  for name in "${POLICY_ORDER[@]}"; do
    exists aws iam get-policy --policy-arn "$(policy_arn "$name")" || continue
    for version in $(aws iam list-policy-versions --policy-arn "$(policy_arn "$name")" \
      --query 'Versions[?!IsDefaultVersion].VersionId' --output text); do
      aws iam delete-policy-version --policy-arn "$(policy_arn "$name")" --version-id "$version"
    done
    aws iam delete-policy --policy-arn "$(policy_arn "$name")" && ok "Deleted the policy $name"
  done

  if exists aws budgets describe-budget --account-id "$account" --budget-name "$ACCOUNT_BUDGET"; then
    aws budgets delete-budget --account-id "$account" --budget-name "$ACCOUNT_BUDGET" && ok "Deleted the budget"
  fi
  for sub in $(ce get-anomaly-subscriptions \
    --query "AnomalySubscriptions[?SubscriptionName=='$SUBSCRIPTION_NAME'].SubscriptionArn" --output text); do
    ce delete-anomaly-subscription --subscription-arn "$sub" >/dev/null && ok "Deleted the anomaly alerts"
  done
  for monitor in $(ce get-anomaly-monitors \
    --query "AnomalyMonitors[?MonitorName=='$MONITOR_NAME'].MonitorArn" --output text); do
    ce delete-anomaly-monitor --monitor-arn "$monitor" >/dev/null && ok "Deleted the anomaly monitor"
  done
  say "Account setup removed. Remove the voiceover profiles from ~/.aws/config yourself."
  exit 0
fi

# ==========================================================================================================
# Set up: check everything first, then ask, then apply
# ==========================================================================================================
[[ -n "${BUDGET_EMAIL:-}" && "$BUDGET_EMAIL" != you@example.com ]] ||
  die "Set BUDGET_EMAIL in .env first: budget and anomaly alerts go there."
STEPS=()
plan() { # plan <symbol> <description> <step...>
  todo "$1" "$2"
  shift 2
  STEPS+=("$*")
}

say "Checking the account"

bpa=$(aws s3control get-public-access-block --account-id "$account" --output text \
  --query 'PublicAccessBlockConfiguration.[BlockPublicAcls,IgnorePublicAcls,BlockPublicPolicy,RestrictPublicBuckets]' \
  2>/dev/null || echo none)
if [[ "$bpa" != none && "$bpa" != *False* ]]; then
  ok "S3 Block Public Access is on for the account"
else
  plan + "Turn on S3 Block Public Access for the account" bpa
fi

if exists aws budgets describe-budget --account-id "$account" --budget-name "$ACCOUNT_BUDGET"; then
  ok "Account budget $ACCOUNT_BUDGET exists"
else
  plan + "Create the account budget $ACCOUNT_BUDGET (\$${ACCOUNT_BUDGET_USD:-30}/month, emails to $BUDGET_EMAIL)" budget
fi

monitors=$(ce get-anomaly-monitors --query "AnomalyMonitors[?MonitorType=='DIMENSIONAL'].MonitorArn" --output text)
if [[ -z "$monitors" ]]; then
  plan + "Create cost anomaly alerts (AWS services monitor, daily email to $BUDGET_EMAIL)" anomaly
elif ce get-anomaly-subscriptions --query 'AnomalySubscriptions[].MonitorArnList[]' --output text |
  grep -qF "${monitors%%[[:space:]]*}"; then # alerts on the (first) AWS services monitor
  ok "Cost anomaly alerts exist"
else
  plan + "Add daily email alerts to the existing cost anomaly monitor" anomaly
fi

quota=$(aws service-quotas get-service-quota --service-code ec2 --quota-code "$GPU_QUOTA" \
  --query Quota.Value --output text 2>/dev/null || echo 0)
if ((${quota%.*} >= 4)); then
  ok "GPU quota: ${quota%.*} vCPUs"
elif [[ -n $(aws service-quotas list-requested-service-quota-change-history-by-quota --service-code ec2 \
  --quota-code "$GPU_QUOTA" --query "RequestedQuotas[?Status=='PENDING' || Status=='CASE_OPENED'].Id" \
  --output text 2>/dev/null) ]]; then
  ok "GPU quota increase to 4 vCPUs requested, waiting for AWS (hours to days)"
else
  plan + "Request a GPU quota of 4 vCPUs (one instance); AWS approves it, in hours to days" quota
fi

for name in "${POLICY_ORDER[@]}"; do
  file=$(render "${POLICY_FILES[$name]}")
  if ! exists aws iam get-policy --policy-arn "$(policy_arn "$name")"; then
    plan + "Create the IAM policy $name" policy "$name"
    continue
  fi
  version=$(aws iam get-policy --policy-arn "$(policy_arn "$name")" --query Policy.DefaultVersionId --output text)
  current=$(aws iam get-policy-version --policy-arn "$(policy_arn "$name")" --version-id "$version" \
    --query PolicyVersion.Document --output json)
  if same_json "$file" "$current"; then
    ok "IAM policy $name is up to date"
  else
    plan "~" "Update the IAM policy $name to the repo's version (diff below)" policy "$name"
    diff <(jq -S . <<<"$current") <(jq -S . "$file") | sed 's/^/        /' || true
  fi
done

operator_policy=$(render operator-user-policy.json)
if ! exists aws iam get-user --user-name "$OPERATOR"; then
  plan + "Create the user $OPERATOR (no access keys; you add its password and MFA)" user
else
  ok "User $OPERATOR exists"
  # Set up by hand, the inline policy may have any name: accept a matching one whatever it's called.
  matching=""
  for name in $(aws iam list-user-policies --user-name "$OPERATOR" --query 'PolicyNames[]' --output text); do
    current=$(aws iam get-user-policy --user-name "$OPERATOR" --policy-name "$name" \
      --query PolicyDocument --output json)
    if same_json "$operator_policy" "$current"; then
      matching=$name
      break
    fi
  done
  if [[ -n "$matching" ]]; then
    ok "Its inline policy ($matching: assume the deploy role only) is up to date"
  else
    plan "~" "Set its inline policy: it may only assume $ROLE" user_policy
  fi
  if aws iam list-attached-user-policies --user-name "$OPERATOR" --query 'AttachedPolicies[].PolicyName' \
    --output text | grep -qw SignInLocalDevelopmentAccess; then
    ok "It may use aws login (SignInLocalDevelopmentAccess)"
  else
    plan + "Let it use aws login (attach SignInLocalDevelopmentAccess)" user_signin
  fi
fi

trust=$(render trust-policy.json)
if ! exists aws iam get-role --role-name "$ROLE"; then
  plan + "Create the deploy role $ROLE (MFA required, 1-hour sessions) with its three policies" role
else
  ok "Role $ROLE exists"
  current=$(aws iam get-role --role-name "$ROLE" --query Role.AssumeRolePolicyDocument --output json)
  if same_json "$trust" "$current"; then
    ok "Its trust policy (only $OPERATOR, with MFA) is up to date"
  else
    plan "~" "Set its trust policy: only $OPERATOR, with MFA" role_trust
  fi
  [[ $(aws iam get-role --role-name "$ROLE" --query Role.MaxSessionDuration --output text) == 3600 ]] ||
    plan "~" "Set its maximum session to 1 hour" role_session
  attached=$(aws iam list-attached-role-policies --role-name "$ROLE" --query 'AttachedPolicies[].PolicyName' --output text)
  for name in "${ROLE_POLICIES[@]}"; do
    grep -qw "$name" <<<"$attached" || plan + "Attach $name to the role" role_attach "$name"
  done
fi

# --- apply ------------------------------------------------------------------------------------------------
apply_bpa() {
  aws s3control put-public-access-block --account-id "$account" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
}
apply_budget() {
  local budget notifications
  budget=$(jq -n --arg name "$ACCOUNT_BUDGET" --arg amount "${ACCOUNT_BUDGET_USD:-30}" \
    '{BudgetName: $name, BudgetLimit: {Amount: $amount, Unit: "USD"}, TimeUnit: "MONTHLY", BudgetType: "COST"}')
  notifications=$(jq -n --arg email "$BUDGET_EMAIL" '[
    (50, 80, 100 | {Notification: {NotificationType: "ACTUAL", ComparisonOperator: "GREATER_THAN", Threshold: .,
      ThresholdType: "PERCENTAGE"}, Subscribers: [{SubscriptionType: "EMAIL", Address: $email}]}),
    {Notification: {NotificationType: "FORECASTED", ComparisonOperator: "GREATER_THAN", Threshold: 100,
      ThresholdType: "PERCENTAGE"}, Subscribers: [{SubscriptionType: "EMAIL", Address: $email}]}]')
  aws budgets create-budget --account-id "$account" --budget "$budget" --notifications-with-subscribers "$notifications"
}
apply_anomaly() {
  local monitor
  monitor=$(ce get-anomaly-monitors --query "AnomalyMonitors[?MonitorType=='DIMENSIONAL'].MonitorArn | [0]" \
    --output text)
  if [[ -z "$monitor" || "$monitor" == None ]]; then
    monitor=$(ce create-anomaly-monitor --query MonitorArn --output text --anomaly-monitor \
      "{\"MonitorName\": \"$MONITOR_NAME\", \"MonitorType\": \"DIMENSIONAL\", \"MonitorDimension\": \"SERVICE\"}")
  fi
  [[ "$monitor" == arn:* ]] || die "Couldn't create or find the cost anomaly monitor (got '$monitor')."
  ce create-anomaly-subscription --anomaly-subscription "$(jq -n --arg m "$monitor" --arg e "$BUDGET_EMAIL" \
    --arg n "$SUBSCRIPTION_NAME" '{SubscriptionName: $n, MonitorArnList: [$m], Frequency: "DAILY",
      Subscribers: [{Type: "EMAIL", Address: $e}],
      ThresholdExpression: {Dimensions: {Key: "ANOMALY_TOTAL_IMPACT_ABSOLUTE", Values: ["10"],
        MatchOptions: ["GREATER_THAN_OR_EQUAL"]}}}')" >/dev/null
}
apply_quota() {
  aws service-quotas request-service-quota-increase --service-code ec2 --quota-code "$GPU_QUOTA" \
    --desired-value 4 >/dev/null
}
apply_policy() {
  local name=$1 file target oldest
  file=$(render "${POLICY_FILES[$name]}")
  target=$(policy_arn "$name")
  if exists aws iam get-policy --policy-arn "$target"; then
    # A managed policy keeps at most five versions: drop the oldest non-default one first.
    if (($(aws iam list-policy-versions --policy-arn "$target" --query 'length(Versions)' --output text) >= 5)); then
      oldest=$(aws iam list-policy-versions --policy-arn "$target" \
        --query 'Versions[?!IsDefaultVersion] | sort_by(@, &CreateDate)[0].VersionId' --output text)
      aws iam delete-policy-version --policy-arn "$target" --version-id "$oldest"
    fi
    aws iam create-policy-version --policy-arn "$target" --policy-document "file://$file" --set-as-default >/dev/null
  else
    aws iam create-policy --policy-name "$name" --policy-document "file://$file" --tags "${SETUP_TAG[@]}" \
      --description "voiceover-studio account setup (infra/bootstrap)" >/dev/null
  fi
}
apply_user() {
  aws iam create-user --user-name "$OPERATOR" --tags "${SETUP_TAG[@]}" >/dev/null
  apply_user_policy
  apply_user_signin
}
apply_user_policy() {
  aws iam put-user-policy --user-name "$OPERATOR" --policy-name "$OPERATOR" --policy-document "file://$operator_policy"
}
apply_user_signin() {
  aws iam attach-user-policy --user-name "$OPERATOR" \
    --policy-arn "arn:$partition:iam::aws:policy/SignInLocalDevelopmentAccess"
}
apply_role() {
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document "file://$trust" --max-session-duration 3600 \
    --description "voiceover-studio deploys: assumed by $OPERATOR with MFA" --tags "${SETUP_TAG[@]}" >/dev/null
  local name
  for name in "${ROLE_POLICIES[@]}"; do apply_role_attach "$name"; done
}
apply_role_trust() { aws iam update-assume-role-policy --role-name "$ROLE" --policy-document "file://$trust"; }
apply_role_session() { aws iam update-role --role-name "$ROLE" --max-session-duration 3600; }
apply_role_attach() { aws iam attach-role-policy --role-name "$ROLE" --policy-arn "$(policy_arn "$1")"; }

if ((${#STEPS[@]} == 0)); then
  say "Nothing to change: the account setup is complete."
else
  if ! $yes; then confirm "Make these ${#STEPS[@]} change(s)?" || die "Cancelled. Nothing was changed."; fi
  for step in "${STEPS[@]}"; do
    read -r -a parts <<<"$step"
    "apply_${parts[0]}" "${parts[@]:1}"
  done
  say "Done: ${#STEPS[@]} change(s) made."
fi

# --- what's left for you ----------------------------------------------------------------------------------
say "Your part (needs you, or your phone)"
note "Root user: MFA on, no access keys; Account > 'IAM user and role access to Billing information' > Activate."
if exists aws iam get-login-profile --user-name "$OPERATOR"; then
  ok "$OPERATOR has a console password"
else
  todo "!" "Give $OPERATOR a console password: IAM > Users > $OPERATOR > Security credentials > Enable console access"
fi
mfa=$(aws iam list-mfa-devices --user-name "$OPERATOR" --query 'MFADevices[0].SerialNumber' --output text 2>/dev/null || true)
if [[ -n "$mfa" && "$mfa" != None ]]; then
  ok "$OPERATOR has an MFA device"
else
  todo "!" "Add an MFA device for $OPERATOR (same page: Assign MFA device), then run this again for the config"
  mfa="<the MFA device ARN>"
fi
say "AWS CLI profiles (~/.aws/config). 'aws login --profile $OPERATOR' writes the first one:"
cat <<EOF
    [profile $OPERATOR]
    login_session = arn:$partition:iam::$account:user/$OPERATOR
    region = $AWS_REGION

    [profile voiceover]
    role_arn = arn:$partition:iam::$account:role/$ROLE
    source_profile = $OPERATOR
    mfa_serial = $mfa
    region = $AWS_REGION
    duration_seconds = 3600
EOF
note "Then: aws login --profile $OPERATOR, set AWS_PROFILE=voiceover in .env, and ./scripts/deploy.sh"
