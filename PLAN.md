# close_encounters / neo_citation — project plan

**Owner:** Mark Pernotto (mark@pernotto.com)
**Status:** Phase 1 in progress
**Target effort:** ~4 weeks part-time (Phases 1+2 = original 02 doc; Phase 3 = new citation thread)

---

## One-paragraph pitch

A public data warehouse and alerting feed for near-Earth objects (asteroids
and comets that pass close to Earth's orbit). Daily ETL ingests NASA JPL's
Small-Body Database, the CNEOS close-approach feed, and ESA's NEO
Coordination Centre. The warehouse exposes "what's passing close this week,
how big, how confident is the orbit determination, and how does it compare
to historical close approaches." Public RSS/JSON alerts fire when something
larger than 50 m passes inside the lunar distance. Phase 3 adds a citation
graph linking each NEO to the IAU Minor Planet Center circular or scientific
paper that announced it.

---

## Definition of Done

### Phase 1 (Weeks 1–2): Close-Approach Watcher
- [ ] Repo public on GitHub
- [ ] Nightly GitHub Action ingests CNEOS close-approach data + JPL SBDB queries for any new objects
- [ ] Postgres (Neon) contains a historical record of every close approach observed
- [ ] Diff job emits `NEW_APPROACH`, `REVISED_APPROACH`, `NEW_OBJECT` events
- [ ] Public RSS feed of close approaches in the next 60 days
- [ ] Public RSS feed of "noteworthy" approaches (≥50 m, inside lunar distance)
- [ ] Public JSON endpoints: `/api/approaches/upcoming`, `/api/approaches/recent`, `/api/objects/{designation}`
- [ ] Minimal React page shows upcoming approaches in a sortable table
- [ ] README with architecture diagram, data sources, attribution, how-to-run
- [ ] `docs/DATA_CATALOG.md` entries for SBDB and CNEOS
- [ ] Controlled-vocabulary files for `orbit_class`, `approach_event_type`, `alert_rule`
- [ ] Freshness SLO: published data ≤ 26 hours stale from source
- [ ] pytest suite covers extract, transform, diff, load idempotency, alert-threshold logic
- [ ] Action has been green for 5 consecutive nights

### Phase 2 (Week 3): Risk Warehouse + Historical Comparator
- [ ] dbt project: `raw` → `staging` → `marts` with `dim_object`, `dim_orbit_revision`, `fact_close_approach`, `fact_risk_assessment`
- [ ] SCD-2 modeling for orbit determinations (each revision keyed by `solution_date`)
- [ ] ESA NEOCC risk list ingested and joined to JPL data (cross-agency reconciliation)
- [ ] NASA Sentry impact-risk feed ingested
- [ ] Diff emits `RISK_CLASS_CHANGE` events
- [ ] Public endpoint: `/api/objects/{designation}/orbit-history`
- [ ] Public endpoint: `/api/comparisons/{designation}` — "this approach is the Nth-closest of size class X since 1900"
- [ ] React UI: object detail page with orbit-revision timeline; "compare to historical" panel
- [ ] dbt tests pass in CI; `dbt docs` published
- [ ] `docs/SCD_MODELING.md` written

### Phase 3 (Week 4): Citation Graph
- [ ] Each tracked NEO linked to ≥1 discovery announcement via MPEC ID, DOI, or ADS bibcode
- [ ] Resolution confidence score per link (high / medium / low / unresolved) with reason
- [ ] MPC announcement circulars (MPECs), Crossref, arXiv, and NASA ADS metadata cached in `discovery_publications`
- [ ] Discovery program / facility attribution per object (Catalina, ATLAS, Pan-STARRS, NEOWISE, Rubin SSP, etc.)
- [ ] Public endpoints: `/api/objects/{designation}/publications`, `/api/publications/{id}`, `/api/publications/{id}/objects`
- [ ] React UI: object detail page shows discovery announcement + follow-up papers
- [ ] `docs/CITATION_RESOLUTION.md` documents the tiered resolver
- [ ] README v3 leads with the citation graph + cross-agency risk reconciliation

---

## Data Sources

All public. Attribute the agency in README and in-app.

| Source | URL | Format | Update | Phase | Notes |
|---|---|---|---|---|---|
| JPL Small-Body Database (SBDB) Query API | https://ssd-api.jpl.nasa.gov/sbdb_query.api | JSON | Continuous | 1+ | Reference catalog: orbital elements + physical properties |
| JPL SBDB Lookup API | https://ssd-api.jpl.nasa.gov/sbdb.api | JSON | Continuous | 1+ | Single-object lookup with full orbit-determination history |
| NASA CNEOS Close-Approach Data | https://ssd-api.jpl.nasa.gov/cad.api | JSON | Daily | 1+ | The close-approach firehose |
| NASA Sentry Impact Risk | https://ssd-api.jpl.nasa.gov/sentry.api | JSON | Continuous | 2 | Official NASA risk list |
| NASA NEOWS | https://api.nasa.gov/neo/rest/v1/ | JSON | Daily | 1 (fallback) | Used only if SBDB+CNEOS rate-limit us |
| ESA NEOCC Risk List | https://neo.ssa.esa.int/PSDB-portlet/download | JSON/CSV | Daily | 2 | European cross-check |
| IAU Minor Planet Center MPEC archive | https://www.minorplanetcenter.net/iau/services/MPEC.html | HTML/text | On publication | 3 | Discovery announcements — primary citation source |
| NASA ADS API | https://api.adsabs.harvard.edu/v1 | JSON | On demand | 3 | Astronomy bibliography (DOI/bibcode resolution) |
| Crossref REST API | https://api.crossref.org/works/{doi} | JSON | On demand | 3 | DOI metadata |
| arXiv API | http://export.arxiv.org/api/query | Atom | On demand | 3 | arXiv preprint metadata |

### Source-of-truth notes
- The CNEOS feed is the operational firehose. SBDB is the reference catalog. Use CNEOS for "what's coming up" and SBDB to enrich with physical properties.
- Sentry is its own list — only objects with computed impact probability > 0. Most NEOs are *not* on Sentry.
- ESA NEOCC and NASA Sentry sometimes disagree on risk classification; that disagreement is itself useful warehouse content.
- MPECs are the canonical "this is a new object" notice. The MPEC ID is the closest thing to a stable citation key for a discovery.

---

## Schema

### Phase 1 (raw landing — implemented in `etl/schema.sql`)

- `objects_snapshots` keyed by `(snapshot_date, spkid)` — physical/orbital metadata per snapshot.
- `orbit_elements_snapshots` keyed by `(spkid, solution_date)` — every orbit revision separately, drives Phase 2 SCD-2.
- `close_approaches_snapshots` keyed by `(snapshot_date, spkid, approach_date, body)` — every close-approach prediction snapshot.
- `approach_events` — derived event stream from `etl.diff`.

### Phase 2 additions

- `risk_assessments` keyed by `(spkid, agency, assessment_date)`.
- dbt mart layer: `dim_object`, `dim_orbit_revision`, `fact_close_approach`, `fact_risk_assessment`, `mart_upcoming_approaches`.

### Phase 3 additions

```sql
discovery_publications (
  publication_id     BIGSERIAL PRIMARY KEY,
  doi                TEXT UNIQUE,
  mpec_id            TEXT UNIQUE,
  ads_bibcode        TEXT UNIQUE,
  arxiv_id           TEXT UNIQUE,
  title              TEXT NOT NULL,
  authors            JSONB,
  publication_date   DATE,
  source_url         TEXT,
  resolved_via       TEXT NOT NULL,    -- 'mpec' | 'ads' | 'crossref' | 'sbdb_producer'
  resolved_at        TIMESTAMPTZ NOT NULL,
  raw_record         JSONB NOT NULL
);

object_publications (
  spkid              TEXT NOT NULL,
  publication_id     BIGINT NOT NULL REFERENCES discovery_publications(publication_id),
  relationship       TEXT NOT NULL,    -- 'discovery' | 'recovery' | 'follow_up' | 'risk_assessment'
  confidence         TEXT NOT NULL,    -- 'high' | 'medium' | 'low'
  confidence_reason  TEXT NOT NULL,
  extracted_from     TEXT NOT NULL,
  extracted_at       TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (spkid, publication_id, relationship)
);

discovery_attributions (
  spkid              TEXT PRIMARY KEY,
  discovery_facility TEXT NOT NULL,
  discovery_program  TEXT,
  discovery_date     DATE NOT NULL,
  reported_via       TEXT,             -- usually MPEC ID
  source_url         TEXT
);
```

---

## Pipeline

### Phase 1
```
JPL CNEOS Close-Approach API ─┐
JPL SBDB Query API ───────────┼─► nightly cron (06:30 UTC)
                              ▼
  etl.extract  → R2 snapshot
  etl.load     → objects_snapshots, orbit_elements_snapshots, close_approaches_snapshots
  etl.diff     → approach_events
  etl.alerts   → noteworthy.{rss,json}
  etl.publish  → upcoming.{rss,json}, public/health.json
  FastAPI / Vercel
```

### Phase 2
```
NASA Sentry + ESA NEOCC ─► etl.sources.* → risk_assessments
                                    │
                                    ▼
                              dbt run → marts
                                    │
                                    ▼
                              etl.publish (extended endpoints)
```

### Phase 3
```
approach_events (NEW_OBJECT) + objects_snapshots
                │
                ▼
  etl.resolve_citations → discovery_publications, object_publications, discovery_attributions
                │
                ▼
  etl.publish (citation-graph endpoints)
```

---

## Alert threshold logic (Phase 1)

The "noteworthy" RSS feed is the user-facing trust point. Rules implemented as
pure functions in `etl/alerts.py` and tested exhaustively. Documented in
plain English in `docs/ALERT_RULES.md`.

1. **Size + distance.** Estimated diameter ≥ 50 m AND distance ≤ 1 LD.
2. **Very-close regardless of size.** Distance ≤ 0.5 LD.
3. **Newly-discovered with short observation arc.** `NEW_OBJECT` AND first close approach within 30 days AND observation arc < 14 days.
4. **Risk class change.** Phase 2 only.

False-alarm policy (in `docs/ALERT_RULES.md`): alerts are NEVER retracted;
corrections are appended.

---

## Citation resolution strategy (Phase 3)

Mirrors the tiered approach from `exoplanet_citation`. For each new NEO:

1. **Tier 1 — direct DOI/bibcode/MPEC ID** present in the SBDB record. Trivial; `confidence='high'`.
2. **Tier 2 — MPEC archive lookup.** Construct the MPEC ID from the discovery date + survey program; fetch the announcement.
3. **Tier 3 — ADS bibcode + Crossref structured search** for follow-up papers that cite the object designation.
4. **Tier 4 — manual review queue.** `docs/UNRESOLVED.md` autogenerated.

Anti-goal: real NLP. Rule-based parsing with progressively wider nets. If
unresolved by Tier 3, queue it.

---

## Repository layout (current)

```
close_encounters/
├── .github/workflows/{nightly,ci}.yml
├── etl/
│   ├── r2.py, check_setup.py, schema.sql
│   ├── sources/                         # JPL CNEOS, JPL SBDB, etc. (per phase)
│   ├── transform/                       # dbt project root (Phase 2)
│   └── migrations/
├── api/index.py                         # FastAPI; uvicorn entry api.index:app
├── web/                                 # Vite + React + TS
├── vocabularies/                        # orbit_class, risk_class, approach_event_type, alert_rule, discovery_facility, citation_confidence
├── data/MANIFEST.jsonl                  # snapshot manifest (snapshots themselves live in R2)
├── tests/
├── docs/                                # ARCHITECTURE, DATA_CATALOG, ALERT_RULES, SCD_MODELING, CITATION_RESOLUTION; OUTREACH.md is gitignored
├── infra/                               # Terraform (small scope)
├── public/                              # generated RSS + JSON (committed by nightly)
├── Dockerfile, docker-compose.yml, vercel.json
├── pyproject.toml, Makefile
├── LICENSE, LICENSE-DATA, PRIVACY.md
├── README.md, PLAN.md
└── .env.example
```

---

## Risk register

| Risk | Mitigation |
|---|---|
| JPL APIs change response schema | `raw_row JSONB` preserves source row; transforms log unknown fields rather than failing |
| CNEOS rate limits or blocks us | Polite 1 req/day per endpoint; `User-Agent` identifies the project; NEOWS as fallback |
| Alert rules fire spuriously and erode trust | Test exhaustively; document each rule with rationale; alerts NEVER retracted, corrections appended |
| Orbit revisions arrive faster than nightly cadence | Acceptable for v1.0. Increase to 6-hourly if needed |
| ESA NEOCC and NASA Sentry disagree | Content, not bug. Surface explicitly in `fact_risk_assessment` |
| Sentry list is empty | Normal — handle gracefully in UI |
| MPEC parsing is fragile | Fall back to ADS/Crossref tiers; queue for manual review if all fail |
| Schema drift in CNEOS solution_date semantics | Document JPL conventions in `docs/DATA_SOURCES.md` |
| Timeline slips | Acceptable to 5 weeks. Phase 3 (citation) can ship as v1.1 if Week 4 runs tight |

---

## What NOT to add

- Authentication / user accounts
- "Subscribe to alerts" infrastructure beyond RSS
- Predictive risk modeling — the agencies do this; we don't compete
- Any modification of NASA's risk classifications — we report, we don't reinterpret
- "Will this hit my city" calculators — irresponsible without rigor
- Comet-specific physical modeling — out of scope, NEO focus only
- ML / LLM features
- Rubin alert-stream ingestion or other special-engineered Rubin pathways — outreach-only relationship for now

---

## Open questions

1. **NASA NEOWS API key** — instant signup at https://api.nasa.gov. Get one even though it's a fallback.
2. **NASA ADS token** — required for Phase 3. Apply at https://ui.adsabs.harvard.edu/user/settings/token. Existing token (from `exoplanet_citation` work) can be reused.
3. **Backfill depth** — recommend backfilling 1 year of close-approach history on Day 1 to populate the UI; deeper history can wait.
4. **Database isolation** — recommend a fresh Neon project (already decided), separate from `exoplanet_citation`.
