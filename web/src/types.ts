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
  diameter_estimate_km: number | null;
  absolute_magnitude_h: number | null;
  orbit_class: string | null;
}

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
