# Names below are fixed on purpose: the deploy role's IAM policies only allow these name patterns
# (voiceover-studio-*, /voiceover-studio/*). Changing them here means changing the policies too.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name       = "voiceover-studio"
  tags       = { project = "voiceover-studio" }
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  gpu        = var.compute_profile == "gpu"

  bucket_name  = "voiceover-studio-${local.account_id}-${var.region}"
  log_group    = "/voiceover-studio/app"
  boundary_arn = "arn:${local.partition}:iam::${local.account_id}:policy/voiceover-studio-instance-boundary"
}
