// Thin typed fetchers for the FastAPI endpoints. Same-origin in production
// via vercel.json rewrites; vite proxies /api/* in dev.

import type {
  AlertListResponse,
  ApproachListResponse,
  ConstellationData,
  HealthResponse,
  ObjectDetail,
  OrbitHistoryResponse,
  PublicationsResponse,
  RiskAssessmentItem,
  RiskOverviewResponse,
  SkyResponse,
  SkyTrackResponse,
  StarCatalog,
} from './types';

async function jsonOrThrow<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = '';
    try {
      const body = await resp.json();
      detail = body?.detail ?? '';
    } catch {
      // ignore non-JSON body
    }
    throw new ApiError(resp.status, detail || resp.statusText);
  }
  return (await resp.json()) as T;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return fetch('/health', { signal }).then(jsonOrThrow<HealthResponse>);
}

export function fetchUpcomingApproaches(
  params: { days?: number; limit?: number } = {},
  signal?: AbortSignal,
): Promise<ApproachListResponse> {
  const qs = new URLSearchParams();
  if (params.days) qs.set('days', String(params.days));
  if (params.limit) qs.set('limit', String(params.limit));
  return fetch(`/api/approaches/upcoming?${qs}`, { signal }).then(
    jsonOrThrow<ApproachListResponse>,
  );
}

export function fetchRecentApproaches(
  params: { days?: number; limit?: number } = {},
  signal?: AbortSignal,
): Promise<ApproachListResponse> {
  const qs = new URLSearchParams();
  if (params.days) qs.set('days', String(params.days));
  if (params.limit) qs.set('limit', String(params.limit));
  return fetch(`/api/approaches/recent?${qs}`, { signal }).then(
    jsonOrThrow<ApproachListResponse>,
  );
}

export function fetchObject(designation: string, signal?: AbortSignal): Promise<ObjectDetail> {
  return fetch(`/api/objects/${encodeURIComponent(designation)}`, { signal }).then(
    jsonOrThrow<ObjectDetail>,
  );
}

export function fetchObjectApproaches(
  designation: string,
  signal?: AbortSignal,
): Promise<ApproachListResponse> {
  return fetch(`/api/objects/${encodeURIComponent(designation)}/approaches`, { signal }).then(
    jsonOrThrow<ApproachListResponse>,
  );
}

export function fetchAlerts(
  params: { limit?: number; rule_id?: string } = {},
  signal?: AbortSignal,
): Promise<AlertListResponse> {
  const qs = new URLSearchParams();
  if (params.limit) qs.set('limit', String(params.limit));
  if (params.rule_id) qs.set('rule_id', params.rule_id);
  return fetch(`/api/alerts?${qs}`, { signal }).then(jsonOrThrow<AlertListResponse>);
}

export function fetchOrbitHistory(
  designation: string,
  signal?: AbortSignal,
): Promise<OrbitHistoryResponse> {
  return fetch(
    `/api/objects/${encodeURIComponent(designation)}/orbit-history`,
    { signal },
  ).then(jsonOrThrow<OrbitHistoryResponse>);
}

export function fetchRiskOverview(
  signal?: AbortSignal,
): Promise<RiskOverviewResponse> {
  return fetch('/api/risk', { signal }).then(jsonOrThrow<RiskOverviewResponse>);
}

export function fetchRiskForObject(
  designation: string,
  signal?: AbortSignal,
): Promise<RiskAssessmentItem> {
  return fetch(`/api/risk/${encodeURIComponent(designation)}`, { signal }).then(
    jsonOrThrow<RiskAssessmentItem>,
  );
}

export function fetchObjectPublications(
  designation: string,
  signal?: AbortSignal,
): Promise<PublicationsResponse> {
  return fetch(
    `/api/objects/${encodeURIComponent(designation)}/publications`,
    { signal },
  ).then(jsonOrThrow<PublicationsResponse>);
}

export function fetchSky(
  params: { lat: number; lon: number; time?: string; minAltitude?: number },
  signal?: AbortSignal,
): Promise<SkyResponse> {
  const qs = new URLSearchParams({
    lat: String(params.lat),
    lon: String(params.lon),
  });
  if (params.time) qs.set('time', params.time);
  if (params.minAltitude != null) qs.set('min_altitude', String(params.minAltitude));
  return fetch(`/api/sky?${qs}`, { signal }).then(jsonOrThrow<SkyResponse>);
}

export function fetchSkyTrack(
  params: {
    lat: number;
    lon: number;
    start?: string;
    end?: string;
    stepMinutes?: number;
    minAltitude?: number;
  },
  signal?: AbortSignal,
): Promise<SkyTrackResponse> {
  const qs = new URLSearchParams({
    lat: String(params.lat),
    lon: String(params.lon),
  });
  if (params.start) qs.set('start', params.start);
  if (params.end) qs.set('end', params.end);
  if (params.stepMinutes != null) qs.set('step_minutes', String(params.stepMinutes));
  if (params.minAltitude != null) qs.set('min_altitude', String(params.minAltitude));
  return fetch(`/api/sky/track?${qs}`, { signal }).then(jsonOrThrow<SkyTrackResponse>);
}

// Static catalogs served from web/public/skydata/ (not the API).

export function fetchStarCatalog(signal?: AbortSignal): Promise<StarCatalog> {
  return fetch('/skydata/stars.json', { signal }).then(jsonOrThrow<StarCatalog>);
}

export function fetchConstellations(signal?: AbortSignal): Promise<ConstellationData> {
  return fetch('/skydata/constellations.json', { signal }).then(
    jsonOrThrow<ConstellationData>,
  );
}
