# One private, encrypted bucket: voice samples + consent records (voices/), finished voiceovers (outputs/)
# and the code bundles that deploy.sh uploads (deploy/).
#
# No versioning, on purpose: deleting a voice in the UI must really delete the recording (voice samples are
# biometric-like data), not keep an old version around.

resource "aws_s3_bucket" "data" {
  bucket = local.bucket_name
  # destroy.sh first offers to download your files, then destroy removes the bucket with everything in it.
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    object_ownership = "BucketOwnerEnforced" # no ACLs at all
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # S3-managed keys: encrypted at rest, no KMS key to pay for or manage
    }
  }
}

data "aws_iam_policy_document" "tls_only" {
  statement {
    sid     = "DenyUnencryptedTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.data.arn,
      "${aws_s3_bucket.data.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "data" {
  bucket     = aws_s3_bucket.data.id
  policy     = data.aws_iam_policy_document.tls_only.json
  depends_on = [aws_s3_bucket_public_access_block.data]
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    id     = "old-code-bundles"
    status = "Enabled"
    filter {
      prefix = "deploy/"
    }
    expiration {
      days = 30
    }
  }

  rule {
    id     = "unfinished-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}
