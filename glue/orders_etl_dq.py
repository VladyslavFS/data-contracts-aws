import json
import sys
import time
import traceback

import boto3
from awsglue.context import GlueContext
from awsglue.dynamicframe import DynamicFrame
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from awsgluedq.transforms import EvaluateDataQuality
from pyspark.context import SparkContext

args = getResolvedOptions(sys.argv, ["JOB_NAME", "input_path", "scenario", "bucket", "ruleset_key"])
sc = SparkContext()
glue_ctx = GlueContext(sc)
spark = glue_ctx.spark_session
job = Job(glue_ctx)
job.init(args["JOB_NAME"], args)

s3 = boto3.client("s3")
scenario = args["scenario"]
bucket = args["bucket"]
result = {"scenario": scenario, "input_path": args["input_path"]}

df = None
t0 = time.perf_counter()
try:
    df = (spark.read.option("header", "true").option("inferSchema", "true")
          .csv(args["input_path"]))
    out_path = f"s3://{bucket}/lake/orders/scenario={scenario}/"
    df.write.mode("overwrite").parquet(out_path)
    result["no_contract"] = {
        "mechanism": "no_contract",
        "detected": False,
        "stage": "—",
        "rows_written": df.count(),
        "inferred_schema": [f"{f.name}:{f.dataType.simpleString()}" for f in df.schema.fields],
        "note": "завдання завершилось успішно, дані записані в озеро",
    }
except Exception as e:  # noqa: BLE001
    result["no_contract"] = {
        "mechanism": "no_contract",
        "detected": True,
        "stage": "обробка (збій ETL-завдання)",
        "error": str(e)[:1000],
    }
result["no_contract"]["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)

t0 = time.perf_counter()
ruleset = s3.get_object(Bucket=bucket, Key=args["ruleset_key"])["Body"].read().decode("utf-8")
try:
    if df is None:
        raise RuntimeError("дані не прочитано")
    dyf = DynamicFrame.fromDF(df, glue_ctx, "orders")
    outcomes = EvaluateDataQuality.apply(
        frame=dyf,
        ruleset=ruleset,
        publishing_options={
            "dataQualityEvaluationContext": scenario,
            "enableDataQualityCloudWatchMetrics": False,
            "enableDataQualityResultsPublishing": False,
        },
    ).toDF().collect()
    rules = []
    for row in outcomes:
        r = row.asDict()
        rules.append({"rule": r.get("Rule"), "outcome": r.get("Outcome"),
                      "reason": r.get("FailureReason")})
    failed = [r for r in rules if r["outcome"] != "Passed"]
    result["glue_dq"] = {
        "mechanism": "glue_dq",
        "detected": bool(failed),
        "stage": "обробка (після читання даних)" if failed else "—",
        "rules_total": len(rules),
        "rules_failed": len(failed),
        "failed_rules": failed,
    }
except Exception as e:  # noqa: BLE001
    result["glue_dq"] = {
        "mechanism": "glue_dq",
        "detected": True,
        "stage": "обробка (помилка обчислення правил)",
        "error": str(e)[:1000],
        "trace": traceback.format_exc()[-1500:],
    }
result["glue_dq"]["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)

s3.put_object(
    Bucket=bucket,
    Key=f"results/glue/{scenario}.json",
    Body=json.dumps(result, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
    ContentType="application/json",
)
print(json.dumps(result, ensure_ascii=False, default=str))
job.commit()
