# close encounters

A public data warehouse and alerting feed for near-Earth objects: which
asteroids and comets are passing close to Earth, how big they are, how
confident the orbit is, and who saw them first.

> **Status:** Phase 1 shipped (live). Phase 2 shipped (live). Phase 3
> wired end-to-end as of Commit 5 of 5 — the citation graph builds
> nightly via `make resolve-citations` (MPEC + ADS tiers, gracefully
> skips ADS when no token is configured).

## The three-phase project

Each phase is independently shippable, building on the last.

### Phase 1 — close-approach watcher ✅ shipped

Nightly pipeline pulls NASA JPL's CNEOS close-approach feed and the JPL
Small-Body Database, snapshots them to durable storage with provenance,
diffs against the previous night, fires threshold-rule alerts, and
publishes RSS + JSON feeds. The public site shows upcoming approaches in
a sortable table.

### Phase 2 — risk warehouse + orbit-revision history ✅ shipped

NASA Sentry and ESA NEOCC risk lists ingested and reconciled into a
single warehouse. A dbt mart layer materializes SCD-2 history on object
parameters (`dim_object`), one row per orbit determination
(`dim_orbit_revision`), a cross-agency pivot (`fact_risk_assessment`),
and denormalized API-friendly views. The public site has a `/risk` page
showing coverage stats and a per-object cross-agency panel. The diff
layer emits `RISK_CLASS_CHANGE` events when either agency revises an
assessment.

### Phase 3 — citation graph ✅ wired end-to-end

Each NEO linked to the discovery announcement that announced it (IAU
Minor Planet Center electronic circular) and to journal papers from
NASA ADS, with confidence-scored links. Two-tier resolver runs nightly:
MPEC discovery for objects where SBDB references one, ADS full-text
search for follow-up papers per designation. Discovery info (who,
where, when, which program) surfaces on each object detail page. See
[docs/CITATION_RESOLUTION.md](docs/CITATION_RESOLUTION.md) for the
methodology and confidence model.

## What's built (as of the latest commit)

### Pipeline modules

- **Schema** — [etl/schema.sql](etl/schema.sql). Nine tables across raw
  landing (`objects_snapshots`, `orbit_elements_snapshots`,
  `close_approaches_snapshots`, `risk_assessments`,
  `discovery_attributions`), derived (`approach_events`, `alerts`), and
  Phase 3 citation graph (`discovery_publications`,
  `object_publications`). All keyed for idempotent re-runs.
- **Source clients** — JPL CNEOS, JPL SBDB, NASA Sentry, ESA NEOCC, IAU
  MPC. All polite httpx with tenacity retries and a User-Agent that
  identifies the project to upstream logs.
- **Transform** — pure functions normalizing each source's response into
  schema-shaped row dicts; no I/O, fully unit-tested with committed
  fixtures.
- **Load** — UPSERT writers for every table, with the right conflict
  targets (composite keys for raw snapshots, deterministic dedup_keys
  for events, designation+publication_id+relationship for the citation
  graph).
- **Diff** — pure `compute_events` + `compute_risk_events` over two
  consecutive snapshots; emits four event types (`NEW_OBJECT`,
  `NEW_APPROACH`, `REVISED_APPROACH`, `RISK_CLASS_CHANGE`) with
  deterministic dedup_keys so re-runs are no-ops.
- **Alerts** — threshold rules in `etl/alerts.py` (sizeable+close,
  very-close-any-size, short-arc late warning), each a pure function,
  exhaustively unit-tested. Append-only by policy.
- **Publish** — generates `public/{upcoming,noteworthy}.{rss,json}` +
  `public/health.json`. Renderers are pure functions over DB rows.
- **dbt project** — staging views over every raw landing table; seven
  marts: SCD-2 `dim_object` (via dbt snapshot), `dim_orbit_revision`,
  `fact_close_approach` joined to the orbit revision that produced it
  with apparent-magnitude estimation, `fact_risk_assessment`
  cross-agency pivot, `mart_objects_current`, and the symmetric
  `mart_upcoming_approaches` / `mart_recent_approaches` pair that both
  the API endpoints **and** the public RSS / JSON feeds read from.
- **Resolve citations** — Phase 3 `etl/resolve_citations.py` fetches MPECs
  referenced in `discovery_attributions`, parses them, and populates
  `discovery_publications` + `object_publications` with confidence-scored
  relationships.

### API + web

FastAPI app with the following endpoints, all reading from the dbt
marts where applicable:

- `GET /health`
- `GET /api/approaches/upcoming` (mart-backed, includes
  apparent_mag_estimate + visibility_bucket)
- `GET /api/approaches/recent` (mart-backed, 90-day window)
- `GET /api/objects/{designation}` (mart-backed)
- `GET /api/objects/{designation}/approaches`
- `GET /api/objects/{designation}/orbit-history` — every JPL orbit
  revision for this object
