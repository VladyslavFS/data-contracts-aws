output "region" {
  value = var.region
}

output "bucket_name" {
  value = aws_s3_bucket.data.id
}

output "glue_job_name" {
  value = aws_glue_job.etl_dq.name
}

output "registry_name" {
  value = aws_glue_registry.this.registry_name
}

output "ruleset_key" {
  value = local.ruleset_key
}

output "lambda_name" {
  value = aws_lambda_function.validator.function_name
}

output "sns_topic_arn" {
  value = aws_sns_topic.alerts.arn
}
