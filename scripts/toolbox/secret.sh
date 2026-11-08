#!/usr/bin/env bash
# Store a secret (e.g. a Hugging Face token or a hosted provider's API key) in SSM Parameter Store as an
# encrypted SecureString. .env then holds only the parameter's NAME.
#   ./scripts/secret.sh put /voiceover-studio/hf-token     (asks for the value; nothing is echoed)
#   ./scripts/secret.sh list
#   ./scripts/secret.sh delete /voiceover-studio/hf-token
# shellcheck source=scripts/toolbox/lib.sh
source scripts/toolbox/lib.sh
load_env

action=${1:-}
name=${2:-}
check_name() {
  [[ "$name" =~ ^/voiceover-studio/[A-Za-z0-9_./-]+$ ]] ||
    die "The name must start with /voiceover-studio/ (the instance can only read those), e.g. /voiceover-studio/hf-token"
}

case "$action" in
  put)
    check_name
    [[ -t 0 ]] || die "Run this in a terminal: the value is typed in, never passed as an argument."
    read -r -s -p "Value for $name (hidden): " value
    echo
    [[ -n "$value" ]] || die "Empty value; nothing stored."
    if aws ssm get-parameter --name "$name" >/dev/null 2>&1; then
      input=$(jq -n --arg n "$name" --arg v "$value" '{Name: $n, Value: $v, Type: "SecureString", Overwrite: true}')
    else
      input=$(jq -n --arg n "$name" --arg v "$value" \
        '{Name: $n, Value: $v, Type: "SecureString", Tags: [{Key: "project", Value: "voiceover-studio"}]}')
    fi
    unset value
    aws ssm put-parameter --cli-input-json file:///dev/stdin <<<"$input" >/dev/null # not on the command line
    say "Stored $name. Reference it in .env, then run ./scripts/deploy.sh"
    ;;
  delete)
    check_name
    aws ssm delete-parameter --name "$name"
    say "Deleted $name."
    ;;
  list)
    aws ssm describe-parameters --parameter-filters Key=Name,Option=BeginsWith,Values=/voiceover-studio/ \
      --query 'Parameters[].[Name, LastModifiedDate]' --output table
    ;;
  *) die "Usage: ./scripts/secret.sh put|delete <name>, or ./scripts/secret.sh list" ;;
esac
