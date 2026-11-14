from __future__ import annotations

import json
import time

import boto3

import scenarios as sc_mod


def check_scenario(glue, registry: str, scenario: sc_mod.Scenario,
                   compatibility: str = "BACKWARD") -> dict:
    name = f"orders-{scenario.code.lower().replace('_', '-')}"
    schema_id = {"RegistryName": registry, "SchemaName": name}
    base = sc_mod.base_json_schema()
    producer = scenario.mutate_schema(sc_mod.base_json_schema())
    t0 = time.perf_counter()

    try:
        glue.delete_schema(SchemaId=schema_id)
        time.sleep(2)
    except glue.exceptions.EntityNotFoundException:
        pass

    glue.create_schema(
        RegistryId={"RegistryName": registry},
        SchemaName=name,
        DataFormat="JSON",
        Compatibility=compatibility,
        SchemaDefinition=json.dumps(base),
    )
    resp = glue.register_schema_version(SchemaId=schema_id, SchemaDefinition=json.dumps(producer))
    version_id = resp["SchemaVersionId"]
    status = resp["Status"]
    for _ in range(30):
        if status not in ("PENDING",):
            break
        time.sleep(1)
        status = glue.get_schema_version(SchemaVersionId=version_id)["Status"]

    glue.delete_schema(SchemaId=schema_id)
    detected = status == "FAILURE"
    return {
        "scenario": scenario.code,
        "mechanism": "schema_registry",
        "compatibility": compatibility,
        "producer_schema_changed": producer != base,
        "version_status": status,
        "detected": detected,
        "stage": "публікація схеми виробником" if detected else "—",
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def run_all(registry: str, region: str, compatibility: str = "BACKWARD") -> list[dict]:
    glue = boto3.client("glue", region_name=region)
    out = []
    for sc in sc_mod.SCENARIOS:
        r = check_scenario(glue, registry, sc, compatibility)
        print(f"  {sc.code:<22} {r['version_status']}")
        out.append(r)
    return out
