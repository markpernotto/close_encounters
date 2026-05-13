# close encounters

A public data warehouse and alerting feed for near-Earth objects: which
asteroids and comets are passing close to Earth, how big they are, how
confident the orbit is, and who saw them first.

> **Status:** Phase 1 in progress, mid-build. The schema, source clients,
> transform, load, and diff layers are written and unit-tested. The
> alerting, publishing, web UI, and the actual nightly run are still
> ahead. Nothing is shipping yet.

## The eventual project

Three phases, each independently shippable, each building on the last.

### Phase 1 — close-approach watcher

A nightly pipeline pulls NASA JPL's CNEOS close-approach feed and the JPL
Small-Body Database (SBDB) and snapshots them into Postgres with full
provenance. A diff job compares each night to the night before and emits
events when the catalog changes: `NEW_OBJECT`, `NEW_APPROACH`,
`REVISED_APPROACH`. Two public RSS feeds — one for everything passing close
in the next 60 days, one for "noteworthy" approaches (e.g. ≥50 m and inside
the lunar distance). A minimal React UI lists upcoming approaches with
distance, velocity, and estimated diameter.

### Phase 2 — risk warehouse and orbit-revision history

NASA Sentry and ESA NEOCC ingested and joined to JPL data, including the
cases where the agencies disagree on risk classification. A dbt mart layer
with SCD-2 modeling tracks every revision of an object's orbit
determination, so the warehouse can answer "what did we think this orbit
looked like last March, vs. what we know now." A historical-comparator
endpoint contextualizes each upcoming approach against the catalog's
history.

### Phase 3 — citation graph

Each NEO linked to the discovery announcement that announced it: an IAU
Minor Planet Center electronic circular (MPEC), a journal paper resolved
via NASA ADS or Crossref, or a survey-program record. Confidence-scored
links, parallel to the citation-graph approach used in the sister project
`exoplanet_citation`.

## What's built so far

The chassis (project layout, dependencies, dev tooling, CI) and the lower
half of the Phase 1 ETL:

- **Schema** — [etl/schema.sql](etl/schema.sql). Four raw landing tables
  (`objects_snapshots`, `orbit_elements_snapshots`,
  `close_approaches_snapshots`, `approach_events`) keyed for idempotent
  re-runs.
- **Source clients** — [etl/sources/jpl_cneos.py](etl/sources/jpl_cneos.py)
  and [etl/sources/jpl_sbdb.py](etl/sources/jpl_sbdb.py). Polite httpx
  clients for the JPL CNEOS Close-Approach API and the SBDB Lookup API,
  with tenacity retries and a User-Agent that identifies the project.
- **Transform** — [etl/transform.py](etl/transform.py). Pure functions that
  map raw API responses into typed row dicts matching the schema. No I/O.
- **Load** — [etl/load.py](etl/load.py). UPSERT writers for each table.
  Designation→spkid resolver for CNEOS rows that lack spkids natively.
  Event inserts deduped on a deterministic hash so re-runs are no-ops.
- **Diff** — [etl/diff.py](etl/diff.py). A pure `compute_events` function
  over two snapshots emits the three event types; the orchestrator fetches
  the two latest snapshots from Postgres, computes events, and writes them.
- **Tests** — [tests/](tests/). 22 unit tests against committed fixtures
  (a real CNEOS day plus an Apophis SBDB record). No network, no DB
  required.
- **Vocabularies** — [vocabularies/](vocabularies/). Controlled YAML for
  orbit class, risk class, event type, alert rule, discovery facility, and
  citation confidence.
- **Chassis** — `pyproject.toml`, `Makefile`, GitHub Actions for CI and
  the nightly cron, `Dockerfile` + `docker-compose.yml`, `vercel.json`,
  a FastAPI app stub with `/health`, and a Vite + React + TS web stub.

## What's coming next

Phase 1, in order:

- `etl/alerts.py` — threshold rules that decide which events become
  noteworthy alerts. The trust-critical part of the project, so it gets
  exhaustive tests.
- `etl/publish.py` — turns events and database rows into RSS feeds and
  JSON endpoints.
- API endpoints for `/api/approaches/upcoming`, `/api/approaches/recent`,
  `/api/objects/{designation}`, etc.
