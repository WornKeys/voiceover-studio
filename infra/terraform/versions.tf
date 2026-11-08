terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.70"
    }
  }
  # State is local (infra/terraform/terraform.tfstate, git-ignored). Keep it: destroy.sh needs it.
}

provider "aws" {
  region = var.region

  # Every resource carries project=voiceover-studio. The deploy role can only create and manage resources
  # with this tag, and destroy.sh uses it to prove nothing is left behind.
  default_tags {
    tags = local.tags
  }
}
