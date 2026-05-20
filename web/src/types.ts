// TypeScript mirrors of api/models.py.

export interface HealthResponse {
  status: string;
  version: string;
  latest_snapshot_date: string | null;
}

export interface ApproachItem {
  spkid: string;
  designation: string;
  full_name: string | null;
  approach_date: string;
  body: string;
  distance_au: number;
  distance_ld: number | null;
  distance_min_au: number | null;
  distance_max_au: number | null;
  v_rel_km_s: number | null;
  v_inf_km_s: number | null;
  orbit_id: string | null;
  diameter_km: number | null;
  diameter_estimate_km: number | null;
  absolute_magnitude_h: number | null;
  orbit_class: string | null;
  // Phase 2 mart additions
  apparent_mag_estimate: number | null;
  visibility_bucket: VisibilityBucket | null;
  neo: boolean | null;
  pha: boolean | null;
}

export type VisibilityBucket =
  | 'naked_eye'
  | 'binoculars'
  | 'small_telescope'
  | 'large_telescope'
  | 'unknown';

export interface ApproachListResponse {
  count: number;
  window_days: number;
  snapshot_date: string | null;
  items: ApproachItem[];
}

export interface ObjectDetail {
  spkid: string;
  designation: string;
  full_name: string | null;
  neo: boolean | null;
  pha: boolean | null;
  orbit_class: string | null;
  absolute_magnitude_h: number | null;
  diameter_km: number | null;
  diameter_estimate_km: number | null;
  albedo: number | null;
  rotation_period_h: number | null;
  spec_class: string | null;
  first_observed: string | null;
  last_observed: string | null;
  observation_arc_days: number | null;
  n_observations: number | null;
  solution_date: string;
  snapshot_date: string;
}

export interface AlertItem {
  alert_id: number;
  fired_at: string;
  rule_id: string;
  spkid: string;
  designation: string | null;
  approach_date: string;
  rationale: string;
  payload: Record<string, unknown>;
}

export interface AlertListResponse {
  count: number;
  items: AlertItem[];
}

// Phase 2 — orbit-revision history

export interface OrbitRevisionItem {
  solution_date: string;
  epoch: number | null;
  eccentricity: number | null;
  semi_major_axis_au: number | null;
  inclination_deg: number | null;
  sigma_e: number | null;
  sigma_a: number | null;
  sigma_i: number | null;
  valid_from: string | null;
  valid_to: string | null;
  is_current: boolean;
}

export interface OrbitHistoryResponse {
  spkid: string;
  designation: string;
  count: number;
  revisions: OrbitRevisionItem[];
}

// Phase 2 — cross-agency risk

export interface AgencyRisk {
  torino_scale: number | null;
  palermo_scale: number | null;
  palermo_scale_max: number | null;
  impact_probability: number | null;
  n_impacts: number | null;
}

export interface RiskAssessmentItem {
  designation: string;
  assessment_date: string;
  coverage: 'both' | 'NASA only' | 'ESA only';
  nasa: AgencyRisk | null;
  esa: AgencyRisk | null;
  delta_palermo: number | null;
  abs_delta_palermo: number | null;
  diameter_km: number | null;
  v_inf_km_s: number | null;
  potential_impact_year_min: number | null;
  potential_impact_year_max: number | null;
}

export interface RiskOverviewResponse {
  assessment_date: string | null;
  total: number;
  coverage: Record<string, number>;
  elevated_torino: number;
  highest_palermo: RiskAssessmentItem | null;
}