- A real React UI — sortable upcoming-approaches table, per-object detail
  page, "noteworthy only" filter.
- Wiring the nightly GitHub Action to a Neon Postgres + Cloudflare R2
  bucket, then watching it run green for five consecutive nights before
  calling Phase 1 shipped.

Phases 2 and 3 are scoped in [PLAN.md](PLAN.md).

## How it works (under the hood)

The design is **snapshot + diff**, not stateful change-data-capture. Every
night the pipeline:

1. **Snapshots the source.** Pulls the CNEOS close-approach feed for the
   next 60 days and looks up each object in SBDB. Saves the raw JSON to
   Cloudflare R2 with provenance (URL, retrieved-at timestamp, checksum)
   and inserts normalized rows into Postgres keyed by
   `(snapshot_date, ...)`.
2. **Diffs against last night.** Compares yesterday's snapshot to today's.
   Emits typed events: a new object, a newly-forecast approach, or a
   revision to an existing approach (distance changed, orbit determination
   updated).
3. **Evaluates alert rules.** Pure functions decide which events cross
   thresholds worth telling people about — a sizeable object inside the
   lunar distance, a very-close approach regardless of size, a
   newly-discovered object whose first close approach is imminent.
4. **Publishes.** Regenerates RSS feeds, JSON endpoints, and the public
   site.

Every event has a deterministic `dedup_key` so re-running the pipeline is
idempotent: the same input produces the same key, and the loader skips on
conflict. The nightly can re-run safely after a partial failure without
duplicating alerts.

The two-phase split (raw landing tables vs. dbt marts) keeps the ingest
path simple and the analytical layer auditable. dbt only enters in Phase
2; Phase 1 reads from raw tables directly.

## Local development

```bash
# Python (3.12)
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill in real values

# Apply schema (against your Neon DATABASE_URL)
psql "$DATABASE_URL" -f etl/schema.sql

# Verify Neon + R2 (or local-fallback) connectivity
make check-setup

# Run unit tests (no DB or R2 required)
make test

# Local API + web (two terminals)
make api               # http://localhost:8551
make web-install
make web               # http://localhost:5551
```

### Snapshot storage backend

By default, raw CNEOS + SBDB payloads are archived to Cloudflare R2. If the
four `R2_*` env vars aren't set (or `STORAGE_BACKEND=local`), the pipeline
falls back to writing snapshots into `data/snapshots/local-r2/` on disk —
useful for local development without a Cloudflare account. See
`.env.example` for details. Switching backends is purely an env-var change;
no code changes required.

## Architecture (Phase 1)

```
JPL CNEOS Close-Approach API ─┐
JPL SBDB Query API ───────────┼─► nightly cron (GitHub Actions, 06:30 UTC)
                              │
                              ▼
  etl.extract → R2 snapshot
  etl.load    → Postgres raw landing tables
  etl.diff    → approach_events stream (idempotent on dedup_key)
  etl.alerts  → noteworthy.{rss,json}
  etl.publish → upcoming.{rss,json}, public/health.json
  FastAPI / Vercel
```

See [PLAN.md](PLAN.md) for the full phased plan including data sources,
schema specifics, and risk register.

## Acknowledgments

Close-approach and small-body data are derived from products of NASA's Jet
Propulsion Laboratory, California Institute of Technology, including the
[Center for Near-Earth Object Studies (CNEOS)](https://cneos.jpl.nasa.gov/)
close-approach database and the [JPL Small-Body Database](https://ssd.jpl.nasa.gov/).
NASA/JPL/Caltech data is in the public domain.

Risk assessments are sourced from [NASA Sentry](https://cneos.jpl.nasa.gov/sentry/)
and the [European Space Agency Near-Earth Object Coordination Centre
(ESA NEOCC)](https://neo.ssa.esa.int/).

Object designations and discovery announcements are sourced from the
[IAU Minor Planet Center](https://www.minorplanetcenter.net/), Smithsonian
Astrophysical Observatory.

Bibliographic metadata for scientific publications is sourced from the
[NASA Astrophysics Data System](https://ui.adsabs.harvard.edu/), Crossref,
and arXiv.

## License

- Code: [MIT](LICENSE)
- Data products: [CC BY 4.0](LICENSE-DATA), with upstream attributions per
  the agencies listed above.

## Contact

mark@pernotto.com
