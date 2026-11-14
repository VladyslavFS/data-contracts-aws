from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import scenarios as sc_mod


def write_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data")
    p.add_argument("--rows", type=int, default=200)
    args = p.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    base = sc_mod.generate_base_rows(args.rows)

    for sc in sc_mod.SCENARIOS:
        cols, rows = sc_mod.build_scenario(sc, base)
        write_csv(out / sc.file_name, cols, rows)
        schema = sc.mutate_schema(sc_mod.base_json_schema())
        (out / f"{sc.code}.schema.json").write_text(
            json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"{sc.code:<22} {len(rows):>4} рядків  [{sc.change_class}] {sc.title}")


if __name__ == "__main__":
    main()
