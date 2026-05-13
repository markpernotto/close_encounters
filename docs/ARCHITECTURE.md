# Architecture

This document describes how `close_encounters` is structured and why. It
covers the Phase 1 pipeline (close-approach watcher); Phase 2 (risk
warehouse + dbt) and Phase 3 (citation graph) will extend it.

## Overview

A nightly batch pipeline pulls NASA JPL's close-approach feed (CNEOS) and
small-body catalog (SBDB), snapshots the raw JSON to Cloudflare R2 with
provenance, normalizes it into a Postgres schema, computes a stream of
typed change events against the previous snapshot, evaluates threshold
rules to produce public alerts, and regenerates the public RSS + JSON
feeds.

The design favors **batch over streaming** and **snapshot-and-diff over
change-data-capture**. The upstream sources update on a daily-to-weekly
cadence; a sub-hourly pipeline would be no fresher than the inputs. The
trade-off accepted: latency from source change to public feed is bounded
by the cron frequency (currently nightly at 06:30 UTC), capped at a
26-hour freshness SLO.

## Stack

| Concern | Choice |
|---|---|
| Language | Python 3.12 |
| Warehouse | Postgres 16 (Neon free tier) |
| Object storage | Cloudflare R2 (S3-compatible) |
| Orchestration | GitHub Actions cron |
| Transform (Phase 2) | dbt Core (dbt-postgres) |
| API | FastAPI |
| Frontend | Vite + React + TypeScript |
| Hosting | Vercel (web + API as serverless functions) |
| HTTP | httpx + tenacity (retries) |
| Test runner | pytest |

Not used: Kubernetes, Spark, Kafka, cloud data warehouses. The volumes
involved (thousands of rows per night, millions cumulative) fit
comfortably in a free Neon tier without any of those.

## Pipeline stages

```
JPL CNEOS Close-Approach API ─┐
JPL SBDB Lookup API ──────────┼─► GitHub Actions cron (06:30 UTC daily)
                              │
                              ▼
  etl.extract  ─► pulls CNEOS for next 60 days
               ─► looks up each unique designation in SBDB (rate-limited)
               ─► uploads each raw payload to R2 (provenance: sha256 + bytes)
               ─► normalizes rows via etl.transform
               ─► UPSERTs into objects_snapshots, orbit_elements_snapshots,
                  close_approaches_snapshots via etl.load
               ─► appends/replaces today's line in data/MANIFEST.jsonl

  etl.diff     ─► fetches the two latest snapshots from Postgres
               ─► emits NEW_OBJECT / NEW_APPROACH / REVISED_APPROACH events
               ─► UPSERTs into approach_events (idempotent on dedup_key)

  etl.alerts   ─► reads the latest snapshot's events + context
               ─► evaluates threshold rules (see docs/ALERT_RULES.md)
               ─► UPSERTs into alerts (idempotent on dedup_key, append-only)

  etl.publish  ─► reads upcoming approaches from Postgres
               ─► reads recent alerts from Postgres
               ─► writes public/{upcoming,noteworthy}.{rss,json}
               ─► writes public/health.json
               ─► nightly workflow commits public/ + MANIFEST.jsonl back to main

  Vercel       ─► rebuilds the static site on each commit to main
               ─► serves the React UI + the FastAPI /api/* endpoints
                  via serverless functions
```

Each stage is independently runnable from the `Makefile`. CI executes
`make pipeline` which chains them in order.

## Snapshot + diff design

Why snapshot the whole window each night instead of incrementally
tracking changes via CDC or a webhook?

1. **The sources do not push.** CNEOS and SBDB are pull-only HTTP APIs.
   There is no upstream change notification to subscribe to.
2. **Their update cadence is unknown.** JPL revises orbit determinations
   whenever new observations arrive. There is no published "object X has
   been updated" feed; the only way to know is to compare.
3. **Snapshots give us auditable history for free.** Every night's full
   pull is archived to R2 with a checksum. If JPL changes a row, we can
   reconstruct exactly what they said before and after.

The diff layer turns the snapshot stream into the equivalent of a
change-data-capture log — but driven by what we observed, not by an
upstream notification.

## Idempotency model

The pipeline can be re-run safely after partial or full failure without
producing duplicates. Idempotency holds at four layers:

| Layer | Mechanism |
|---|---|
| R2 uploads | Keys are deterministic (`snapshots/YYYY-MM-DD/cneos.json`, `…/sbdb/<spkid>.json`). Re-uploads overwrite the same key with identical bytes. |
| Postgres raw landing | All four tables (`objects_snapshots`, `orbit_elements_snapshots`, `close_approaches_snapshots`, `approach_events`) use `INSERT … ON CONFLICT (pk) DO UPDATE`. |
| Events | `approach_events.dedup_key` = sha256 of `(event_type, spkid, approach_date, canonical-json(new_value))`. Re-running `etl.diff` against the same snapshot pair produces identical keys; the loader skips on conflict. |
| Alerts | `alerts.dedup_key` = sha256 of `(rule_id, event_dedup_key)`. Re-running `etl.alerts` against the same events produces identical alerts; the loader skips on conflict. |

