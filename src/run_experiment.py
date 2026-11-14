from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import matrix  # noqa: E402
import scenarios as sc_mod  # noqa: E402
import schema_registry_check  # noqa: E402
from generate_data import write_csv  # noqa: E402


def tf_outputs() -> dict:
    raw = subprocess.check_output(["terraform", "output", "-json"], cwd=ROOT / "terraform")
    return {k: v["value"] for k, v in json.loads(raw).items()}


def wait_for_object(s3, bucket: str, key: str, timeout: int = 180) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            return json.loads(body)
        except s3.exceptions.NoSuchKey:
            time.sleep(3)
    raise TimeoutError(f"не дочекалися s3://{bucket}/{key}")


def clear_prefix(s3, bucket: str, prefix: str) -> None:
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if objs:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": objs})


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--skip-glue", action="store_true", help="не запускати Glue job (економія)")
    p.add_argument("--compatibility", default="BACKWARD")
    p.add_argument("--glue-batch", type=int, default=4,
                   help="скільки Glue job запускати одночасно (ліміти нових акаунтів малі)")
    args = p.parse_args()

    cfg = tf_outputs()
    bucket, region = cfg["bucket_name"], cfg["region"]
    s3 = boto3.client("s3", region_name=region)
    glue = boto3.client("glue", region_name=region)

    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    base = sc_mod.generate_base_rows()
    for sc in sc_mod.SCENARIOS:
        cols, rows = sc_mod.build_scenario(sc, base)
        write_csv(data_dir / sc.file_name, cols, rows)
    print(f"[1/5] Згенеровано {len(sc_mod.SCENARIOS)} файлів у {data_dir}")

    for prefix in ("landing/", "validated/", "quarantine/", "results/", "lake/"):
        clear_prefix(s3, bucket, prefix)
    for sc in sc_mod.SCENARIOS:
        s3.upload_file(str(data_dir / sc.file_name), bucket, f"landing/{sc.file_name}")
    print("[2/5] Файли завантажено в landing/, чекаємо на Lambda...")
    results: dict[str, dict[str, dict]] = {sc.code: {} for sc in sc_mod.SCENARIOS}
    for sc in sc_mod.SCENARIOS:
        r = wait_for_object(s3, bucket, f"results/contract/{sc.code}.json")
        results[sc.code]["odcs_contract"] = r
        print(f"  {sc.code:<22} контракт: {'ПОРУШЕНО' if r['detected'] else 'ok'}")

    # 3. Glue job
    if not args.skip_glue:
        print(f"[3/5] Запуск Glue job для кожного сценарію (по {args.glue_batch} одночасно)...")
        queue = [sc for sc in sc_mod.SCENARIOS]
        running: dict[str, str] = {}
        while queue or running:
            while queue and len(running) < args.glue_batch:
                sc = queue.pop(0)
                running[sc.code] = glue.start_job_run(
                    JobName=cfg["glue_job_name"],
                    Arguments={
                        "--input_path": f"s3://{bucket}/landing/{sc.file_name}",
                        "--scenario": sc.code,
                        "--bucket": bucket,
                        "--ruleset_key": cfg["ruleset_key"],
                    },
                )["JobRunId"]
            time.sleep(15)
            for code in list(running):
                st = glue.get_job_run(JobName=cfg["glue_job_name"], RunId=running[code])["JobRun"]
                if st["JobRunState"] in ("SUCCEEDED", "FAILED", "TIMEOUT", "STOPPED", "ERROR"):
                    running.pop(code)
                    print(f"  {code:<22} {st['JobRunState']}")
                    if st["JobRunState"] != "SUCCEEDED":
                        results[code]["no_contract"] = {"detected": True, "stage": "збій Glue job",
                                                        "error": st.get("ErrorMessage")}
        for sc in sc_mod.SCENARIOS:
            try:
                r = wait_for_object(s3, bucket, f"results/glue/{sc.code}.json", timeout=30)
                results[sc.code].setdefault("no_contract", r["no_contract"])
                results[sc.code]["glue_dq"] = r["glue_dq"]
            except TimeoutError:
                print(f"  ! немає результату Glue для {sc.code}")
    else:
        print("[3/5] Glue job пропущено (--skip-glue)")

    # 4. Schema Registry
    print(f"[4/5] Перевірка Glue Schema Registry (режим {args.compatibility})...")
    for r in schema_registry_check.run_all(cfg["registry_name"], region, args.compatibility):
        results[r["scenario"]]["schema_registry"] = r

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / "raw_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    table = matrix.build(results, out)
    print("[5/5] Готово. Таблиця 1 -> results/matrix.csv, results/matrix.md\n")
    matrix.print_table(table)


if __name__ == "__main__":
    main()
