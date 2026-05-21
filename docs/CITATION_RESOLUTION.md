# Citation Resolution

Phase 3 of the project links each near-Earth object to the publications
that discuss it: the discovery announcement that announced it (an IAU
Minor Planet Center electronic circular, "MPEC"), and the follow-up
journal papers indexed by NASA ADS. The result is a confidence-scored
graph stored in two tables, queryable via the API.

This document explains how that graph gets built, what the confidence
levels mean, and where the current implementation falls short.

## What it produces

**`discovery_publications`** — one row per publication. The publication is
the unit of identity; many objects can cite the same paper (a survey
paper announcing 50 discoveries, a cross-classification update covering
hundreds of objects). Keyed flexibly on whichever of `mpec_id`, `doi`,
`ads_bibcode`, or `arxiv_id` uniquely identifies it.

**`object_publications`** — the citation graph edges. PK is
`(designation, publication_id, relationship)`. An object can relate to
the same publication under multiple relationships (e.g., an MPEC both
announces it and reports a recovery observation), so relationship is
part of the natural key.

The `relationship` vocabulary is small and stable:

| Value | Meaning |
|---|---|
| `discovery` | This publication is the body's discovery announcement |
| `recovery` | This publication reports a recovery / continued observation |
| `follow_up` | A scientific paper studying the object after discovery |
| `risk_assessment` | A paper specifically addressing this object's impact-risk profile |

## The resolution pipeline

The resolver runs nightly via `make resolve-citations` (in CI: as a
`continue-on-error` step after publish). It has two tiers, run in
sequence:

### Tier 1: MPEC resolution

Every SBDB lookup the nightly already performs returns a `discovery`
block. Commit 1 of Phase 3 mined this block into `discovery_attributions`
— specifically, the `mpec_id` field captured when SBDB references one
(e.g., "MPEC 2004-O02").

The resolver:

1. SELECTs every `discovery_attributions` row that surfaces an `mpec_id`
2. Dedupes to one HTTP fetch per unique MPEC ID (one announcement can
   reference many objects; we only fetch the page once)
3. For each MPEC, GETs the canonical URL
   `https://www.minorplanetcenter.net/mpec/K<yy>/K<yy><half-month><seq>.html`,
   rate-limited to one request per second
4. Parses the HTML for:
   - MPEC ID (verified against the requested one)
   - Issued timestamp (from the `M.P.E.C. ... Issued YYYY MONTH DD, HH:MM UT` header)
   - Featured designations (those bolded in `<b>` tags)
   - All other mentioned designations (provisional + numbered, regex over body text)
5. UPSERTs a `discovery_publications` row keyed on `mpec_id`
6. Inserts `object_publications` edges:
   - Featured designations → `relationship='discovery'`, confidence high
   - Mentioned but not featured → `relationship='follow_up'`, confidence medium

Why this works: the MPEC's `<b>`-tagged designations are the ones the
MPEC is explicitly announcing. Other designations might appear in
observation tables, comparison contexts, or backstory paragraphs — those
are mentions, not declarations.

### Tier 2: ADS bibcode resolution

For every designation in our warehouse with a resolved spkid, the
resolver searches the NASA ADS API with a full-text query for the
designation, requests the top 10 results, and creates edges for each.

