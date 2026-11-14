from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambda"))

from contract_validator import DataContract  # noqa: E402

_DQ_TYPE = {"date": "DATE"}


def _fmt_num(x) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def contract_to_dqdl(c: DataContract) -> str:
    rules: list[str] = []
    for q in c.table_quality:
        if q.get("rule") == "rowCount" and "mustBeGreaterThan" in q:
            rules.append(f"RowCount > {q['mustBeGreaterThan']}")
    for p in c.properties:
        rules.append(f'ColumnExists "{p["name"]}"')
    for p in c.properties:
        name, opts = p["name"], p.get("logicalTypeOptions", {}) or {}
        ltype = p.get("logicalType")
        if p.get("required") and ltype not in ("date",) and not any(
                q.get("rule") == "validValues" for q in p.get("quality", []) or []):
            rules.append(f'IsComplete "{name}"')
        if p.get("unique"):
            rules.append(f'IsUnique "{name}"')
        if ltype in ("number", "integer"):
            if "minimum" in opts:
                rules.append(f'ColumnValues "{name}" >= {_fmt_num(opts["minimum"])}')
            if "maximum" in opts:
                rules.append(f'ColumnValues "{name}" <= {_fmt_num(opts["maximum"])}')
        if ltype in _DQ_TYPE:
            rules.append(f'ColumnDataType "{name}" = "{_DQ_TYPE[ltype]}"')
        for q in p.get("quality", []) or []:
            if q.get("rule") == "validValues":
                vals = ", ".join(f'"{v}"' for v in q["validValues"])
                rules.append(f'ColumnValues "{name}" in [{vals}]')
    return "Rules = [\n    " + ",\n    ".join(rules) + "\n]\n"


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "contracts" / "orders.odcs.yaml")
    sys.stdout.write(contract_to_dqdl(DataContract.from_file(path)))
