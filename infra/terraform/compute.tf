# One instance. GPU profile: the AWS Deep Learning Base AMI (Ubuntu 24.04), which comes with the NVIDIA driver,
# Docker and the NVIDIA Container Toolkit. CPU profile: Amazon Linux 2023. Both are Amazon-owned images
# (the guardrails deny any other owner, which keeps paid Marketplace images out).

data "aws_ami" "gpu" {
  count       = local.gpu && var.ami_id == "" ? 1 : 0
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04) *"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

data "aws_ami" "cpu" {
  count       = !local.gpu && var.ami_id == "" ? 1 : 0
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
}

data "aws_ami" "chosen" {
  owners = ["amazon"]
  filter {
    name   = "image-id"
    values = [var.ami_id != "" ? var.ami_id : (local.gpu ? data.aws_ami.gpu[0].id : data.aws_ami.cpu[0].id)]
  }
}

locals {
  # The disk can't be smaller than the image's own snapshot.
  ami_min_volume_gb = max(0, [
    for m in data.aws_ami.chosen.block_device_mappings : tonumber(lookup(m.ebs, "volume_size", "0"))
  ]...)
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.chosen.id
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnet.chosen.id
  vpc_security_group_ids = [aws_security_group.instance.id]
  iam_instance_profile   = aws_iam_instance_profile.instance.name

  associate_public_ip_address = true   # outbound only (no inbound rules); avoids a ~$32/month NAT gateway
  instance_initiated_shutdown_behavior = "stop" # the idle timer shuts down -> stopped, not terminated

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 2          # so the app container can get the instance role's credentials
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    iops                  = 3000 # gp3 baseline: free
    throughput            = 125  # gp3 baseline: free
    encrypted             = true
    delete_on_termination = true
    tags                  = merge(local.tags, { Name = local.name })
  }

  # First boot only: installs the idle auto-stop. The app is installed by scripts/deploy.sh.
  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    idle_stop_minutes = var.idle_stop_minutes
    idle_stop_sh      = base64encode(file("${path.module}/../instance/idle-stop.sh"))
    idle_service      = base64encode(file("${path.module}/../instance/voiceover-idle.service"))
    idle_timer        = base64encode(file("${path.module}/../instance/voiceover-idle.timer"))
  })

  tags = { Name = local.name }

  lifecycle {
    # A newer AMI or changed first-boot script must not silently replace the instance (and its downloaded
    # models). To move to a new image on purpose: ./scripts/deploy.sh --replace-instance
    ignore_changes = [ami, user_data]

    precondition {
      condition     = var.root_volume_gb >= local.ami_min_volume_gb
      error_message = "ROOT_VOLUME_GB must be at least ${local.ami_min_volume_gb} for this image."
    }
    precondition {
      condition     = local.gpu == startswith(var.instance_type, "g")
      error_message = "COMPUTE_PROFILE=${var.compute_profile} doesn't match INSTANCE_TYPE=${var.instance_type}: use a g* type for gpu and t3.medium for cpu."
    }
  }
}
