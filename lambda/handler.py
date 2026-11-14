from __future__ import annotations

import json
import os
import time
import urllib.parse

import boto3

from contract_validator import DataContract

s3 = boto3.client("s3")
sns = boto3.client("sns")

BUCKET = os.environ["BUCKET"]
CONTRACT_KEY = os.environ.get("CONTRACT_KEY", "contracts/orders.odcs.yaml")
TOPIC_ARN = os.environ.get("TOPIC_ARN", "")

_contract: DataContract | None = None


def _get_contract() -> DataContract:
    global _contract
    if _contract is None:
        body = s3.get_object(Bucket=BUCKET, Key=CONTRACT_KEY)["Body"].read().decode("utf-8")
        _contract = DataContract.from_yaml(body)
    return _contract


def lambda_handler(event, context):
    contract = _get_contract()
    out = []
    for rec in event.get("Records", []):
        bucket = rec["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])
        scenario = os.path.splitext(os.path.basename(key))[0]

        started = time.perf_counter()
        text = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
        result = contract.validate_csv(text)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

        target = "validated" if result.valid else "quarantine"
        s3.copy_object(Bucket=bucket, Key=f"{target}/{os.path.basename(key)}",
                       CopySource={"Bucket": bucket, "Key": key})

        payload = {
            "scenario": scenario,
            "mechanism": "odcs_contract",
            "contract_id": contract.id,
            "contract_version": contract.version,
            "owner": contract.owner,
            "detected": not result.valid,
            "stage": "landing (до завантаження в озеро даних)",
            "elapsed_ms": elapsed_ms,
            **result.to_dict(),
        }
        s3.put_object(Bucket=bucket, Key=f"results/contract/{scenario}.json",
                      Body=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                      ContentType="application/json")

        if not result.valid and TOPIC_ARN:
            sns.publish(
                TopicArn=TOPIC_ARN,
                Subject=f"[data contract] {contract.id} порушено: {scenario}"[:100],
                Message=(f"Файл s3://{bucket}/{key} не відповідає контракту "
                         f"{contract.id} v{contract.version}.\n"
                         f"Власник даних: {contract.owner}\n"
                         f"Файл переміщено в quarantine/.\n\nПомилки:\n- "
                         + "\n- ".join(result.errors)),
            )
        out.append(payload)
        print(json.dumps(payload, ensure_ascii=False))
    return {"processed": len(out)}
