from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable

BASE_COLUMNS = ["order_id", "customer_id", "order_date", "amount", "currency", "status"]

CLASS_COMPATIBLE = "сумісна"
CLASS_BREAKING = "руйнівна структурна"
CLASS_HIDDEN = "прихована (семантична)"

Rows = list[dict[str, str]]


def generate_base_rows(n: int = 200, seed: int = 42) -> Rows:
    rnd = random.Random(seed)
    start = date(2026, 10, 1)
    rows: Rows = []
    for i in range(1, n + 1):
        rows.append(
            {
                "order_id": f"ORD-{i:06d}",
                "customer_id": f"C{rnd.randint(1, 9999):05d}",
                "order_date": (start + timedelta(days=rnd.randint(0, 30))).isoformat(),
                "amount": f"{rnd.uniform(50, 20000):.2f}",
                "currency": rnd.choice(["UAH", "UAH", "UAH", "USD", "EUR"]),
                "status": rnd.choice(["new", "paid", "shipped", "cancelled"]),
            }
        )
    return rows


def base_json_schema() -> dict:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "orders",
        "type": "object",
        "properties": {
            "order_id": {"type": "string"},
            "customer_id": {"type": "string"},
            "order_date": {"type": "string"},
            "amount": {"type": "number"},
            "currency": {"type": "string", "enum": ["UAH", "USD", "EUR"]},
            "status": {"type": "string", "enum": ["new", "paid", "shipped", "cancelled"]},
        },
        "required": list(BASE_COLUMNS),
    }


@dataclass
class Scenario:
    code: str
    title: str
    change_class: str
    mutate_data: Callable[[list[str], Rows], tuple[list[str], Rows]]
    mutate_schema: Callable[[dict], dict] = field(default=lambda s: s)

    @property
    def file_name(self) -> str:
        return f"{self.code}.csv"


def _identity(cols, rows):
    return cols, rows


def _add_column(cols, rows):
    for r in rows:
        r["discount"] = "0.00"
    return cols + ["discount"], rows


def _rename(old: str, new: str):
    def f(cols, rows):
        for r in rows:
            r[new] = r.pop(old)
        return [new if c == old else c for c in cols], rows
    return f


def _drop(col: str):
    def f(cols, rows):
        for r in rows:
            r.pop(col)
        return [c for c in cols if c != col], rows
    return f


def _amount_as_localized_string(cols, rows):
    for r in rows:
        whole, frac = r["amount"].split(".")
        whole = f"{int(whole):,}".replace(",", " ")
        r["amount"] = f"{whole},{frac} грн"
    return cols, rows


def _reorder(cols, rows):
    return list(reversed(cols)), rows


def _nulls_in(col: str, share: float = 0.1):
    def f(cols, rows):
        step = int(1 / share)
        for i, r in enumerate(rows):
            if i % step == 0:
                r[col] = ""
        return cols, rows
    return f


def _duplicate_ids(cols, rows):
    for i in range(0, 20):
        rows[i + 20]["order_id"] = rows[i]["order_id"]
    return cols, rows


def _amount_in_kopecks(cols, rows):
    for r in rows:
        r["amount"] = str(int(round(float(r["amount"]) * 100)))
    return cols, rows


def _date_ddmmyyyy(cols, rows):
    for r in rows:
        y, m, d = r["order_date"].split("-")
        r["order_date"] = f"{d}.{m}.{y}"
    return cols, rows


def _new_status(cols, rows):
    for i, r in enumerate(rows):
        if i % 10 == 0:
            r["status"] = "refunded"
    return cols, rows


def _header_only(cols, rows):
    return cols, []


def _s_add_optional(s):
    s = copy.deepcopy(s)
    s["properties"]["discount"] = {"type": "number"}
    return s


def _s_rename(old, new):
    def f(s):
        s = copy.deepcopy(s)
        s["properties"][new] = s["properties"].pop(old)
        s["required"] = [new if c == old else c for c in s["required"]]
        return s
    return f


def _s_drop(col):
    def f(s):
        s = copy.deepcopy(s)
        s["properties"].pop(col)
        s["required"] = [c for c in s["required"] if c != col]
        return s
    return f


def _s_amount_string(s):
    s = copy.deepcopy(s)
    s["properties"]["amount"] = {"type": "string"}
    return s


def _s_new_status(s):
    s = copy.deepcopy(s)
    s["properties"]["status"]["enum"].append("refunded")
    return s


SCENARIOS: list[Scenario] = [
    Scenario("S00_baseline", "Еталонні дані без змін", "—", _identity),
    Scenario("S01_add_column", "Додано необов'язкове поле discount", CLASS_COMPATIBLE,
             _add_column, _s_add_optional),
    Scenario("S02_rename_column", "Поле amount перейменовано на total_amount", CLASS_BREAKING,
             _rename("amount", "total_amount"), _s_rename("amount", "total_amount")),
    Scenario("S03_drop_column", "Видалено обов'язкове поле customer_id", CLASS_BREAKING,
             _drop("customer_id"), _s_drop("customer_id")),
    Scenario("S04_type_change", "Тип amount змінено з числа на рядок", CLASS_BREAKING,
             _amount_as_localized_string, _s_amount_string),
    Scenario("S05_reorder_columns", "Змінено порядок стовпців", CLASS_COMPATIBLE, _reorder),
    Scenario("S06_nulls_required", "Порожні значення в customer_id (10%)", CLASS_HIDDEN,
             _nulls_in("customer_id")),
    Scenario("S07_duplicate_keys", "Дублікати order_id (20 рядків)", CLASS_HIDDEN, _duplicate_ids),
    Scenario("S08_unit_change", "Суми в копійках замість гривень", CLASS_HIDDEN, _amount_in_kopecks),
    Scenario("S09_date_format", "Формат дати ДД.ММ.РРРР замість ISO 8601", CLASS_HIDDEN, _date_ddmmyyyy),
    Scenario("S10_new_enum_value", "Новий статус refunded", CLASS_HIDDEN, _new_status, _s_new_status),
    Scenario("S11_case_change", "Поле amount перейменовано на Amount", CLASS_BREAKING,
             _rename("amount", "Amount"), _s_rename("amount", "Amount")),
    Scenario("S12_empty_file", "Файл містить лише заголовок", CLASS_HIDDEN, _header_only),
]


def build_scenario(sc: Scenario, base_rows: Rows) -> tuple[list[str], Rows]:
    return sc.mutate_data(list(BASE_COLUMNS), copy.deepcopy(base_rows))


def get(code: str) -> Scenario:
    for sc in SCENARIOS:
        if sc.code == code:
            return sc
    raise KeyError(code)
