from __future__ import annotations

import csv
from pathlib import Path

import scenarios as sc_mod

MECHANISMS = [
    ("no_contract", "Без контракту (ETL)"),
    ("schema_registry", "Glue Schema Registry"),
    ("glue_dq", "Glue Data Quality"),
    ("odcs_contract", "Контракт даних ODCS"),
]


def mark(detected: bool | None, change_class: str) -> str:
    if detected is None:
        return "?"
    if change_class in (sc_mod.CLASS_COMPATIBLE, "—"):
        return "!" if detected else "·"
    return "+" if detected else "−"


def build(results: dict[str, dict[str, dict]], out_dir: Path) -> list[list[str]]:
    """results[scenario_code][mechanism] = {"detected": bool, "stage": str, ...}"""
    header = ["Код", "Зміна", "Клас зміни"] + [title for _, title in MECHANISMS]
    table = [header]
    totals = {m: 0 for m, _ in MECHANISMS}
    relevant = 0
    for sc in sc_mod.SCENARIOS:
        r = results.get(sc.code, {})
        row = [sc.code.split("_")[0], sc.title, sc.change_class]
        is_relevant = sc.change_class not in (sc_mod.CLASS_COMPATIBLE, "—")
        relevant += is_relevant
        for m, _ in MECHANISMS:
            det = r.get(m, {}).get("detected")
            row.append(mark(det, sc.change_class))
            if is_relevant and det:
                totals[m] += 1
        table.append(row)
    table.append(["", "Виявлено несумісних змін", ""] +
                 [f"{totals[m]} з {relevant}" for m, _ in MECHANISMS])

    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "matrix.csv").open("w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(table)
    with (out_dir / "matrix.md").open("w", encoding="utf-8") as f:
        f.write("| " + " | ".join(header) + " |\n")
        f.write("|" + "---|" * len(header) + "\n")
        for row in table[1:]:
            f.write("| " + " | ".join(row) + " |\n")
        f.write("\nПозначки: + виявлено; − пропущено; · сумісну зміну коректно пропущено; "
                "! хибна тривога; ? немає даних\n")
    return table


def print_table(table: list[list[str]]) -> None:
    widths = [max(len(str(r[i])) for r in table) for i in range(len(table[0]))]
    for r in table:
        print("  ".join(str(c).ljust(w) for c, w in zip(r, widths)))
