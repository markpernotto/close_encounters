# close encounters

A public data warehouse and alerting feed for near-Earth objects: what's
passing close, who saw it first, and how the orbit got refined.

> **Status:** Phase 1 in progress. Nothing is shipping yet.

## What it does

- Nightly ingest of NASA JPL's CNEOS close-approach feed and the JPL
  Small-Body Database, snapshotted into Postgres with full provenance.
- Diff between successive snapshots produces a stream of `NEW_OBJECT`,
  `NEW_APPROACH`, and `REVISED_APPROACH` events.
- Public RSS and JSON feeds of upcoming approaches and "noteworthy"
  approaches (size + distance thresholds).
- A minimal React UI for browsing upcoming and recent close approaches.

Phase 2 adds a risk warehouse cross-referencing NASA Sentry and ESA NEOCC
plus a dbt mart layer with SCD-2 modeling of orbit revisions. Phase 3 adds
a citation graph linking each NEO to the IAU Minor Planet Center circular
or scientific paper that announced it.

## Local development

```bash
# Python
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill in real values

# Verify Neon + R2 connectivity and the schema
make check-setup

# Web
make web-install
make web   # http://localhost:5550

# API
make api   # http://localhost:8000
```

## Architecture

```
JPL CNEOS Close-Approach API ─┐
JPL SBDB Query API ───────────┼─► nightly cron (GitHub Actions, 06:30 UTC)
                              │
                              ▼
  etl.extract → R2 snapshot
  etl.load    → Postgres raw landing tables
  etl.diff    → approach_events stream
  etl.alerts  → noteworthy.{rss,json}
  etl.publish → upcoming.{rss,json}, public/health.json
  FastAPI / Vercel
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
[docs/DATA_CATALOG.md](docs/DATA_CATALOG.md) for details.

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
