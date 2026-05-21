# Data Catalog

One entry per upstream source: title, publisher, URL, license, update
cadence, coverage period, fields used, known quality issues, and citation
string. Entries marked "Phase 2" or "Phase 3" are scoped but not yet
ingested.

Each entry follows the same template so the file is easy to scan and easy
to add to.

---

## NASA JPL CNEOS Close-Approach Data API

| | |
|---|---|
| **Phase** | 1 |
| **Status** | ingested nightly |
| **Publisher** | NASA Jet Propulsion Laboratory, California Institute of Technology |
| **Operating office** | Center for Near-Earth Object Studies (CNEOS) |
| **Endpoint** | `https://ssd-api.jpl.nasa.gov/cad.api` |
| **Documentation** | https://ssd-api.jpl.nasa.gov/doc/cad.html |
| **Authentication** | None |
| **Rate limits** | No published limit; we make one request per night |
| **Format** | JSON. Column-oriented: `{fields: [...], data: [[...], ...], count, signature}` |
| **License** | Public domain (US government work) |
| **Attribution required** | Acknowledgment of NASA/JPL/Caltech |
| **Update cadence** | Continuous as orbits are refined; we sample once per UTC day |
| **Coverage period** | We pull a sliding 60-day forward window inside 0.05 AU (~19.5 LD) |

**Fields used** (from `fields` array):

| CNEOS field | Schema column | Notes |
|---|---|---|
| `des` | `close_approaches_snapshots.designation` | Primary designation, e.g. "2024 YR4" or "99942" |
| `orbit_id` | `close_approaches_snapshots.orbit_id` | Changes signal a revised orbit determination |
| `cd` | `close_approaches_snapshots.approach_date` | Format `YYYY-Mon-DD HH:MM` UTC |
| `dist` | `close_approaches_snapshots.distance_au` | AU at closest approach |
| `dist_min` / `dist_max` | `close_approaches_snapshots.distance_min_au` / `distance_max_au` | 1-sigma bounds |
| `v_rel` | `close_approaches_snapshots.v_rel_km_s` | km/s relative to body at approach |
| `v_inf` | `close_approaches_snapshots.v_inf_km_s` | km/s at infinity |

**Derived** in `etl.transform`: `distance_ld = distance_au * (1 AU / 1 LD)` ≈ `distance_au * 389.17`.

**Known quality issues**

- `dist_min` / `dist_max` are sometimes equal to `dist` for very well-tracked objects with vanishing orbital uncertainty.
- The CNEOS API does not echo the requested `body` parameter back in rows. We default to `body = "Earth"` because that is what the nightly pulls.
- The `orbit_id` is an internal JPL integer; absolute values are meaningful only relative to the same object's prior orbit_id.
- CNEOS rows do not carry `spkid`. We resolve it via the parallel SBDB lookup in `etl.extract.gather_snapshot`.

**Citation string**

> Data sourced from the NASA/JPL Center for Near-Earth Object Studies
> Close-Approach Database, https://cneos.jpl.nasa.gov/ca/, accessed
> {snapshot_date}.

---

## NASA JPL Small-Body Database (SBDB) Lookup API

| | |
|---|---|
| **Phase** | 1 |
| **Status** | ingested nightly |
| **Publisher** | NASA Jet Propulsion Laboratory, California Institute of Technology |
| **Endpoint** | `https://ssd-api.jpl.nasa.gov/sbdb.api` |
| **Documentation** | https://ssd-api.jpl.nasa.gov/doc/sbdb.html |
| **Authentication** | None |
| **Rate limits** | No published limit; we pace requests 0.5 s apart |
| **Format** | JSON: `{object, signature, orbit, phys_par, discovery}` |
| **License** | Public domain (US government work) |
| **Attribution required** | Acknowledgment of NASA/JPL/Caltech |
| **Update cadence** | Continuous as orbits are refined |
| **Coverage** | All catalogued small bodies. We look up one record per unique designation in each night's CNEOS pull. |

**Fields used**

From `object`: `spkid`, `des`, `fullname`, `neo`, `pha`, `orbit_class.code`.

From `orbit`: `soln_date`, `epoch`, `n_obs_used`, `data_arc`, `first_obs`, `last_obs`, `elements` array (indexed by name: `e`, `a`, `i`, `om`, `w`, `ma` plus their `sigma`).

From `phys_par`: `H` (absolute magnitude), `diameter` (km), `albedo`, `rot_per` (rotation period in hours), `spec_T` / `spec_B` (spectral class).

From `discovery` (Phase 3 — captured today but not yet surfaced): `who`, `site`, `date`, `ref`, `name`, `citation`. This block is the seed for the Phase 3 citation graph.

**Known quality issues**

- Many newly-discovered objects have only `H` (absolute magnitude), no measured `diameter` or `albedo`. `etl.alerts.derive_diameter_km` estimates size from `H` using default albedo 0.14 for typical NEOs.
- `orbit.elements` is an array of dicts indexed by name, not a flat record. `etl.transform._index_orbit_elements` flattens this for storage.
- `data_arc` units are days (integer). For poorly-tracked objects this can be < 1 day; SBDB returns 0 in that case.
- `soln_date` is a timestamp string `YYYY-MM-DD HH:MM:SS` UTC — we down-cast to DATE on storage since the nightly cadence makes sub-day precision moot.

