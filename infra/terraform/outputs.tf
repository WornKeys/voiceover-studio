output "instance_id" {
  value = aws_instance.app.id
}

output "bucket" {
  value = aws_s3_bucket.data.bucket
}

output "region" {
  value = var.region
}

output "availability_zone" {
  value = aws_instance.app.availability_zone
}

output "ami" {
  value = "${data.aws_ami.chosen.id} (${data.aws_ami.chosen.name})"
}

output "log_group" {
  value = aws_cloudwatch_log_group.app.name
}
