"""Reservation, pickup and receipt schemas."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import Field, field_validator

from .common import ApiModel, StrictBaseModel, ensure_finite_decimal, validate_quantity


class ReservationCreate(StrictBaseModel):
    donation_id: str = Field(min_length=36, max_length=36)
    recipient_org_id: str = Field(min_length=36, max_length=36)
    quantity_kg: float | str
    proposal_expires_at: Optional[datetime] = None

    @field_validator("quantity_kg")
    @classmethod
    def _valid_quantity(cls, v) -> str:
        d = ensure_finite_decimal(v)
        validate_quantity(d)
        return str(d)


class AcceptReservationRequest(StrictBaseModel):
    accepted: bool = False

    @field_validator("accepted")
    @classmethod
    def _must_accept(cls, v: bool) -> bool:
        if not v:
            raise ValueError("use /decline to reject a proposal")
        return v


class DeclineReservationRequest(StrictBaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class CancelReservationRequest(StrictBaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class ReservationSummary(ApiModel):
    id: str
    donation_id: str
    donation_category: str
    donation_status: str
    donor_org_id: str
    donor_org_name: str
    recipient_org_id: str
    recipient_org_name: str
    proposed_by: str
    quantity_kg: str
    state: str
    failure_stage: Optional[str] = None
    proposal_expires_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    released_at: Optional[datetime] = None
    decline_reason: Optional[str] = None
    cancel_reason: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    pickup_start: datetime
    pickup_end: datetime
    deadline: datetime
    donation_available_kg: Optional[str] = None
    allowed_actions: List[str]


class ReservationListResponse(ApiModel):
    items: List[ReservationSummary]
    total: int
    limit: int
    offset: int


class PickupCreate(StrictBaseModel):
    reservation_id: str = Field(min_length=36, max_length=36)
    assigned_transport_org_id: Optional[str] = Field(default=None, min_length=36, max_length=36)
    pickup_window_start: datetime
    pickup_window_end: datetime


class PickupEventCreate(StrictBaseModel):
    event_type: str  # COLLECTED | DELIVERED | FAILED
    occurred_at: Optional[datetime] = None
    quantity_kg: Optional[float | str] = None
    reason: Optional[str] = Field(default=None, max_length=500)

    @field_validator("event_type")
    @classmethod
    def _valid_event(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in {"COLLECTED", "DELIVERED", "FAILED"}:
            raise ValueError("event_type must be COLLECTED, DELIVERED or FAILED")
        return v

    @field_validator("quantity_kg")
    @classmethod
    def _valid_quantity(cls, v) -> Optional[str]:
        if v is None:
            return None
        d = ensure_finite_decimal(v)
        validate_quantity(d)
        return str(d)


class ReceiptCreate(StrictBaseModel):
    received_quantity_kg: float | str
    exception_reason: Optional[str] = Field(default=None, max_length=500)

    @field_validator("received_quantity_kg")
    @classmethod
    def _valid_quantity(cls, v) -> str:
        d = ensure_finite_decimal(v)
        if d < 0:
            raise ValueError("received quantity cannot be negative")
        return str(d)


class ReceiptSummary(ApiModel):
    id: str
    pickup_id: str
    recipient_user_id: str
    received_quantity_kg: str
    exception_reason: Optional[str] = None
    confirmed_at: datetime


class PickupSummary(ApiModel):
    id: str
    reservation_id: str
    reservation_state: str
    assigned_transport_org_id: Optional[str] = None
    assigned_transport_org_name: Optional[str] = None
    recipient_org_id: str
    recipient_org_name: str
    donor_org_name: str
    donation_category: str
    reserved_quantity_kg: str
    pickup_window_start: datetime
    pickup_window_end: datetime
    status: str
    collected_quantity_kg: Optional[str] = None
    collected_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    receipt: Optional[ReceiptSummary] = None
    failure_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    allowed_actions: List[str]


class PickupListResponse(ApiModel):
    items: List[PickupSummary]
    total: int
    limit: int
    offset: int
