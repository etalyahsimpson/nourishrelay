"""Donation, matching and revision schemas."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import Field, field_validator, model_validator

from .common import (
    ApiModel,
    CATEGORY_VALUES,
    StrictBaseModel,
    validate_quantity,
)


class DonationCreate(StrictBaseModel):
    category: str  # validated against CATEGORY_VALUES below
    quantity_kg: float | str  # Decimal accepted as number or exact string
    handling_tags: List[str] = Field(default_factory=list)
    pickup_start: datetime
    pickup_end: datetime
    deadline: datetime
    location_label: str = Field(min_length=1, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in CATEGORY_VALUES:
            raise ValueError(f"category must be one of {list(CATEGORY_VALUES)}")
        return v

    @field_validator("quantity_kg")
    @classmethod
    def _valid_quantity(cls, v) -> float | str:
        from .common import ensure_finite_decimal

        d = ensure_finite_decimal(v)
        validate_quantity(d)
        return str(d)  # keep exact decimal string

    @field_validator("handling_tags")
    @classmethod
    def _normalize_tags(cls, v: List[str]) -> List[str]:
        from .common import normalize_tags

        return normalize_tags(v)

    @model_validator(mode="after")
    def _coherent_window(self) -> "DonationCreate":
        if not (self.pickup_start < self.pickup_end):
            raise ValueError("pickup_start must be before pickup_end (half-open window)")
        if not (self.pickup_start < self.deadline):
            raise ValueError("deadline must be after pickup_start")
        if not (self.deadline <= self.pickup_end):
            raise ValueError("deadline must not be after pickup_end")
        return self


class DonationUpdate(StrictBaseModel):
    """Optimistic-concurrency edit; only pre-commit donations are editable."""

    version: int = Field(ge=1)
    category: Optional[str] = None
    quantity_kg: Optional[float | str] = None
    handling_tags: Optional[List[str]] = None
    pickup_start: Optional[datetime] = None
    pickup_end: Optional[datetime] = None
    deadline: Optional[datetime] = None
    location_label: Optional[str] = Field(default=None, min_length=1, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().lower()
        if v not in CATEGORY_VALUES:
            raise ValueError(f"category must be one of {list(CATEGORY_VALUES)}")
        return v

    @field_validator("quantity_kg")
    @classmethod
    def _valid_quantity(cls, v) -> Optional[str]:
        if v is None:
            return None
        from .common import ensure_finite_decimal

        d = ensure_finite_decimal(v)
        validate_quantity(d)
        return str(d)

    @field_validator("handling_tags")
    @classmethod
    def _normalize_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        from .common import normalize_tags

        if v is None:
            return None
        return normalize_tags(v)


class PublishRequest(StrictBaseModel):
    """Human attestation that the donor completed donor-side handling review."""

    attested: bool  # required: publication without explicit attestation is rejected

    @field_validator("attested")
    @classmethod
    def _must_attest(cls, v: bool) -> bool:
        if not v:
            raise ValueError("publication requires explicit donor handling-review attestation")
        return v


class WithdrawRequest(StrictBaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class DonationRevision(ApiModel):
    version: int
    actor_id: str
    changed_at: datetime
    before: dict
    after: dict


class DonationSummary(ApiModel):
    id: str
    donor_org_id: str
    donor_org_name: str
    category: str
    quantity_kg: str
    available_kg: Optional[str] = None
    committed_kg: Optional[str] = None
    handling_tags: List[str]
    pickup_start: datetime
    pickup_end: datetime
    deadline: datetime
    status: str
    location_label: str
    notes: Optional[str] = None
    version: int
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None


class DonationDetail(DonationSummary):
    revisions: List[DonationRevision]
    reservations: List[dict]
    allowed_actions: List[str]
    available_transitions: List[str]


class DonationListResponse(ApiModel):
    items: List[DonationSummary]
    total: int
    limit: int
    offset: int


class MatchReasonFactor(ApiModel):
    factor: str
    raw: Optional[str] = None  # raw observed value or None when unavailable
    normalized: Optional[float] = None
    known: bool
    weight: float
    contribution: float


class MatchCandidate(ApiModel):
    recipient_id: str
    recipient_name: str
    max_feasible_kg: str
    score: float
    score_breakdown: List[MatchReasonFactor]
    reasons: List[str]
    zero_history: bool


class ExcludedCandidate(ApiModel):
    recipient_id: str
    recipient_name: str
    reasons: List[str]


class MatchListResponse(ApiModel):
    donation_id: str
    available_kg: str
    weights: dict
    eligible: List[MatchCandidate]
    excluded: List[ExcludedCandidate]
    generated_at: datetime
    note: str