- `GET /api/alerts`
- `GET /api/risk` — cross-agency coverage overview
- `GET /api/risk/{designation}` — per-object NASA/ESA side-by-side
- `GET /api/objects/{designation}/publications` — citation graph for one
  object (Phase 3); orders by relationship (discovery → follow-up) and
  surfaces confidence-scored links to MPECs + ADS papers

React + Vite frontend with three pages:

- `/` — upcoming approaches with sortable table + visibility-bucket
  column
- `/alerts` — noteworthy threshold-rule matches as cards
- `/risk` — coverage bars + Palermo/Torino scale explainer
- `/objects/:designation` — full object detail, including a discovery
  card (who reported it, when, which program), a cross-agency risk
  panel (when the object is on a risk list), an orbit-revision
  timeline, and a citation-graph publications panel grouped by
  relationship with confidence badges

### Tests + tooling

230+ unit tests across all modules. ruff linting in CI. dbt schema +
relationship + accepted-values tests in nightly. Local development via
`make` targets for every step.

## How it works (under the hood)

The design is **snapshot + diff**, not stateful change-data-capture. Every
night the pipeline:

1. **Snapshots the sources.** CNEOS + SBDB + NASA Sentry + ESA NEOCC,
   all pulled and saved to Cloudflare R2 (or local fallback) with
   provenance (URL, retrieved-at timestamp, checksum). Normalized rows
   land in Postgres keyed by `(snapshot_date, ...)`.
2. **Diffs against last night.** Two parallel diffs: close-approach
   diffs produce NEW_OBJECT / NEW_APPROACH / REVISED_APPROACH events;
   risk-list diffs produce RISK_CLASS_CHANGE events.
3. **Evaluates alert rules.** Pure functions decide which approach
   events cross thresholds worth surfacing publicly.
4. **Refreshes marts.** dbt snapshot updates SCD-2 history; dbt run
   rebuilds the analytical layer; dbt test validates.
5. **Publishes.** Regenerates RSS + JSON feeds and commits them back to
   the repo, which triggers a Vercel rebuild.

Idempotency is enforced at four layers: R2 keys are deterministic, raw
landing tables use ON CONFLICT DO UPDATE, events have deterministic
dedup_keys, alerts have rule_id+event_dedup_key keys. A re-run produces
zero net rows.

## Local development

```bash
# Python (3.12)
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill in real values

# Apply schema (against your Neon DATABASE_URL via the Makefile target)
make schema

# Verify Neon + R2 (or local-fallback) connectivity
make check-setup

# Run unit tests (no DB or R2 required)
make test

# Run the full nightly pipeline locally
make pipeline           # extract → diff → alerts → publish
make dbt-build          # dbt snapshot → run → test

# Optional: resolve citation graph from accumulated discovery data
make resolve-citations  # fetches MPECs referenced in discovery_attributions

# Local API + web (two terminals)
make api                # http://localhost:8551
make web-install
make web                # http://localhost:5551

# Interactive psql against Neon
make psql
```

### Snapshot storage backend

By default, raw payloads are archived to Cloudflare R2. If the four
`R2_*` env vars aren't set (or `STORAGE_BACKEND=local`), the pipeline
falls back to writing snapshots into `data/snapshots/local-r2/` on disk —
useful for local development without a Cloudflare account. See
`.env.example` for details. Switching backends is purely an env-var
change; no code changes required.

## Architecture

```
JPL CNEOS, JPL SBDB, NASA Sentry,    ┐
ESA NEOCC                            ├─► nightly cron (GitHub Actions, 06:30 UTC)
                                     │
                                     ▼
  etl.extract    → R2 snapshot + raw landing tables in Postgres
  etl.diff       → approach_events stream (idempotent on dedup_key)
  etl.alerts     → alerts table + threshold-rule evaluation
  dbt snapshot   → dim_object SCD-2 history
  dbt run        → staging views + marts
  dbt test       → schema validation
  etl.publish    → reads mart_upcoming_approaches + alerts
                   → public/{upcoming,noteworthy}.{rss,json}
                   + public/health.json
                                     │
                                     ▼
  Vercel: React UI + FastAPI as serverless functions, reading marts
  IAU MPC (on-demand via make resolve-citations) → discovery_publications
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

Bibliographic metadata for scientific publications (Phase 3) is sourced
from the [NASA Astrophysics Data System](https://ui.adsabs.harvard.edu/),
Crossref, and arXiv.

## License

- Code: [MIT](LICENSE)
- Data products: [CC BY 4.0](LICENSE-DATA), with upstream attributions per
  the agencies listed above.

## Contact

mark@pernotto.com
