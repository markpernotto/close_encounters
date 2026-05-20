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
    diameter_km: float | None = None
    diameter_estimate_km: float | None = None
    absolute_magnitude_h: float | None = None
    orbit_class: str | None = None
    # Phase 2 mart additions
    apparent_mag_estimate: float | None = None
    visibility_bucket: str | None = None
    neo: bool | None = None
    pha: bool | None = None


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


# Phase 2 — orbit-revision history


class OrbitRevisionItem(BaseModel):
    solution_date: date
    epoch: float | None = None
    eccentricity: float | None = None
    semi_major_axis_au: float | None = None
    inclination_deg: float | None = None
    sigma_e: float | None = None
    sigma_a: float | None = None
    sigma_i: float | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    is_current: bool


class OrbitHistoryResponse(BaseModel):
    spkid: str
    designation: str
    count: int
    revisions: list[OrbitRevisionItem]


# Phase 2 — cross-agency risk


class AgencyRisk(BaseModel):
    torino_scale: int | None = None
    palermo_scale: float | None = None
    palermo_scale_max: float | None = None
    impact_probability: float | None = None
    n_impacts: int | None = None


class RiskAssessmentItem(BaseModel):
    designation: str
    assessment_date: date
    coverage: str
    nasa: AgencyRisk | None = None
    esa: AgencyRisk | None = None
    delta_palermo: float | None = None
    abs_delta_palermo: float | None = None
    diameter_km: float | None = None
    v_inf_km_s: float | None = None
    potential_impact_year_min: int | None = None
    potential_impact_year_max: int | None = None


class RiskOverviewResponse(BaseModel):
    assessment_date: date | None
    total: int
    coverage: dict[str, int] = Field(default_factory=dict)
    elevated_torino: int
    highest_palermo: RiskAssessmentItem | None = None
