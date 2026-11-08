# The default VPC: nothing to create or pay for (no NAT gateway, no load balancer, no Elastic IP).
# The instance gets a public IPv4 address for outbound traffic only; nothing can connect in.

data "aws_vpc" "default" {
  default = true
}

# Not every zone offers every GPU type (e.g. g6 isn't in us-east-1e), so only use zones that do.
data "aws_ec2_instance_type_offerings" "zones" {
  location_type = "availability-zone"

  filter {
    name   = "instance-type"
    values = [var.instance_type]
  }
}

data "aws_subnets" "usable" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
  filter {
    name   = "availability-zone"
    values = var.availability_zone != "" ? [var.availability_zone] : data.aws_ec2_instance_type_offerings.zones.locations
  }
}

data "aws_subnet" "chosen" {
  # (The placeholder only exists so the precondition below can report the problem in plain words.)
  id = length(data.aws_subnets.usable.ids) > 0 ? sort(data.aws_subnets.usable.ids)[0] : "no-usable-subnet"

  lifecycle {
    precondition {
      condition     = length(data.aws_subnets.usable.ids) > 0
      error_message = "No default subnet in a zone that offers ${var.instance_type} in ${var.region}. Try another INSTANCE_TYPE or AVAILABILITY_ZONE."
    }
  }
}

resource "aws_security_group" "instance" {
  name        = local.name
  description = "voiceover-studio: no inbound access (SSM only), outbound web access"
  vpc_id      = data.aws_vpc.default.id

  # No ingress rules: the UI is reached through an SSM Session Manager tunnel. (The guardrails deny any.)

  egress {
    description = "HTTPS: AWS APIs, SSM, model and package downloads"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "HTTP: OS package mirrors used while building the image"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
