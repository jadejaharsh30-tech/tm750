"""Request models and the filter-DSL -> SQL compiler.

Security model: the field whitelist comes from the catalog, operators come
from a fixed enum, and every value is bound as a parameter. No user-supplied
string is ever interpolated into SQL. An unknown field is a 422, not a query.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .db import numeric_fields, screenable_fields, valid_fields

Op = Literal["eq", "ne", "gt", "gte", "lt", "lte", "between", "in", "not_in",
             "contains", "is_null", "not_null"]

# Operators that require numeric fields, and how many values each expects.
_ARITY: dict[str, int | None] = {
    "eq": 1, "ne": 1, "gt": 1, "gte": 1, "lt": 1, "lte": 1,
    "between": 2, "in": None, "not_in": None, "contains": 1,
    "is_null": 0, "not_null": 0,
}
_SQL_OP = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


class Filter(BaseModel):
    field: str
    op: Op
    value: Any = None

    @field_validator("field")
    @classmethod
    def _known_field(cls, v: str) -> str:
        if v not in valid_fields():
            raise ValueError(f"unknown field '{v}'")
        return v

    @model_validator(mode="after")
    def _check_arity(self):
        want = _ARITY[self.op]
        if want == 0:
            return self
        if want is None:
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(f"op '{self.op}' needs a non-empty list")
            return self
        if want == 2:
            if not isinstance(self.value, (list, tuple)) or len(self.value) != 2:
                raise ValueError("op 'between' needs exactly two values")
            return self
        if isinstance(self.value, list):
            raise ValueError(f"op '{self.op}' needs a single value")
        if self.value is None:
            raise ValueError(f"op '{self.op}' needs a value")
        return self


class Sort(BaseModel):
    field: str
    dir: Literal["asc", "desc"] = "desc"

    @field_validator("field")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in valid_fields():
            raise ValueError(f"unknown sort field '{v}'")
        return v


DEFAULT_COLUMNS = [
    "symbol", "name", "sector", "cap_tier", "market_cap", "price",
    "chg_1d_pct", "perf_1y_pct", "pe_ratio", "roe", "dividend_yield",
    "dist_52w_high_pct", "rsi_14", "technical_rating", "analyst_rating",
]


class ScreenRequest(BaseModel):
    filters: list[Filter] = Field(default_factory=list)
    sort: list[Sort] = Field(default_factory=list)
    columns: list[str] | None = None
    limit: int = Field(100, ge=1, le=750)
    offset: int = Field(0, ge=0)
    include_total: bool = True
    mask_finance: bool = True

    @field_validator("columns")
    @classmethod
    def _known_columns(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        unknown = [c for c in v if c not in valid_fields()]
        if unknown:
            raise ValueError(f"unknown columns: {unknown}")
        return v


class CompareRequest(BaseModel):
    symbols: list[str] = Field(min_length=2, max_length=6)
    segments: list[str] | None = None


# ------------------------------------------------------------- compiler
def build_where(filters: list[Filter]) -> tuple[str, list[Any]]:
    """Compile filters to a parameterised WHERE clause.

    Field names are safe because they are whitelist-checked above; values are
    always bound, never formatted in.
    """
    if not filters:
        return "", []
    clauses: list[str] = []
    params: list[Any] = []

    for f in filters:
        col = f'"{f.field}"'
        if f.op == "is_null":
            clauses.append(f"{col} IS NULL")
        elif f.op == "not_null":
            clauses.append(f"{col} IS NOT NULL")
        elif f.op == "between":
            clauses.append(f"{col} BETWEEN ? AND ?")
            params.extend([f.value[0], f.value[1]])
        elif f.op in ("in", "not_in"):
            marks = ", ".join("?" * len(f.value))
            neg = "NOT " if f.op == "not_in" else ""
            clauses.append(f"{col} {neg}IN ({marks})")
            params.extend(f.value)
        elif f.op == "contains":
            clauses.append(f"lower(CAST({col} AS VARCHAR)) LIKE ?")
            params.append(f"%{str(f.value).lower()}%")
        else:
            clauses.append(f"{col} {_SQL_OP[f.op]} ?")
            params.append(f.value)

    return "WHERE " + " AND ".join(clauses), params


def build_order(sort: list[Sort]) -> str:
    if not sort:
        return 'ORDER BY "market_cap" DESC'
    parts = [f'"{s.field}" {s.dir.upper()} NULLS LAST' for s in sort]
    return "ORDER BY " + ", ".join(parts)


def build_select(columns: list[str] | None) -> str:
    cols = columns or DEFAULT_COLUMNS
    # sector is required for the finance mask to work
    if "sector" not in cols:
        cols = cols + ["sector"]
    return ", ".join(f'"{c}"' for c in cols)
