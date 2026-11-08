# AWS services used

Every AWS service this project touches: what it's for, who creates it, what it costs and whether `destroy.sh`
removes it. Kept up to date as the project changes (see the change log at the end).

Region: **us-east-1**. Prices are us-east-1 on-demand list prices (check current prices).
**Created by:** *account setup* = the one-time admin setup (`scripts/bootstrap.sh`, or by hand: `infra/bootstrap/README.md`); removed with `bootstrap.sh --remove`; *Terraform* = `deploy.sh`;
*script* = another command in `scripts/`; *AWS* = created by AWS itself.

## Runs the app

| Service | What we use | Purpose | Created by | Cost | Removed by `destroy.sh` |
|---|---|---|---|---|---|
| **Amazon EC2** | 1 instance `voiceover-studio`: g6.xlarge (NVIDIA L4 24 GB, 4 vCPU, 16 GiB) | Runs the app and both models | Terraform | ≈ $0.80/h while running; $0 while stopped | Yes |
| EC2: **EBS** | 1 gp3 root volume, 150 GB, encrypted, 3000 IOPS / 125 MB/s (free baseline) | OS + CUDA (AMI), Docker images (~30 GB), models (~13 GB) | Terraform | ≈ $12/month, **also while stopped** | Yes (deleted with the instance) |
| EC2: **AMI** | AWS Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04), owned by Amazon | NVIDIA driver, Docker, NVIDIA Container Toolkit | AWS (we only use it) | Free | n/a |
| EC2: **VPC** | The default VPC and one default subnet | Networking without creating anything | AWS (exists in every account) | Free | n/a (not ours) |
| EC2: **security group** | `voiceover-studio`: no inbound rules; outbound 443 and 80 | Nothing can connect in | Terraform | Free | Yes |
| EC2: **public IPv4** | One auto-assigned address while running | Outbound internet (downloads, AWS APIs) without a NAT gateway (~$32/month) | AWS, at launch | ≈ $0.005/h while running | Yes (released on stop/terminate) |
| **Amazon S3** | Bucket `voiceover-studio-<account>-us-east-1`: `voices/`, `outputs/`, `deploy/` | Voice samples + consent records, finished voiceovers, code bundles for deploys | Terraform | Cents (a few GB at most) | Yes, after offering a download to `backups/` |
| **AWS Systems Manager** (SSM): Session Manager | Port forwarding (`AWS-StartPortForwardingSession`), browser shell | Private tunnel to the UI; shell access without SSH or open ports | AWS (agent on the AMI) | Free | n/a |
| SSM: **Run Command** | `AWS-RunShellScript` | `deploy.sh` installs and updates the app; `status.sh` checks it | AWS | Free | n/a |
| SSM: **Parameter Store** | SecureString parameters under `/voiceover-studio/` (optional: HF token, API keys) | Secrets, never in files or images | script (`secret.sh`) | Free (standard parameters) | Yes |
| **AWS IAM** | Role + instance profile `voiceover-studio-instance` (path `/voiceover-studio/`), inline policy, `AmazonSSMManagedInstanceCore` | What the instance may do: own bucket, own parameters, own logs, SSM | Terraform | Free | Yes |
| **Amazon CloudWatch** Logs | Log group `/voiceover-studio/app`, 14-day retention | Container logs (app, vLLM) | Terraform | Cents | Yes |
| CloudWatch **alarms + metrics** | Alarm `voiceover-studio-idle-stop` on `CPUUtilization`, with the EC2 stop action | Stops the instance after 60 min of near-zero CPU (backstop for the idle timer) | Terraform | ≈ $0.10/month | Yes |
| **AWS Budgets** | Budget `voiceover-studio-monthly` ($30, email at 80% actual / 100% forecast) | Spending alerts for this project | Terraform | Free (first two budgets) | Yes |

## Guards the account (one-time setup)

| Service | What we use | Purpose | Created by | Cost | Removed by `destroy.sh` |
|---|---|---|---|---|---|
| **AWS IAM** | Role `VoiceoverStudioDeployer` (MFA required, 1 h sessions); policies `voiceover-studio-deployer-compute`, `-deployer-services`, `-guardrails`, `-instance-boundary`; user `voiceover-operator` (console sign-in + MFA, no access keys) | Least-privilege deploys and guardrails against surprise bills | account setup | Free | No (`bootstrap.sh --remove`) |
| **AWS Sign-In** (`aws login`) | Console sign-in turned into short-lived CLI credentials (managed policy `SignInLocalDevelopmentAccess`) | No long-lived access keys anywhere | account setup | Free | No |
| **AWS STS** | `AssumeRole` with MFA; `GetCallerIdentity` | Temporary credentials for the deploy role; preflight checks | AWS | Free | n/a |
| **Service Quotas** | EC2 "Running On-Demand G and VT instances" = 4 vCPUs | At most one GPU instance can run | account setup (request); AWS approves | Free | No (kept) |
| **AWS Budgets** | Account budget `account-monthly` | Spending alerts for the whole account | account setup | Free | No (`bootstrap.sh --remove`) |
| **Cost Anomaly Detection** | Monitor (AWS services) with an email subscription | Alerts on unusual spending | account setup | Free | No |
| **Cost Explorer** | Enabled | See where the money went | account setup | Free in the console | No |
| **S3** (account setting) | Block Public Access at account level | No bucket can be made public | account setup | Free | No |

## Used by the scripts (no resources)

| Service | Call | Why |
|---|---|---|
| EC2 | `DescribeImages`, `DescribeInstanceTypeOfferings`, `DescribeVpcs`, `DescribeSubnets`, `Start/StopInstances` | Find the AMI and a zone that offers the instance type; start and stop |
| Service Quotas | `GetServiceQuota` (quota `L-DB2E81BA`) | Preflight: is the GPU quota approved? |
| Resource Groups Tagging API | `GetResources` with tag `project=voiceover-studio` | `destroy.sh` proves nothing is left |

## Not used (on purpose)

| Service | Why not |
|---|---|
| NAT gateway, Elastic IP, VPC endpoints, load balancers | Cost (≈ $32/month for NAT alone) and not needed: no inbound traffic, outbound via the instance's public IPv4. Denied by the guardrails |
| ECR | The image is built on the instance from the code bundle; the repo is private, and the deploy role has no ECR access |
| SageMaker | Too much machinery for one user and one GPU |
| KMS customer-managed keys | S3-managed and AWS-managed keys encrypt at rest at no cost |
| Spot instances, reservations, Savings Plans | Denied by the guardrails (spot can come later as an option) |
| **Amazon Bedrock** | Optional LLM fallback, **not enabled yet**: needs IAM additions after the dry run |

## Change log

| Date | Change |
|---|---|
| 2026-11-08 | First version: services as built in `infra/terraform/` and the account setup. Dry run in progress |
| 2026-11-08 | SSM Run Command: the install now runs as a background systemd service on the instance; Run Command only starts it and reads its log every 15 s (one long command hit its time limit in the dry run) |
| 2026-11-08 | EBS root volume 100 → 150 GB (≈ $8 → $12/month, also while stopped): the first install ran out of disk unpacking the vLLM image. A size change replaces the instance (the deploy role can't resize volumes; `terraform_data` + `replace_triggered_by`) |
| 2026-11-08 | Account setup scripted: `scripts/bootstrap.sh` creates or checks S3 Block Public Access, the account budget, cost anomaly alerts (monitor `voiceover-account-services`, subscription `voiceover-account-alerts`), the GPU quota request, the four policies, the operator user and the deploy role; `--remove` deletes them. Policies moved to `infra/bootstrap/policies/` |