Manifest writes are also idempotent: `etl.extract.merge_manifest` replaces
the existing line for today's `snapshot_date` rather than appending,
preserving order otherwise.

The composite consequence: if the nightly workflow re-runs (manually
triggered, or after a failure-and-retry), the only diff in the committed
output is `lastBuildDate` in the RSS feeds — and even that can be made
stable by passing an explicit `generated_at`.

## Failure modes and recovery

| Failure | Behavior | Recovery |
|---|---|---|
| CNEOS API down | `etl.extract` raises on the first request after three retries | Re-run the next night; data flows once the API recovers |
| SBDB lookup fails for one designation | Recorded in `manifest_entry.sbdb_errors`; that designation's approach row gets `spkid=None` and is skipped by `load.load_close_approaches`; pipeline continues | Next night re-tries the lookup |
| R2 down mid-run | Whichever uploads succeeded keep their bytes; DB writes haven't started; manifest not yet written | Re-run — R2 keys are deterministic, so successful uploads overwrite identically |
| DB write fails mid-transaction | All-or-nothing per transaction; manifest not written | Re-run; UPSERTs converge |
| Diff finds only one snapshot | Returns 0 events, no error | First run on a fresh DB always produces 0 events |
| Alert rule produces unexpected output | Append-only: corrections are appended as new alerts; prior alerts are never deleted | See [ALERT_RULES.md](ALERT_RULES.md) for the false-alarm policy |
| Workflow itself fails | GitHub Action opens a labeled issue with a link to the failed run | Investigate logs, fix, re-trigger via `workflow_dispatch` |

## Schema overview

Phase 1 ships five tables. Three are raw landing tables receiving normalized
source rows; two are derived.

| Table | Grain | Purpose |
|---|---|---|
| `objects_snapshots` | `(snapshot_date, spkid)` | Physical + orbital metadata per nightly snapshot. Includes derived diameter estimate, observation arc, solution date. |
| `orbit_elements_snapshots` | `(spkid, solution_date)` | Every distinct orbit determination, keyed independently of when we observed it. Phase 2 SCD-2 modeling draws from here. |
| `close_approaches_snapshots` | `(snapshot_date, spkid, approach_date, body)` | CNEOS close-approach predictions, snapshotted nightly. Includes `orbit_id` for revision detection. |
| `approach_events` | `event_id BIGSERIAL`, plus `dedup_key UNIQUE` | Derived event stream from `etl.diff`. NEW_OBJECT, NEW_APPROACH, REVISED_APPROACH. |
| `alerts` | `alert_id BIGSERIAL`, plus `dedup_key UNIQUE` | Threshold-rule matches against `approach_events`. Append-only by policy. |

Every raw landing row carries provenance: `source_url`,
`source_retrieved_at`, `source_checksum` (sha256 of the source row), and
`extraction_version` (the ETL code version that produced the row).

## Provenance and reproducibility

Three artifacts together let any past pipeline run be reconstructed:

1. **`data/MANIFEST.jsonl`** — one line per snapshot date, listing every
   raw payload uploaded (CNEOS plus one SBDB record per object) with
   sha256 and byte counts.
2. **Cloudflare R2** — the raw payloads themselves, keyed by date and
   spkid.
3. **Postgres `*_snapshots` tables** — the normalized rows, each carrying
   `raw_row` (the original source row as JSONB) plus the provenance
   columns named above.

Given any past `snapshot_date`, you can fetch the raw R2 payloads, verify
their sha256s against the manifest, and replay normalization to confirm
the database state.

## Deployment topology

```
GitHub Actions runner (ubuntu-latest, Python 3.12)
  │  reads secrets: DATABASE_URL, R2_*, USER_AGENT_*, NASA_API_KEY, ADS_API_TOKEN
  │
  ├─► HTTP GET → ssd-api.jpl.nasa.gov  (CNEOS + SBDB)
  │
  ├─► S3 PUT  → <account>.r2.cloudflarestorage.com (R2)
  │
  ├─► Postgres → ep-*.neon.tech                    (Neon)
  │
  └─► git push → github.com/markpernotto/close_encounters (main)
            │
            └─► Vercel webhook → rebuild static site + serverless functions
                  ├─► https://close-encounters.vercel.app/          (React UI)
                  ├─► https://close-encounters.vercel.app/api/…     (FastAPI)
                  ├─► https://close-encounters.vercel.app/upcoming.rss
                  └─► https://close-encounters.vercel.app/noteworthy.rss
```

Everything outside the runner is managed: Neon for Postgres, Cloudflare
for R2, Vercel for hosting. No long-running servers to operate.

## Future phases

- **Phase 2** layers a dbt project under `etl/transform/` that reads the
  raw landing tables and produces marts: `dim_object`, `dim_orbit_revision`
  (SCD-2), `fact_close_approach`, `fact_risk_assessment`, and a
  denormalized `mart_upcoming_approaches` view the API reads directly.
  Adds NASA Sentry and ESA NEOCC sources. See PLAN.md.
- **Phase 3** adds a citation graph: links each NEO to its discovery
  announcement (Minor Planet Center electronic circulars, journal papers
  resolved via NASA ADS or Crossref) with confidence-scored relationships.
  Parallel to the sister project `exoplanet_citation`.
