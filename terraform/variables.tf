variable "region" {
  description = "Регіон AWS"
  type        = string
  default     = "eu-central-1"
}

variable "project" {
  description = "Префікс імен ресурсів"
  type        = string
  default     = "data-contracts"
}

variable "alert_email" {
  description = "Email для сповіщень SNS про порушення контракту (порожньо — без підписки)"
  type        = string
  default     = ""
}
