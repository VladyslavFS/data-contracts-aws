from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime

import yaml

_JAVA_TO_PY_DATE = {"yyyy": "%Y", "MM": "%m", "dd": "%d"}


def _py_date_format(fmt: str) -> str:
    for java, py in _JAVA_TO_PY_DATE.items():
        fmt = fmt.replace(java, py)
    return fmt


@dataclass
class ValidationResult:
    valid: bool = True
    rows: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.valid = False
        self.errors.append(msg)

    def to_dict(self) -> dict:
        return {"valid": self.valid, "rows": self.rows,
                "errors": self.errors, "warnings": self.warnings}


class DataContract:
    def __init__(self, raw: dict):
        self.raw = raw
        self.id = raw.get("id")
        self.version = raw.get("version")
        self.owner = next((t["username"] for t in raw.get("team", []) if t.get("role") == "owner"), None)
        model = raw["schema"][0]
        self.table_quality = model.get("quality", [])
        self.properties = model["properties"]

    @classmethod
    def from_yaml(cls, text: str) -> "DataContract":
        return cls(yaml.safe_load(text))

    @classmethod
    def from_file(cls, path: str) -> "DataContract":
        with open(path, encoding="utf-8") as f:
            return cls.from_yaml(f.read())

    # ------------------------------------------------------------------
    def validate_csv(self, text: str, max_examples: int = 3) -> ValidationResult:
        res = ValidationResult()
        reader = csv.DictReader(io.StringIO(text))
        header = reader.fieldnames or []
        rows = list(reader)
        res.rows = len(rows)

        for q in self.table_quality:
            if q.get("rule") == "rowCount" and "mustBeGreaterThan" in q:
                if len(rows) <= q["mustBeGreaterThan"]:
                    res.error(f"rowCount: {len(rows)} рядків, очікується > {q['mustBeGreaterThan']}")

        expected = [p["name"] for p in self.properties]
        missing = [c for c in expected if c not in header]
        extra = [c for c in header if c not in expected]
        for c in missing:
            prop = next(p for p in self.properties if p["name"] == c)
            if prop.get("required"):
                res.error(f"schema: відсутнє обов'язкове поле '{c}'")
            else:
                res.warnings.append(f"schema: відсутнє необов'язкове поле '{c}'")
        for c in extra:
            res.warnings.append(f"schema: поле '{c}' не описане в контракті (допускається)")

        for prop in self.properties:
            name = prop["name"]
            if name not in header:
                continue
            values = [r.get(name, "") for r in rows]
            self._check_property(prop, values, res, max_examples)
        return res

    # ------------------------------------------------------------------
    def _check_property(self, prop: dict, values: list[str], res: ValidationResult, k: int) -> None:
        name = prop["name"]
        opts = prop.get("logicalTypeOptions", {}) or {}
        ltype = prop.get("logicalType", "string")

        empty = [i for i, v in enumerate(values) if v is None or v.strip() == ""]
        if prop.get("required") and empty:
            res.error(f"{name}: {len(empty)} порожніх значень у обов'язковому полі")
        present = [v for v in values if v is not None and v.strip() != ""]

        if prop.get("unique"):
            dup = len(present) - len(set(present))
            if dup:
                res.error(f"{name}: {dup} дублікатів у полі з обмеженням unique")

        if ltype in ("number", "integer"):
            bad, nums = [], []
            for v in present:
                try:
                    nums.append(float(v))
                except ValueError:
                    bad.append(v)
            if bad:
                res.error(f"{name}: {len(bad)} значень не є числом, напр. {bad[:k]}")
            lo, hi = opts.get("minimum"), opts.get("maximum")
            if lo is not None:
                n = sum(1 for x in nums if x < lo)
                if n:
                    res.error(f"{name}: {n} значень менше мінімуму {lo}")
            if hi is not None:
                n = sum(1 for x in nums if x > hi)
                if n:
                    res.error(f"{name}: {n} значень більше максимуму {hi}")

        if ltype == "date":
            fmt = _py_date_format(opts.get("format", "yyyy-MM-dd"))
            bad = []
            for v in present:
                try:
                    datetime.strptime(v, fmt)
                except ValueError:
                    bad.append(v)
            if bad:
                res.error(f"{name}: {len(bad)} значень не відповідають формату дати "
                          f"{opts.get('format')}, напр. {bad[:k]}")

        if "pattern" in opts:
            rx = re.compile(opts["pattern"])
            bad = [v for v in present if not rx.fullmatch(v)]
            if bad:
                res.error(f"{name}: {len(bad)} значень не відповідають шаблону {opts['pattern']}, "
                          f"напр. {bad[:k]}")

        for q in prop.get("quality", []) or []:
            if q.get("rule") == "validValues":
                allowed = set(map(str, q["validValues"]))
                bad = sorted({v for v in present if v not in allowed})
                if bad:
                    res.error(f"{name}: недопустимі значення {bad[:k]}, дозволено {sorted(allowed)}")
