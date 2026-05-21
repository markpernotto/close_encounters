# Procedural object rendering

Each object's detail page shows a small procedural "portrait" of the body. It
uses **no image assets** — the picture is derived entirely from the object's
*measured* physical properties. This documents the mapping and, importantly,
where it stops (we render what we know and say so when we don't).

Implementation: [`web/src/lib/asteroidVisual.ts`](../web/src/lib/asteroidVisual.ts)
(the pure mapping) and
[`web/src/components/AsteroidRender.tsx`](../web/src/components/AsteroidRender.tsx)
(the SVG).

## Inputs (all from SBDB, via `mart_objects_current`)

| Property | Role in the render |
|---|---|
| `spec_class` (Tholen / SMASS taxonomy) | Picks the mineralogical group → base hue |
| `albedo` (geometric) | Brightens/darkens the base tone (real reflectivity) |
| `diameter_km` / `diameter_estimate_km` | Stated size caption |
| `rotation_period_h` | Stated spin caption |

Most close-approaching NEOs carry only an absolute magnitude `H`; they render
as a generic uncharacterized rock with a note saying so. The objects with real
taxonomy come from the curated seed set (see `etl/seeds.py`).

## Taxonomy → mineralogy → color

Classification is by the leading letter(s) of the spectral class, following the
standard complexes:

| Group | Classes | Composition | Look |
|---|---|---|---|
| Carbonaceous | C, Cb, Cg, Ch, B, F, G | Primitive carbon-rich | Very dark, neutral-to-bluish grey |
| Stony | S, Sq, Sk, Sr, Q, A, R | Olivine/pyroxene silicate + metal | Tan/brown, reddened by space weathering |
| Metallic | M, X, Xc, Xk, K, L | Nickel–iron | Metallic grey |
| Enstatite | E | Enstatite | Bright, light grey |
| Basaltic | V | Pyroxene-rich crust | Reddish, moderately bright |
| Primitive | P | Organic/carbon-rich | Dark reddish |
| Organic | D, T | Organics + ices | Very dark, very red |
| Unknown | (none) | — | Neutral grey, flagged generic |

The base hue is the group's representative tone. The **measured albedo** then
scales brightness (≈0.03 → 0.6×, ≈0.5 → 1.45×), so two S-types with different
albedos don't render identically — e.g. Toutatis (albedo 0.40) is visibly
brighter than Apophis (0.35), and Bennu (0.044) is nearly black.

## What is real vs. illustrative

- **Real:** the group classification, the hue family it implies, and the
  surface brightness (driven by measured albedo). The size and rotation
  captions are measured values.
- **Illustrative:** the fractal-noise surface mottling (a `feTurbulence`
  texture, seeded deterministically from the designation) and the spherical
  shape. Real asteroids are irregular; the texture is decorative, not a shape
  model.

We deliberately do **not** invent a spectral type or albedo for objects that
lack one — they get a generic rock and an explicit "not a measurement" note.
This keeps the render honest: it depicts what the data supports and nothing
more.