**Citation string**

> Data sourced from the NASA/JPL Small-Body Database, https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html, accessed {snapshot_date}.

---

## NASA Sentry Impact Risk

| | |
|---|---|
| **Phase** | 2 (planned) |
| **Status** | not yet ingested |
| **Publisher** | NASA Jet Propulsion Laboratory / CNEOS |
| **Endpoint** | `https://ssd-api.jpl.nasa.gov/sentry.api` |
| **Documentation** | https://ssd-api.jpl.nasa.gov/doc/sentry.html |
| **Authentication** | None |
| **License** | Public domain (US government work) |
| **Update cadence** | Continuous; refresh nightly |
| **Coverage** | Only objects with computed impact probability > 0. Most NEOs are *not* on this list. |

**Fields planned for ingest** (Phase 2): `spkid`, `torino_scale` (0–10),
`palermo_scale` (logarithmic), `impact_probability`, `potential_impact_date`,
`energy_mt` (impact energy in megatons TNT-equivalent).

**Known quality issues**

- The Sentry list is empty most days. The UI must handle the zero-row
  case gracefully.
- Risk classifications can move both up and down over time as observation
  arcs lengthen. We capture each assessment date so the history is
  preserved.

**Citation string**

> Impact-risk assessments sourced from the NASA Sentry system, https://cneos.jpl.nasa.gov/sentry/, accessed {snapshot_date}.

---

## ESA Near-Earth Object Coordination Centre (NEOCC) Risk List

| | |
|---|---|
| **Phase** | 2 (planned) |
| **Status** | not yet ingested |
| **Publisher** | European Space Agency, NEO Coordination Centre |
| **Endpoint** | `https://neo.ssa.esa.int/PSDB-portlet/download` |
| **Documentation** | https://neo.ssa.esa.int/ |
| **Authentication** | None |
| **License** | ESA terms; attribution required |
| **Update cadence** | Daily |
| **Coverage** | European cross-check on the NASA Sentry list. The two lists sometimes disagree on risk classification; that disagreement is the point — both are surfaced. |

**Citation string**

> Risk assessments sourced from the ESA Near-Earth Object Coordination Centre Risk List, https://neo.ssa.esa.int/risk-list, accessed {snapshot_date}.

---

## IAU Minor Planet Center (MPC) — MPEC archive

| | |
|---|---|
| **Phase** | 3 |
| **Status** | ingested on demand via `make resolve-citations`; wired into nightly with continue-on-error |
| **Publisher** | Smithsonian Astrophysical Observatory, on behalf of the International Astronomical Union |
| **Endpoint** | `https://www.minorplanetcenter.net/iau/services/MPEC.html` and archive |
| **Documentation** | https://www.minorplanetcenter.net/iau/info/Acknowledgements.html |
| **Authentication** | None |
| **License** | Attribution required per MPC terms |
| **Update cadence** | On publication (variable, often daily) |
| **Coverage** | The canonical "this is a new object" notice for newly-discovered minor planets. Phase 3 uses MPEC IDs as one of the stable citation keys in the discovery graph. |

**Citation string**

> Discovery announcements sourced from the IAU Minor Planet Center electronic circulars (MPECs), https://www.minorplanetcenter.net/, accessed {snapshot_date}.

---

## NASA Astrophysics Data System (ADS) API

| | |
|---|---|
| **Phase** | 3 |
| **Status** | ingested nightly when ADS_API_TOKEN is configured; tier skips gracefully if missing |
| **Publisher** | Harvard-Smithsonian Center for Astrophysics, operated under NASA grant |
| **Endpoint** | `https://api.adsabs.harvard.edu/v1` |
| **Documentation** | https://ui.adsabs.harvard.edu/help/api/ |
| **Authentication** | Bearer token (free, manual approval). Same token as `exoplanet_citation` is reused; the token is tied to the user, not the project. |
| **Rate limits** | 5000 queries/day per token. Phase 3 only resolves new discoveries, not nightly re-resolution, so the burn is bursty and small. |
| **License** | API output is metadata; verify terms per ADS |
| **Update cadence** | On demand |
| **Coverage** | Astronomy bibliography, resolves DOIs and ADS bibcodes for discovery papers. |

**Citation string**

> Bibliographic metadata sourced from the NASA Astrophysics Data System, https://ui.adsabs.harvard.edu/, accessed {snapshot_date}.

---

## Internal artifacts (derived)

The pipeline produces these from the upstream sources. They are not
themselves data sources, but they are catalog entries because downstream
consumers (the public site, RSS readers) treat them as such.

- **`public/upcoming.json`** — every approach in the latest snapshot within the next 60 days. License: CC BY 4.0, see [LICENSE-DATA](../LICENSE-DATA).
- **`public/upcoming.rss`** — same content as RSS 2.0.
- **`public/noteworthy.json`** — all alerts (threshold-rule matches) most recent first. License: CC BY 4.0.
- **`public/noteworthy.rss`** — same content as RSS 2.0.
- **`public/health.json`** — last-run timestamp, latest snapshot date, record counts. Public, no auth.
- **`data/MANIFEST.jsonl`** — per-snapshot provenance manifest. Committed to the repository.
