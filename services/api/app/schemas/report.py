"""Reporting and audit schemas."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ReportRatio(BaseModel):
    label: str
    numerator: str
    denominator: str
    value: Optional[str]  # None ("N/A") when denominator is zero
    unit: str = "kg"


class ExceptionBreakdown(BaseModel):
    kind: str
    count: int
    quantity_kg: Optional[str] = None


class OperationsReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    window_from: datetime
    window_to: datetime
    scope_organization_id: Optional[str] = None
    scope_organization_name: Optional[str] = None
    offered_kg: str
    committed_kg: str
    collected_kg: str
    received_kg: str
    offers: int
    reservations: int
    pickups: int
    failures: int
    cancellations: int
    median_pickup_lead_time_minutes: Optional[float] = None
    ratios: List[ReportRatio]
    cancellation_reasons: List[ExceptionBreakdown]
    failure_reasons: List[ExceptionBreakdown]
    categories: List[dict]
    note: str


class AuditEntry(BaseModel):
    id: str
    actor_id: Optional[str] = None
    actor_display_name: Optional[str] = None
    actor_role: Optional[str] = None
    organization_id: Optional[str] = None
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    outcome: str
    safe_summary: dict
    created_at: datetime


class AuditListResponse(BaseModel):
    items: List[AuditEntry]
    total: int
    limit: int
    offset: int