`ADS_API_TOKEN` is required (free, manual approval; same token can be
reused across projects since it's tied to the user, not the project).
If the token isn't configured the entire ADS tier is logged as skipped —
the MPEC tier still runs.

The ADS search returns 0–10 docs per designation. Each doc becomes a
`discovery_publications` row (UPSERTed on `ads_bibcode`) plus one
`object_publications` edge with `relationship='follow_up'`.

## The confidence model

The biggest pitfall in any citation graph is false positives: a paper
that mentions designation `2024 YR4` once in a list of 200 other PHAs
isn't really *about* `2024 YR4`. Marking it as a citation lowers the
graph's signal.

We score each edge based on where the designation surfaces in the
publication's metadata:

| Confidence | Criterion |
|---|---|
| **high** | Designation appears in the publication title; or for MPECs, the designation is the `<b>`-tagged announcement target |
| **medium** | Designation appears in the abstract but not the title |
| **low** | Matched only via ADS full-text search (could be a passing mention in a table or footnote) |

The `confidence_reason` column captures the exact basis in plain
English ("designation appears in paper title" / "designation matched
only via ADS full-text search; not in title/abstract") so a downstream
consumer can audit the call.

Display recommendation: surface `high` prominently, `medium`
secondarily, hide or downplay `low` unless the user explicitly opts in.
The UI's `PublicationsPanel` color-codes each card on the left border:
blue for high, gold for medium, gray for low.

## Known limitations

### MPEC discoverability

The Tier 1 MPEC fetcher only acts on `discovery_attributions` rows that
surface an `mpec_id`. SBDB only populates this field reliably for
modern, fully-numbered objects with rich provenance records. For
provisional-designation objects (e.g., `2026 KQ`), SBDB's `discovery`
block often lacks the MPEC reference even when one exists. The MPEC is
still publishable on minorplanetcenter.net, but our resolver doesn't
know to look for it.

A future commit could:
- Scrape MPC's recent-MPEC index page and reverse-map MPEC →
  designation
- Construct candidate MPEC IDs from `discovery_date` + half-month code
  and probe them
- Use the MPC's NEOCP (Near-Earth Object Confirmation Page) for very
  recent discoveries

For now, the MPEC graph backfills slowly — over weeks of nightly runs,
as objects get formally numbered and SBDB updates with MPEC references,
the resolver starts catching them.

### ADS designation matching

ADS full-text search is noisy by design. A search for `"2024 YR4"` can
return papers that mention the designation in:

- A target-of-opportunity table of dozens of PHAs
- A reference list ("based on the orbit of 2024 YR4...")
- A footnote in a survey paper

These are all `low` confidence in our model. We surface them — they're
real citations technically — but the UI deprioritizes them, and a
downstream consumer might choose to filter them out entirely.

Designations with very common formats (`2024 AB` — short and ambiguous
across many catalogues) generate more false positives than longer
formats (`(99942) Apophis` — usually only refers to the one object).

### Cold start

The graph is empty when the resolver first runs against a freshly
populated warehouse. Each nightly run adds whatever's newly resolvable.
Expect the citation count per object to start at zero and grow over the
first few weeks as SBDB metadata catches up and ADS papers accumulate.

## API shape

`GET /api/objects/{designation}/publications` returns:

```json
{
  "spkid": "20099942",
  "designation": "99942",
  "count": 7,
  "items": [
    {
      "publication_id": 42,
      "ads_bibcode": "2024Sci...123..456A",
      "doi": "10.1126/science.abc1234",
      "title": "Spectral characterization of 99942 Apophis...",
      "authors": ["Smith, J.", "..."],
      "publication_date": "2024-09-01",
      "source_url": "https://ui.adsabs.harvard.edu/abs/2024Sci...123..456A",
      "resolved_via": "ads",
      "relationship": "follow_up",
      "confidence": "high",
      "confidence_reason": "designation appears in paper title"
    }
  ]
}
```

Items are ordered: `discovery` first, then `recovery`, then
`risk_assessment`, then `follow_up`. Within each group: most recent
publication date first.

## Future work

Phase 4 (parked) needs the citation graph for the "look up tonight"
sky-view: when a user clicks an asteroid in their dome, the
publications panel is the "what we know about this thing" expansion.
That work consumes the same API endpoint built here; the resolver just
needs to keep filling the graph nightly.

Concrete improvements not in scope today:
- MPC NEOCP scrape for very-fresh discoveries
- Crossref DOI resolution as a third tier (papers without ADS coverage)
- arXiv preprint matching
- Co-citation analysis (which papers cite the same set of objects)
- Survey paper handling (one paper announcing 50 discoveries shows up
  in 50 object pages today; deduplicating the UX is a UI problem more
  than a data problem)
