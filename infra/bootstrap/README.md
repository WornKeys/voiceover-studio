# One-time account setup

Before the first deploy, an AWS account needs a few things that the deploy scripts can't (and shouldn't) create
for themselves: a deploy role that can only build this project, guardrails against surprise bills, and a GPU
quota. `scripts/bootstrap.sh` sets all of it up with an **admin** profile, once.

**Your existing account is fine.** The guardrails are attached to the project's own deploy role, not to the
account, so nothing else you run is restricted. A separate account is simply tidier: the bill shows only this
project, and the project can't touch anything else. In an account that's already in use, the script behaves a
little differently (see the table below), and the project budget counts the whole account's spending, so set
`BUDGET_MONTHLY_USD` to your usual monthly spend plus about $30. Preflight also checks that the region still has
its default VPC (some older accounts deleted it).

```bash
./scripts/bootstrap.sh --profile <your-admin-profile>      # shows what it will do, asks, then does it
```

It's safe to re-run: it checks every piece, says `✓` for what's already right, and only creates or updates what's
missing or different (a policy that differs from the repo's version is shown as a diff first).

## What it sets up

| Piece | Why |
|---|---|
| S3 Block Public Access (whole account) | No bucket in the account can be made public by mistake. **Only in an account with no other buckets:** elsewhere, one of them may be public on purpose (a static website), so the script leaves the setting alone and says so. The project's bucket blocks public access on its own either way |
| Budget `account-monthly` ($`ACCOUNT_BUDGET_USD`, default 30) | Emails `BUDGET_EMAIL` at 50 %, 80 % and 100 % of actual spend and at 100 % of the forecast. Separate from the project budget that Terraform creates and destroys. **Skipped if the account already has budgets** |
| Cost anomaly alerts | A daily email when spending on a service jumps by $10 or more |
| GPU quota request: 4 vCPUs | "Running On-Demand G and VT instances" starts at 0. 4 vCPUs = exactly one g6/g5 `.xlarge`. AWS approves it, in hours to days, so start early |
| Policy `voiceover-studio-deployer-compute` + `-deployer-services` | What the deploy role may do: only this project's names, tags and resource types (two files because of IAM's 6,144-character limit) |
| Policy `voiceover-studio-guardrails` | Explicit denies that win over any allow: one region, four instance types, Amazon-owned images only, gp3 disks up to 200 GB, no inbound ports, no NAT gateway / Elastic IP / reservations / Marketplace, no quota increases |
| Policy `voiceover-studio-instance-boundary` | The permissions boundary every instance role must carry: own bucket, own parameters, own logs, SSM. Even a compromised app can't do more |
| User `voiceover-operator` | You, for daily use. It can do nothing except assume the deploy role (and use `aws login`). No access keys |
| Role `VoiceoverStudioDeployer` | What the scripts run as. Only `voiceover-operator` can assume it, only with MFA, for 1 hour at a time |

The policy files are in [`policies/`](policies/); `ACCOUNT_ID` and `REGION` are filled in when they're applied.

Resources it creates are tagged `project=voiceover-studio-account` (not `voiceover-studio`, which `destroy.sh`
uses to prove the project itself is gone).

## Your part (the script tells you what's still missing)

These need you, or your phone, so they stay manual:

1. **Root user:** MFA on, no access keys. Then, still as root: Account → "IAM user and role access to Billing
   information" → **Activate** (otherwise an admin user can't create budgets). Use an IAM admin user from then on.
2. **Operator console password and MFA:** IAM → Users → `voiceover-operator` → Security credentials: enable
   console access, and assign a virtual MFA device. Run `bootstrap.sh` again afterwards: it prints the
   `~/.aws/config` lines with your MFA device filled in.
3. **Sign in:** install the AWS CLI v2 (2.32 or later), add the two profiles it printed, then
   `aws login --profile voiceover-operator` (a browser opens: password + MFA). Set `AWS_PROFILE=voiceover` in `.env`.
4. **Check:** `aws sts get-caller-identity --profile voiceover` asks for your MFA code and prints
   `…:assumed-role/VoiceoverStudioDeployer/…`; `aws s3 ls --profile voiceover` fails with AccessDenied (the role
   really is restricted).

## Removing it

After `./scripts/destroy.sh` (it refuses while project resources still exist):

```bash
./scripts/bootstrap.sh --profile <your-admin-profile> --remove
```

It deletes the role, the operator user (password, MFA device, policies), the four policies, the account budget and
the anomaly alerts it created. It keeps S3 Block Public Access and the GPU quota (both free).

## Doing it by hand instead

Everything above can also be done in the console, in this order (the role's trust policy names the user, so the
user must exist first):

1. S3 → Block Public Access settings for this account → all four on. Billing → Budgets → create `account-monthly`.
   Cost Management → Cost Anomaly Detection → AWS services monitor + email alert. Service Quotas → Amazon EC2 →
   "Running On-Demand G and VT instances" → request 4.
2. IAM → Policies → Create policy → JSON, once per file in `policies/` (replace `ACCOUNT_ID` with your 12-digit
   account ID and `REGION` with `us-east-1`): `voiceover-studio-instance-boundary` ← `instance-boundary.json`,
   `voiceover-studio-deployer-compute` ← `deployer-compute-policy.json`, `voiceover-studio-deployer-services` ←
   `deployer-services-policy.json`, `voiceover-studio-guardrails` ← `guardrails-policy.json`.
3. IAM → Users → create `voiceover-operator`: inline policy ← `operator-user-policy.json`, managed policy
   `SignInLocalDevelopmentAccess`, console password, MFA device. No access key.
4. IAM → Roles → create `VoiceoverStudioDeployer` with a custom trust policy ← `trust-policy.json`; attach the
   compute, services and guardrails policies (**not** the boundary); maximum session duration 1 hour.

## Notes

- **Region:** the guardrails deny every region except `REGION`. IAM, STS and Budgets are global services whose
  requests count as us-east-1, so another region needs a `NotAction` exception for them in `guardrails-policy.json`.
- **Worst case with every layer in place:** one g5.xlarge (the most expensive allowed type) running non-stop ≈
  $730/month plus a 200 GB disk ≈ $16/month. The idle auto-stop and the CloudWatch alarm make that very unlikely,
  and the budget emails reach you within about a day (billing data lags 8 to 24 hours).
- **Not covered by AWS:** hosted model vendors (if you choose one) bill separately. Set a spending limit there.
