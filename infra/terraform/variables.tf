# Set from .env by scripts/deploy.sh (TF_VAR_*). The defaults match .env.example.

variable "region" {
  description = "AWS region. The deploy role's policies are written for us-east-1."
  type        = string
  default     = "us-east-1"
}

variable "compute_profile" {
  description = "gpu: local models (default). cpu: every model is hosted, so a small CPU instance is enough."
  type        = string
  default     = "gpu"

  validation {
    condition     = contains(["gpu", "cpu"], var.compute_profile)
    error_message = "compute_profile must be gpu or cpu."
  }
}

variable "instance_type" {
  description = "g6.xlarge (L4 24 GB, default), g5.xlarge (A10G 24 GB), g4dn.xlarge (T4 16 GB), t3.medium (cpu profile)."
  type        = string
  default     = "g6.xlarge"

  validation {
    # The same list as the deploy role's guardrails: anything else would be denied anyway.
    condition     = contains(["g6.xlarge", "g5.xlarge", "g4dn.xlarge", "t3.medium"], var.instance_type)
    error_message = "instance_type must be one of g6.xlarge, g5.xlarge, g4dn.xlarge, t3.medium."
  }
}

variable "availability_zone" {
  description = "Pin the instance to one zone (e.g. us-east-1b) when AWS reports no capacity. Empty = pick one."
  type        = string
  default     = ""
}

variable "ami_id" {
  description = "Use this Amazon-owned image instead of the latest Deep Learning AMI. Empty = look it up."
  type        = string
  default     = ""
}

variable "root_volume_gb" {
  description = "Disk size: the AMI (OS, CUDA), Docker images (~30 GB unpacked) and models (~13 GB). Charged while stopped too."
  type        = number
  default     = 150

  validation {
    condition     = var.root_volume_gb >= 30 && var.root_volume_gb <= 200
    error_message = "root_volume_gb must be between 30 and 200 (the guardrails deny larger disks)."
  }
}

variable "idle_stop_minutes" {
  description = "First-boot value for the idle auto-stop; every deploy updates it from IDLE_STOP_MINUTES."
  type        = number
  default     = 30
}

variable "idle_cpu_percent" {
  description = "Backstop alarm: stop the instance after 60 minutes with average CPU below this."
  type        = number
  default     = 5
}

variable "budget_monthly_usd" {
  description = "Monthly budget for this project. Emails at 80% of actual and 100% of forecast spend."
  type        = number
  default     = 30

  validation {
    condition     = var.budget_monthly_usd > 0
    error_message = "budget_monthly_usd must be more than 0."
  }
}

variable "budget_email" {
  description = "Where budget alerts go."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_email)) && var.budget_email != "you@example.com"
    error_message = "Set BUDGET_EMAIL in .env to your email address."
  }
}
