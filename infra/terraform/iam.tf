# The instance's role: least privilege, and capped by the permissions boundary the account admin created
# (voiceover-studio-instance-boundary). Even if the app were compromised, it could only read and write its own
# bucket, read its own parameters, write its own logs and talk to SSM.

data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name                 = "${local.name}-instance"
  path                 = "/voiceover-studio/"
  description          = "voiceover-studio instance: own bucket, own parameters, own logs, SSM"
  assume_role_policy   = data.aws_iam_policy_document.assume_ec2.json
  permissions_boundary = local.boundary_arn
}

data "aws_iam_policy_document" "instance" {
  statement {
    sid       = "ListOwnBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }
  statement {
    sid       = "ReadWriteOwnObjects"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.data.arn}/*"]
  }
  statement {
    sid       = "ReadOwnParameters"
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = ["arn:${local.partition}:ssm:${var.region}:${local.account_id}:parameter/voiceover-studio/*"]
  }
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["${aws_cloudwatch_log_group.app.arn}:*"]
  }
}

resource "aws_iam_role_policy" "instance" {
  name   = "${local.name}-instance"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.instance.json
}

# Lets the SSM agent register the instance (Session Manager tunnel, deploy commands).
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "instance" {
  name = "${local.name}-instance"
  path = "/voiceover-studio/"
  role = aws_iam_role.instance.name
}
