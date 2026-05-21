"""Curated seed list of well-characterized near-Earth objects.

Most NEOs in the nightly CNEOS close-approach window are small, recently
discovered, and have never been physically characterized — SBDB returns only
their absolute magnitude (H), nothing about composition. To give the warehouse
a backbone of objects with *real* physical data (spectral class, albedo,
measured diameter, rotation period), we always look these up regardless of
whether they have an upcoming close approach.

These are the objects where "what is it made of?" has a real, sourced answer:
spacecraft targets, radar-characterized bodies, and meteor-shower parents. They
are the ones a procedural render can honestly depict rather than guess at.

The runtime only needs the designations; the names + notes document why each
earns a permanent place in the warehouse (and feed future UI copy).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotableNEO:
    designation: str  # SBDB-resolvable primary designation / number
    name: str
    note: str


# Verified against SBDB (2026-05): every entry returns a measured diameter and
# rotation period; all but two carry albedo, and all but one carry a spectral
# class. All are NEOs; most are PHAs.
NOTABLE_NEOS: tuple[NotableNEO, ...] = (
    NotableNEO("99942", "Apophis", "Sq-type PHA; 2029 close pass; the canonical reference object."),
    NotableNEO("101955", "Bennu", "B-type carbonaceous; OSIRIS-REx sample-return target."),
    NotableNEO("162173", "Ryugu", "Cb-type carbonaceous; Hayabusa2 sample-return target."),
    NotableNEO("25143", "Itokawa", "S-type rubble pile; first asteroid sample return (Hayabusa)."),
    NotableNEO("433", "Eros", "S-type; largest near-Earth asteroid; NEAR Shoemaker landing."),
    NotableNEO("65803", "Didymos", "S-type binary; DART kinetic-impact target (Dimorphos)."),
    NotableNEO("3200", "Phaethon", "B/F-type; parent body of the Geminid meteor shower."),
    NotableNEO("4179", "Toutatis", "Sk-type; radar-imaged tumbler with a 176 h rotation."),
    NotableNEO("1620", "Geographos", "S-type; highly elongated, radar-characterized."),
    NotableNEO("1566", "Icarus", "High-eccentricity NEO; classic radar target."),
)


def notable_designations() -> list[str]:
    """SBDB-resolvable designations for the curated set, in canonical order."""
    return [n.designation for n in NOTABLE_NEOS]
