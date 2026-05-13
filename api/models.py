"""Pydantic response models for the public API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    version: str
    latest_snapshot_date: date | None


class ApproachItem(BaseModel):
    spkid: str
    designation: str
    full_name: str | None
    approach_date: datetime
    body: str
    distance_au: float
    distance_ld: float | None
    distance_min_au: float | None = None
    distance_max_au: float | None = None
    v_rel_km_s: float | None
    v_inf_km_s: float | None
    orbit_id: str | None = None
    diameter_estimate_km: float | None = None
    absolute_magnitude_h: float | None = None
    orbit_class: str | None = None


class ApproachListResponse(BaseModel):
    count: int
    window_days: int
    snapshot_date: date | None
    items: list[ApproachItem]


class ObjectDetail(BaseModel):
    spkid: str
    designation: str
    full_name: str | None
    neo: bool | None
    pha: bool | None
    orbit_class: str | None
    absolute_magnitude_h: float | None
    diameter_km: float | None
    diameter_estimate_km: float | None
    albedo: float | None
    rotation_period_h: float | None
    spec_class: str | None
    first_observed: date | None
    last_observed: date | None
    observation_arc_days: int | None
    n_observations: int | None
    solution_date: date
    snapshot_date: date


class AlertItem(BaseModel):
    alert_id: int
    fired_at: datetime
    rule_id: str
    spkid: str
    designation: str | None = None
    approach_date: datetime
    rationale: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AlertListResponse(BaseModel):
    count: int
    items: list[AlertItem]
