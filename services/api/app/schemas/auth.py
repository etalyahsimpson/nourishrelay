"""Auth and organization schemas."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import EmailStr, Field

from .common import ApiModel, StrictBaseModel


class LoginRequest(StrictBaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserSummary(ApiModel):
    id: str
    role: str
    organization_id: Optional[str] = None
    display_name: str
    email: str


class LoginResponse(ApiModel):
    user: UserSummary


class MeResponse(ApiModel):
    user: UserSummary


class OrganizationSummary(ApiModel):
    id: str
    name: str
    kind: str
    verified: bool
    service_area: Optional[str] = None
    created_at: datetime


class OrganizationListResponse(ApiModel):
    items: List[OrganizationSummary]
    total: int


class RecipientCapacitySummary(ApiModel):
    date: str
    max_kg_per_day: Optional[str] = None
    committed_kg: str
    remaining_kg: Optional[str] = None
    capacity_status: str  # OK | EXHAUSTED | UNKNOWN


class RecipientProfileSummary(ApiModel):
    organization_id: str
    name: str
    verified: bool
    active: bool
    accepted_categories: List[str]
    handling_acknowledged: List[str]
    receiving_start: str  # "HH:MM"
    receiving_end: str
    timezone: str
    service_area: Optional[str] = None
    capacity: RecipientCapacitySummary


class RecipientListResponse(ApiModel):
    items: List[RecipientProfileSummary]
    total: int
    as_of: datetime
