"""Pydantic contracts shared by schema modules.

Conventions (spec §4.1):
- snake_case JSON, UUID identifiers as strings.
- UTC RFC3339 timestamps; half-open [start, end) windows.
- Quantities are kilograms, decimal with up to three fraction digits,
  transported as strings ("120.000") to preserve exact decimal form.
"""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Any, List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

QUANTUM = Decimal("0.001")
MAX_QUANTITY = Decimal("999999999.999")  # NUMERIC(12,3) ceiling

CATEGORY_VALUES = ("produce", "baked", "dairy", "canned", "prepared")
HANDLING_TAG_MAX = 8
HANDLING_TAG_LEN = 40
MAX_TEXT = 2000
MAX_PAGE = 100


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


def to_dec_str(value: Decimal | str | float | None) -> str | None:
    """Render a quantity as its canonical 3-decimal string form."""
    if value is None:
        return None
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return str(d.quantize(QUANTUM, rounding=ROUND_HALF_UP))


def validate_quantity(value: Decimal) -> Decimal:
    """Reject non-finite, non-positive or out-of-range quantities."""
    if value is None or not value.is_finite():
        raise ValueError("quantity must be a finite decimal number")
    if value <= 0:
        raise ValueError("quantity must be greater than zero")
    if value > MAX_QUANTITY:
        raise ValueError("quantity exceeds the maximum supported amount")
    return value


QuantityKg = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)]

OptionalQuantityKg = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=3)]


def validate_future_not_past(value: datetime) -> datetime:
    return value


class Page(ApiModel):
    """Consistent pagination envelope."""
    items: List[Any]
    total: int
    limit: int
    offset: int


def normalize_tags(tags: List[str] | None) -> List[str]:
    """Normalize declared handling tags: lowercase, deduped, bounded."""
    if tags is None:
        return []
    seen: list[str] = []
    for raw in tags:
        t = (raw or "").strip().lower()
        if not t:
            continue
        if len(t) > HANDLING_TAG_LEN:
            raise ValueError("handling tag too long")
        if t not in seen:
            seen.append(t)
    if len(seen) > HANDLING_TAG_MAX:
        raise ValueError("too many handling tags")
    return seen


class StrictBaseModel(ApiModel):
    """Base model rejecting unknown fields (strict contracts)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def ensure_finite_decimal(value: Any) -> Decimal:
    """Coerce to Decimal and guarantee finiteness (no NaN/Inf)."""
    from decimal import InvalidOperation

    try:
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("non-finite quantity")
            return Decimal(str(value))
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("non-finite quantity")
            return value
        if isinstance(value, str):
            d = Decimal(value.strip())
            if not d.is_finite():
                raise ValueError("non-finite quantity")
            return d
        if isinstance(value, int):
            return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("quantity must be a number") from exc
    raise ValueError("quantity must be a number")
