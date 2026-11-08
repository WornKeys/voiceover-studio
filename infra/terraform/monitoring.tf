resource "aws_cloudwatch_log_group" "app" {
  name              = local.log_group
  retention_in_days = 14
}

# Backstop for the idle timer on the instance: if the instance sits at near-zero CPU for an hour (e.g. the
# timer is broken), CloudWatch stops it. With "missing data = not breaching" the alarm resets to OK while the
# instance is stopped, so it fires again after the next start.
resource "aws_cloudwatch_metric_alarm" "idle_stop" {
  alarm_name          = "voiceover-studio-idle-stop"
  alarm_description   = "Stops the voiceover-studio instance after 60 minutes of average CPU below ${var.idle_cpu_percent}%."
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  dimensions          = { InstanceId = aws_instance.app.id }
  period              = 300
  evaluation_periods  = 12
  datapoints_to_alarm = 12
  comparison_operator = "LessThanThreshold"
  threshold           = var.idle_cpu_percent
  treat_missing_data  = "notBreaching"
  alarm_actions       = ["arn:${local.partition}:automate:${var.region}:ec2:stop"]
}

# This project's own budget (the account has its own, separate one). Billing data lags by up to a day.
resource "aws_budgets_budget" "monthly" {
  name         = "voiceover-studio-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_monthly_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}
