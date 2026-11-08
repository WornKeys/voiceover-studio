"""Account-setup policies (infra/bootstrap/policies): valid, within IAM's limits, in step with Terraform."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
POLICIES = ROOT / "infra" / "bootstrap" / "policies"
MANAGED = ["instance-boundary.json", "deployer-compute-policy.json", "deployer-services-policy.json",
           "guardrails-policy.json"]  # fmt: skip


def render(name: str) -> dict:
    text = (POLICIES / name).read_text(encoding="utf-8")
    return json.loads(text.replace("ACCOUNT_ID", "123456789012").replace("REGION", "us-east-1"))


@pytest.mark.parametrize("name", sorted(p.name for p in POLICIES.glob("*.json")))
def test_policy_is_valid_after_filling_in_the_placeholders(name):
    policy = render(name)
    assert policy["Version"] == "2012-10-17" and policy["Statement"]
    text = json.dumps(policy)
    assert "ACCOUNT_ID" not in text and "REGION" not in text


@pytest.mark.parametrize("name", MANAGED)
def test_managed_policy_fits_iams_size_limit(name):
    # IAM counts a managed policy's characters without whitespace; the limit is 6,144.
    assert len(re.sub(r"\s", "", (POLICIES / name).read_text(encoding="utf-8"))) < 6144


def test_terraform_names_match_what_the_deploy_role_allows():
    terraform = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "infra" / "terraform").glob("*.tf"))
    compute = json.dumps(render("deployer-compute-policy.json"))
    # The instance role lives under /voiceover-studio/ and carries the boundary the role insists on.
    assert 'path                 = "/voiceover-studio/"' in terraform
    assert "policy/voiceover-studio-instance-boundary" in terraform
    assert "role/voiceover-studio/*" in compute and "policy/voiceover-studio-instance-boundary" in compute
    # Terraform tags everything project=voiceover-studio, which the role requires on create.
    assert 'tags       = { project = "voiceover-studio" }' in terraform
    assert '"aws:RequestTag/project": "voiceover-studio"' in compute
    # The four instance types allowed by Terraform's validation are exactly the guardrails' list.
    guardrails = json.dumps(render("guardrails-policy.json"))
    allowed = re.search(r'"ec2:InstanceType": \[([^\]]*)\]', guardrails).group(1)
    for instance_type in ("g6.xlarge", "g5.xlarge", "g4dn.xlarge", "t3.medium"):
        assert instance_type in allowed and instance_type in terraform


def test_trust_policy_requires_mfa_and_names_only_the_operator():
    statement = render("trust-policy.json")["Statement"][0]
    assert statement["Principal"] == {"AWS": "arn:aws:iam::123456789012:user/voiceover-operator"}
    assert statement["Condition"] == {"Bool": {"aws:MultiFactorAuthPresent": "true"}}
