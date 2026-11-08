#!/usr/bin/env bash
# Checks before deploying, with plain-language fixes. Run by deploy.sh; also on its own: ./scripts/preflight.sh
# shellcheck source=scripts/toolbox/lib.sh
source scripts/toolbox/lib.sh
load_env

say "Preflight checks"
problems=0
fail() {
  printf '    \033[31m✗\033[0m %s\n' "$*"
  problems=$((problems + 1))
}
ok() { printf '    \033[32m✓\033[0m %s\n' "$*"; }

# Who am I? The deploy role, not an admin or root.
if ! arn=$(aws sts get-caller-identity --query Arn --output text 2>&1); then
  die "AWS rejected the credentials: $arn"
fi
case "$arn" in
  *:assumed-role/VoiceoverStudioDeployer/*) ok "Signed in as the deploy role" ;;
  *:root) fail "You're using the root user. Use the deploy role (profile 'voiceover'), see docs/deploy.md." ;;
  *) warn "Signed in as $arn, not the VoiceoverStudioDeployer role: the account guardrails don't apply." ;;
esac

if [[ "$AWS_REGION" == us-east-1 ]]; then
  ok "Region $AWS_REGION"
else
  warn "Region $AWS_REGION: the deploy role's policies are written for us-east-1 (see docs/deploy.md)."
fi

if [[ -z "${BUDGET_EMAIL:-}" || "$BUDGET_EMAIL" == you@example.com ]]; then
  fail "Set BUDGET_EMAIL in .env (budget alerts go there)."
else
  ok "Budget alerts to $BUDGET_EMAIL (\$${BUDGET_MONTHLY_USD:-30}/month)"
fi

case "$COMPUTE_PROFILE:$INSTANCE_TYPE" in
  gpu:g6.xlarge | gpu:g5.xlarge) ok "Instance $INSTANCE_TYPE (GPU, 24 GB)" ;;
  gpu:g4dn.xlarge) warn "g4dn.xlarge (T4, 16 GB) is too small for both local models and has no bfloat16 support. Use g6.xlarge or g5.xlarge." ;;
  cpu:t3.medium) ok "Instance t3.medium (every model is hosted)" ;;
  *) fail "INSTANCE_TYPE=$INSTANCE_TYPE doesn't fit COMPUTE_PROFILE=$COMPUTE_PROFILE." ;;
esac

# GPU quota: "Running On-Demand G and VT instances" counts vCPUs; one *.xlarge needs 4.
if [[ "$COMPUTE_PROFILE" == gpu ]]; then
  if quota=$(aws service-quotas get-service-quota --service-code ec2 --quota-code L-DB2E81BA \
    --query Quota.Value --output text 2>/dev/null); then
    if ((${quota%.*} >= 4)); then
      ok "GPU quota: ${quota%.*} vCPUs"
    else
      fail "GPU quota is ${quota%.*} vCPUs; one instance needs 4. Request an increase (Service Quotas > EC2 >
      'Running On-Demand G and VT instances'). Approval can take hours to days."
    fi
  else
    warn "Couldn't read the GPU quota; continuing."
  fi
fi

if [[ $(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'length(Vpcs)' --output text) == 1 ]]; then
  ok "Default VPC exists"
else
  fail "No default VPC in $AWS_REGION. Create one: VPC console > Actions > Create default VPC."
fi

# Secrets are referenced by SSM parameter name; the instance can only read /voiceover-studio/*.
for key in HF_TOKEN_PARAM TTS_API_KEY_PARAM LLM_API_KEY_PARAM; do
  name=${!key:-}
  [[ -z "$name" ]] && continue
  if [[ "$name" != /voiceover-studio/* ]]; then
    fail "$key must start with /voiceover-studio/ (the instance can't read other parameters)."
  elif aws ssm get-parameter --name "$name" --query Parameter.Name --output text >/dev/null 2>&1; then
    ok "$key: $name exists"
  else
    fail "$key: parameter $name doesn't exist. Create it: ./scripts/secret.sh put $name"
  fi
done

if [[ "$LLM_BASE_URL" == *bedrock* ]]; then
  warn "Amazon Bedrock needs extra IAM permissions that the deploy role and instance boundary don't have yet."
fi

if ((problems > 0)); then
  die "$problems problem(s) to fix before deploying."
fi
