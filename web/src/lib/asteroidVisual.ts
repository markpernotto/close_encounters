// Procedural rendering for near-Earth objects: maps measured taxonomy +
// albedo to a visual surface style. The position of every claim here is real
// — spectral class and geometric albedo are measured quantities from SBDB —
// and the color/brightness follow the standard asteroid-taxonomy → mineralogy
// associations. Where we have no measurement we say so and render generically
// rather than invent a composition. See docs/PROCEDURAL_RENDERING.md.

export type TaxGroup =
  | 'carbonaceous'
  | 'stony'
  | 'metallic'
  | 'enstatite'
  | 'basaltic'
  | 'primitive'
  | 'organic'
  | 'unknown';

export interface AsteroidVisual {
  group: TaxGroup;
  groupLabel: string; // human label, e.g. "S-type (stony)"
  baseHex: string; // mid surface tone (after albedo adjustment)
  litHex: string; // sunlit highlight
  shadowHex: string; // limb / terminator
  roughness: number; // 0..1 — texture frequency/strength
  description: string; // what it's (likely) made of
  characterized: boolean; // did we have a real spectral class or albedo?
}

// Representative surface tones per taxonomy group at a "typical" albedo for
// that group. Albedo, when measured, then brightens/darkens these.
const GROUP_BASE: Record<TaxGroup, { hex: string; rough: number; label: string; blurb: string }> = {
  carbonaceous: {
    hex: '#4a4a52',
    rough: 0.85,
    label: 'C-type (carbonaceous)',
    blurb:
      'Primitive carbon-rich rock — among the darkest material in the solar system, little changed since its formation.',
  },
  stony: {
    hex: '#a07c54',
    rough: 0.7,
    label: 'S-type (stony)',
    blurb:
      'Silicate rock of olivine and pyroxene with metallic flecks; space weathering reddens the surface over time.',
  },
  metallic: {
    hex: '#8c909a',
    rough: 0.45,
    label: 'M-type (metallic)',
    blurb:
      'Nickel–iron metal, likely the exposed core of a shattered larger body.',
  },
  enstatite: {
    hex: '#cbc7bd',
    rough: 0.55,
    label: 'E-type (enstatite)',
    blurb: 'Bright enstatite-rich rock with one of the highest albedos known.',
  },
  basaltic: {
    hex: '#9a7160',
    rough: 0.65,
    label: 'V-type (basaltic)',
    blurb:
      'Basaltic, pyroxene-rich crust — fragments of a differentiated body (the Vesta family).',
  },
  primitive: {
    hex: '#4c4038',
    rough: 0.8,
    label: 'P-type (primitive)',
    blurb: 'Dark, reddish, organic- and carbon-rich primitive material.',
  },
  organic: {
    hex: '#5a3e34',
    rough: 0.8,
    label: 'D-type (organic-rich)',
    blurb:
      'Very dark and very red — rich in organics and ices, like cometary and Trojan bodies.',
  },
  unknown: {
    hex: '#7a766f',
    rough: 0.7,
    label: 'Uncharacterized',
    blurb:
      'No spectral type on record — composition unknown, shown as a generic rocky body.',
  },
};

/** Classify a taxonomy string (Tholen or SMASS, e.g. "Sq", "Cb", "S(IV)",
 * "B", "F", "X") into a coarse mineralogical group by its leading letters. */
export function classifyTaxonomy(specClass: string | null | undefined): TaxGroup {
  if (!specClass) return 'unknown';
  const s = specClass.trim().toUpperCase();
  const c = s.charAt(0);
  // Two-letter / complex cases first.
  if (c === 'B' || c === 'F' || c === 'G') return 'carbonaceous'; // B/F/G are C-complex
  if (c === 'C') return 'carbonaceous';
  if (c === 'S' || c === 'Q' || c === 'A' || c === 'R') return 'stony';
  if (c === 'M') return 'metallic';
  if (c === 'E') return 'enstatite';
  if (c === 'P') return 'primitive';
  if (c === 'V') return 'basaltic';
  if (c === 'D' || c === 'T') return 'organic';
  if (c === 'X' || c === 'K' || c === 'L') return 'metallic'; // X-complex, metal-ish grey
  return 'unknown';
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

function rgbToHex(r: number, g: number, b: number): string {
  const cl = (n: number) => Math.max(0, Math.min(255, Math.round(n)));
  return (
    '#' +
    [cl(r), cl(g), cl(b)]
      .map((n) => n.toString(16).padStart(2, '0'))
      .join('')
  );
}

function scale(hex: string, factor: number): string {
  const [r, g, b] = hexToRgb(hex);
  return rgbToHex(r * factor, g * factor, b * factor);
}

/** Albedo → brightness multiplier on the group's base tone. Typical asteroid
 * albedos run ~0.03 (very dark) to ~0.5 (very bright); map that to a 0.6–1.45
 * multiplier so two same-class objects with different albedos look different. */
function albedoFactor(albedo: number): number {
  const t = Math.max(0, Math.min(1, (albedo - 0.03) / (0.5 - 0.03)));
  return 0.6 + t * 0.85;
}

function albedoPhrase(albedo: number): string {
  if (albedo < 0.06) return `extremely dark (albedo ${albedo.toFixed(3)}, reflecting almost no light)`;
  if (albedo < 0.12) return `dark (albedo ${albedo.toFixed(3)})`;
  if (albedo < 0.25) return `moderately reflective (albedo ${albedo.toFixed(2)})`;
  return `bright (albedo ${albedo.toFixed(2)})`;
}

export function asteroidVisual(
  specClass: string | null | undefined,
  albedo: number | null | undefined,
): AsteroidVisual {
  const group = classifyTaxonomy(specClass);
  const def = GROUP_BASE[group];

  // Brightness from measured albedo when available; otherwise leave the
  // group's representative tone as-is.
  const factor = albedo != null && albedo > 0 ? albedoFactor(albedo) : 1;
  const baseHex = scale(def.hex, factor);

  let description = def.blurb;
  if (albedo != null && albedo > 0) {
    description += ` Its surface is ${albedoPhrase(albedo)}.`;
  }

  return {
    group,
    groupLabel: def.label,
    baseHex,
    litHex: scale(baseHex, 1.55),
    shadowHex: scale(baseHex, 0.4),
    roughness: def.rough,
    description,
    characterized: !!specClass || (albedo != null && albedo > 0),
  };
}

/** Deterministic small integer seed from a string, for stable per-object
 * surface texture (so the same object always renders the same way). */
export function seedFromString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) & 0xffff;
  }
  return h % 100;
}
