import { Canvas, useFrame, useThree, type ThreeEvent } from '@react-three/fiber';
import { Billboard, Text } from '@react-three/drei';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import * as THREE from 'three';
import { altAzToVector3, equatorialToHorizontal } from '../lib/celestial';
import { hazardColor, markerRadius } from '../lib/skyProjection';
import type {
  ConstellationData,
  SkyObject,
  SkyObjectTrack,
  SkyTrackResponse,
  StarCatalog,
} from '../types';

const STAR_RADIUS = 100;
const OBJECT_RADIUS = 92;
const HORIZON_RADIUS = 100;
const SKY_RADIUS = 140;

// How fast play advances the sky, in sky-hours per real second.
const SPEEDS = [0.5, 2, 6, 24];
// Throttle for the React-state clock used by the starfield + readout. Object
// heads animate every frame off a ref, so they stay smooth regardless.
const STATE_TICK_S = 0.12;
// How far back each object's fading tail reaches, in hours of sky time.
const TAIL_HOURS = 2.5;
const TAIL_POINTS = 9;
// Pitch limits — you can look from just above the horizon up to near the
// zenith, but never down into the ground (which would just be black).
const PITCH_MIN = 3;
const PITCH_MAX = 85;

interface Props {
  objects: SkyObject[];
  track: SkyTrackResponse | null;
  stars: StarCatalog | null;
  constellations: ConstellationData | null;
  lat: number;
  lon: number;
  when: Date;
}

// What the floating tooltip shows on hover — normalized so both the static
// markers and the (hidden) track heads can feed it. clientX/Y are viewport
// coordinates; the tooltip is position:fixed so it follows the cursor.
interface HoverInfo {
  designation: string;
  fullName: string | null;
  pha: boolean | null;
  neo: boolean | null;
  orbitClass: string | null;
  alt: number;
  az: number;
  dist: number;
  clientX: number;
  clientY: number;
}

export default function SkyDome({ objects, track, stars, constellations, lat, lon, when }: Props) {
  const navigate = useNavigate();
  const hasTrack = !!track && track.objects.length > 0;

  const startMs = track ? Date.parse(track.start) : when.getTime();
  const stepMs = (track ? track.step_minutes : 30) * 60_000;
  const steps = track ? track.steps : 1;
  const endMs = startMs + Math.max(0, steps - 1) * stepMs;
  const initialMs = Math.max(startMs, Math.min(endMs, when.getTime()));

  const [displayMs, setDisplayMs] = useState(initialMs);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(2);
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const timeMsRef = useRef(initialMs);

  // New location → new track → reset the clock to "now" inside the new window.
  useEffect(() => {
    timeMsRef.current = initialMs;
    setDisplayMs(initialMs);
    setPlaying(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [track]);

  const displayTime = useMemo(() => new Date(displayMs), [displayMs]);

  function scrub(ms: number) {
    timeMsRef.current = ms;
    setDisplayMs(ms);
  }

  return (
    <div className="sky-dome-wrap">
      <div className="sky-dome-canvas-box">
        <Canvas camera={{ fov: 60, position: [0, 0, 0.001], near: 0.01, far: 500 }}>
          <SkyBackdrop />
          <LookControls />
          {hasTrack && playing && (
            <Clock
              timeMsRef={timeMsRef}
              playing={playing}
              speed={speed}
              startMs={startMs}
              endMs={endMs}
              onTick={setDisplayMs}
            />
          )}
          {stars && <Stars stars={stars} lat={lat} lon={lon} when={displayTime} />}
          {constellations && (
            <Constellations data={constellations} lat={lat} lon={lon} when={displayTime} />
          )}
          {hasTrack ? (
            <>
              <TrackTails track={track!} startMs={startMs} stepMs={stepMs} timeMsRef={timeMsRef} />
              <TrackHeads
                track={track!}
                startMs={startMs}
                stepMs={stepMs}
                timeMsRef={timeMsRef}
                onHover={setHover}
                onSelect={(designation) =>
                  navigate(`/objects/${encodeURIComponent(designation)}`)
                }
              />
            </>
          ) : (
            <Asteroids
              objects={objects}
              onHover={setHover}
              onSelect={(o) => navigate(`/objects/${encodeURIComponent(o.designation)}`)}
            />
          )}
          <HorizonAndGround />
          <Cardinals />
        </Canvas>
        {hover && <DomeTooltip info={hover} />}
      </div>

      {hasTrack && (
        <TimeControls
          playing={playing}
          onPlayToggle={() => setPlaying((p) => !p)}
          speed={speed}
          onSpeed={setSpeed}
          startMs={startMs}
          endMs={endMs}
          displayMs={displayMs}
          onScrub={scrub}
        />
      )}

      <div className="sky-dome-readout">
        <span className="muted">
          Drag to look around · scroll to zoom · hover an object for details ·
          click to open it{hasTrack && ' · press play to watch the sky move'}.
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Time controls — play/pause, scrubber, speed.
// ---------------------------------------------------------------------------

function TimeControls({
  playing,
  onPlayToggle,
  speed,
  onSpeed,
  startMs,
  endMs,
  displayMs,
  onScrub,
}: {
  playing: boolean;
  onPlayToggle: () => void;
  speed: number;
  onSpeed: (s: number) => void;
  startMs: number;
  endMs: number;
  displayMs: number;
  onScrub: (ms: number) => void;
}) {
  const label = new Date(displayMs).toUTCString().replace(' GMT', ' UTC');
  return (
    <div className="time-controls">
      <button
        type="button"
        className="time-play"
        onClick={onPlayToggle}
        aria-label={playing ? 'Pause' : 'Play'}
      >
        {playing ? '❚❚' : '►'}
      </button>
      <input
        type="range"
        className="time-slider"
        min={startMs}
        max={endMs}
        step={60_000}
        value={displayMs}
        onChange={(e) => onScrub(Number(e.target.value))}
      />
      <span className="time-label mono">{label}</span>
      <label className="time-speed">
        <span className="muted">speed</span>
        <select value={speed} onChange={(e) => onSpeed(Number(e.target.value))}>
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              {s}h/s
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Clock — advances the play head (a ref) every frame, and pushes a throttled
// copy to React state so the starfield + readout follow without re-rendering
// 60×/second.
// ---------------------------------------------------------------------------

function Clock({
  timeMsRef,
  playing,
  speed,
  startMs,
  endMs,
  onTick,
}: {
  timeMsRef: React.MutableRefObject<number>;
  playing: boolean;
  speed: number;
  startMs: number;
  endMs: number;
  onTick: (ms: number) => void;
}) {
  const acc = useRef(0);
  useFrame((_, delta) => {
    if (!playing) return;
    let t = timeMsRef.current + delta * speed * 3_600_000;
    if (t > endMs) t = startMs; // loop the window
    timeMsRef.current = t;
    acc.current += delta;
    if (acc.current >= STATE_TICK_S) {
      acc.current = 0;
      onTick(t);
    }
  });
  return null;
}

// ---------------------------------------------------------------------------
// Look controls — camera fixed at origin, drag changes view yaw/pitch. Pitch
// is clamped to the visible sky (no looking down into the ground). Also keeps
// the camera aspect synced to the real canvas size each frame.
// ---------------------------------------------------------------------------

function LookControls() {
  const { camera, gl } = useThree();
  const yaw = useRef(180); // start looking south
  const pitch = useRef(25);
  const fov = useRef(60);
  const dragging = useRef(false);
  const last = useRef({ x: 0, y: 0 });

  useEffect(() => {
    const el = gl.domElement;
    const onDown = (e: PointerEvent) => {
      dragging.current = true;
      last.current = { x: e.clientX, y: e.clientY };
    };
    const onUp = () => {
      dragging.current = false;
    };
    const onMove = (e: PointerEvent) => {
      if (!dragging.current) return;
      const dx = e.clientX - last.current.x;
      const dy = e.clientY - last.current.y;
      last.current = { x: e.clientX, y: e.clientY };
      yaw.current = (yaw.current - dx * 0.18) % 360;
      pitch.current = Math.max(PITCH_MIN, Math.min(PITCH_MAX, pitch.current + dy * 0.18));
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      fov.current = Math.max(28, Math.min(90, fov.current + e.deltaY * 0.03));
      const cam = camera as THREE.PerspectiveCamera;
      cam.fov = fov.current;
      cam.updateProjectionMatrix();
    };
    el.addEventListener("pointerdown", onDown);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointermove", onMove);
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      el.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointermove", onMove);
      el.removeEventListener("wheel", onWheel);
    };
  }, [camera, gl]);

  useFrame(() => {
    const cam = camera as THREE.PerspectiveCamera;
    const el = gl.domElement;
    const w = el.clientWidth;
    const h = el.clientHeight;
    if (h > 0) {
      const aspect = w / h;
      if (Math.abs(cam.aspect - aspect) > 1e-3) {
        cam.aspect = aspect;
        cam.updateProjectionMatrix();
      }
    }
    const [x, y, z] = altAzToVector3(pitch.current, yaw.current, 1);
    cam.position.set(0, 0, 0);
    cam.lookAt(x, y, z);
  });

  return null;
}

// ---------------------------------------------------------------------------
// Sky backdrop — a big inward-facing sphere with a vertical gradient so empty
// sky reads as sky (dark at the zenith, faint glow at the horizon).
// ---------------------------------------------------------------------------

function SkyBackdrop() {
  const texture = useMemo(() => {
    const c = document.createElement("canvas");
    c.width = 4;
    c.height = 256;
    const ctx = c.getContext("2d")!;
    const g = ctx.createLinearGradient(0, 0, 0, 256);
    g.addColorStop(0.0, "#060912"); // zenith
    g.addColorStop(0.42, "#0a1322");
    g.addColorStop(0.5, "#16263f"); // horizon glow
    g.addColorStop(0.58, "#080e18");
    g.addColorStop(1.0, "#04060b"); // nadir
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 4, 256);
    const tex = new THREE.CanvasTexture(c);
    tex.needsUpdate = true;
    return tex;
  }, []);

  return (
    <mesh>
      <sphereGeometry args={[SKY_RADIUS, 32, 32]} />
      <meshBasicMaterial map={texture} side={THREE.BackSide} depthWrite={false} />
    </mesh>
  );
}

// ---------------------------------------------------------------------------
// Stars — three brightness tiers as separate Points clouds.
// ---------------------------------------------------------------------------

function Stars({ stars, lat, lon, when }: { stars: StarCatalog; lat: number; lon: number; when: Date }) {
  const tiers = useMemo(() => {
    const bins: Record<string, number[]> = { bright: [], mid: [], faint: [] };
    for (const [ra, dec, mag] of stars.stars) {
      const { altitude_deg, azimuth_deg } = equatorialToHorizontal(ra, dec, lat, lon, when);
      if (altitude_deg < -2) continue;
      const [x, y, z] = altAzToVector3(altitude_deg, azimuth_deg, STAR_RADIUS);
      const bin = mag < 2 ? "bright" : mag < 3.5 ? "mid" : "faint";
      bins[bin].push(x, y, z);
    }
    return bins;
  }, [stars, lat, lon, when]);

  return (
    <>
      <StarPoints positions={tiers.bright} size={2.6} opacity={1} />
      <StarPoints positions={tiers.mid} size={1.7} opacity={0.9} />
      <StarPoints positions={tiers.faint} size={1.0} opacity={0.7} />
    </>
  );
}

function StarPoints({ positions, size, opacity }: { positions: number[]; size: number; opacity: number }) {
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    return g;
  }, [positions]);
  if (positions.length === 0) return null;
  return (
    <points geometry={geometry}>
      <pointsMaterial
        color="#dfe8ff"
        size={size}
        sizeAttenuation={false}
        transparent
        opacity={opacity}
      />
    </points>
  );
}

// ---------------------------------------------------------------------------
// Constellation lines.
// ---------------------------------------------------------------------------

function Constellations({ data, lat, lon, when }: { data: ConstellationData; lat: number; lon: number; when: Date }) {
  const geometry = useMemo(() => {
    const verts: number[] = [];
    for (const con of data.constellations) {
      for (const seg of con.segments) {
        for (let i = 0; i < seg.length - 1; i++) {
          const a = horiz(seg[i], lat, lon, when);
          const b = horiz(seg[i + 1], lat, lon, when);
          if (a.altitude_deg < 0 || b.altitude_deg < 0) continue;
          verts.push(...altAzToVector3(a.altitude_deg, a.azimuth_deg, STAR_RADIUS));
          verts.push(...altAzToVector3(b.altitude_deg, b.azimuth_deg, STAR_RADIUS));
        }
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3));
    return g;
  }, [data, lat, lon, when]);

  return (
    <lineSegments geometry={geometry}>
      <lineBasicMaterial color="#2c4a6e" transparent opacity={0.45} />
    </lineSegments>
  );
}

function horiz(p: [number, number], lat: number, lon: number, when: Date) {
  return equatorialToHorizontal(p[0], p[1], lat, lon, when);
}

// ---------------------------------------------------------------------------
// Track tails — a short fading comet-tail behind each object showing its
// recent motion. Rebuilt every frame into one merged line (one draw call),
// brightness-faded from the head back so old positions dim toward the sky.
// ---------------------------------------------------------------------------

function TrackTails({
  track,
  startMs,
  stepMs,
  timeMsRef,
}: {
  track: SkyTrackResponse;
  startMs: number;
  stepMs: number;
  timeMsRef: React.MutableRefObject<number>;
}) {
  const n = track.objects.length;
  const segsPerObj = TAIL_POINTS - 1;
  const colors = useMemo(
    () => track.objects.map((o) => new THREE.Color(hazardColor(o))),
    [track],
  );
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(n * segsPerObj * 2 * 3), 3));
    g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(n * segsPerObj * 2 * 3), 3));
    return g;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [track]);

  const tailMs = TAIL_HOURS * 3_600_000;

  useFrame(() => {
    const t = timeMsRef.current;
    const pos = geometry.attributes.position.array as Float32Array;
    const col = geometry.attributes.color.array as Float32Array;
    let seg = 0;
    for (let oi = 0; oi < n; oi++) {
      const samples = track.objects[oi].samples;
      const c = colors[oi];
      // Sample TAIL_POINTS positions from (t - tail) up to t (head last).
      const pts: { x: number; y: number; z: number; alt: number }[] = [];
      for (let k = 0; k < TAIL_POINTS; k++) {
        const frac = k / (TAIL_POINTS - 1); // 0 oldest .. 1 head
        pts.push(sampleAt(samples, startMs, stepMs, t - tailMs * (1 - frac)));
      }
      for (let k = 0; k < segsPerObj; k++) {
        const a = pts[k];
        const b = pts[k + 1];
        const base = seg * 6;
        if (a.alt >= track.min_altitude_deg && b.alt >= track.min_altitude_deg) {
          pos[base] = a.x * OBJECT_RADIUS;
          pos[base + 1] = a.y * OBJECT_RADIUS;
          pos[base + 2] = a.z * OBJECT_RADIUS;
          pos[base + 3] = b.x * OBJECT_RADIUS;
          pos[base + 4] = b.y * OBJECT_RADIUS;
          pos[base + 5] = b.z * OBJECT_RADIUS;
          const fa = k / segsPerObj; // brightness ramps up toward the head
          const fb = (k + 1) / segsPerObj;
          col[base] = c.r * fa;
          col[base + 1] = c.g * fa;
          col[base + 2] = c.b * fa;
          col[base + 3] = c.r * fb;
          col[base + 4] = c.g * fb;
          col[base + 5] = c.b * fb;
        } else {
          // Hidden: collapse to a zero-length segment at the origin.
          for (let z = 0; z < 6; z++) pos[base + z] = 0;
          for (let z = 0; z < 6; z++) col[base + z] = 0;
        }
        seg++;
      }
    }
    geometry.attributes.position.needsUpdate = true;
    geometry.attributes.color.needsUpdate = true;
  });

  return (
    <lineSegments geometry={geometry}>
      <lineBasicMaterial vertexColors transparent opacity={0.85} blending={THREE.AdditiveBlending} />
    </lineSegments>
  );
}

// ---------------------------------------------------------------------------
// Track heads — the animated "where it is now" glow. Positions update every
// frame off the play-head ref, interpolating between samples via direction
// vectors (so azimuth wrap is a non-issue).
// ---------------------------------------------------------------------------

function TrackHeads({
  track,
  startMs,
  stepMs,
  timeMsRef,
  onHover,
  onSelect,
}: {
  track: SkyTrackResponse;
  startMs: number;
  stepMs: number;
  timeMsRef: React.MutableRefObject<number>;
  onHover: (info: HoverInfo | null) => void;
  onSelect: (designation: string) => void;
}) {
  const glow = useMemo(glowTexture, []);
  const groupRefs = useRef<(THREE.Group | null)[]>([]);

  const hoverInfo = (obj: SkyObjectTrack, e: ThreeEvent<PointerEvent>): HoverInfo => {
    const r = readoutAt(obj, startMs, stepMs, timeMsRef.current);
    return {
      designation: obj.designation,
      fullName: obj.full_name,
      pha: obj.pha,
      neo: obj.neo,
      orbitClass: obj.orbit_class,
      alt: r.alt,
      az: r.az,
      dist: r.dist,
      clientX: e.clientX,
      clientY: e.clientY,
    };
  };

  useFrame(() => {
    const t = timeMsRef.current;
    track.objects.forEach((obj, idx) => {
      const g = groupRefs.current[idx];
      if (!g) return;
      const s = sampleAt(obj.samples, startMs, stepMs, t);
      if (s.alt < track.min_altitude_deg) {
        g.visible = false;
        return;
      }
      g.visible = true;
      g.position.set(s.x * OBJECT_RADIUS, s.y * OBJECT_RADIUS, s.z * OBJECT_RADIUS);
    });
  });

  return (
    <>
      {track.objects.map((obj, idx) => {
        const color = hazardColor(obj);
        const scale = 1.4 + markerRadius(obj) * 1.6;
        return (
          <group
            key={obj.spkid}
            ref={(el) => (groupRefs.current[idx] = el)}
            onPointerOver={(e) => {
              e.stopPropagation();
              document.body.style.cursor = "pointer";
              onHover(hoverInfo(obj, e));
            }}
            onPointerMove={(e) => {
              e.stopPropagation();
              onHover(hoverInfo(obj, e));
            }}
            onPointerOut={() => {
              document.body.style.cursor = "auto";
              onHover(null);
            }}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(obj.designation);
            }}
          >
            <sprite scale={[scale, scale, scale]}>
              <spriteMaterial
                map={glow}
                color={color}
                transparent
                depthWrite={false}
                blending={THREE.AdditiveBlending}
              />
            </sprite>
          </group>
        );
      })}
    </>
  );
}

// ---------------------------------------------------------------------------
// Asteroids — static glow fallback while the track loads.
// ---------------------------------------------------------------------------

function Asteroids({
  objects,
  onHover,
  onSelect,
}: {
  objects: SkyObject[];
  onHover: (info: HoverInfo | null) => void;
  onSelect: (o: SkyObject) => void;
}) {
  const glow = useMemo(glowTexture, []);
  return (
    <>
      {objects.map((o) => {
        const pos = altAzToVector3(o.altitude_deg, o.azimuth_deg, OBJECT_RADIUS);
        const color = hazardColor(o);
        const scale = 1.4 + markerRadius(o) * 1.6;
        const info = (e: ThreeEvent<PointerEvent>): HoverInfo => ({
          designation: o.designation,
          fullName: o.full_name,
          pha: o.pha,
          neo: o.neo,
          orbitClass: o.orbit_class,
          alt: o.altitude_deg,
          az: o.azimuth_deg,
          dist: o.distance_au,
          clientX: e.clientX,
          clientY: e.clientY,
        });
        return (
          <group
            key={o.spkid}
            position={pos}
            onPointerOver={(e) => {
              e.stopPropagation();
              document.body.style.cursor = "pointer";
              onHover(info(e));
            }}
            onPointerMove={(e) => {
              e.stopPropagation();
              onHover(info(e));
            }}
            onPointerOut={() => {
              document.body.style.cursor = "auto";
              onHover(null);
            }}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(o);
            }}
          >
            <sprite scale={[scale, scale, scale]}>
              <spriteMaterial
                map={glow}
                color={color}
                transparent
                depthWrite={false}
                blending={THREE.AdditiveBlending}
              />
            </sprite>
          </group>
        );
      })}
    </>
  );
}

// ---------------------------------------------------------------------------
// Horizon ring + ground disc + cardinal labels.
// ---------------------------------------------------------------------------

function HorizonAndGround() {
  const ringGeo = useMemo(() => {
    const pts: number[] = [];
    for (let az = 0; az <= 360; az += 2) {
      pts.push(...altAzToVector3(0, az, HORIZON_RADIUS));
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    return g;
  }, []);

  const groundTex = useMemo(() => {
    const c = document.createElement("canvas");
    c.width = c.height = 128;
    const ctx = c.getContext("2d")!;
    // Radial: faint warmth at the horizon rim fading to near-black underfoot,
    // so the ground reads as ground rather than a black hole.
    const g = ctx.createRadialGradient(64, 64, 4, 64, 64, 64);
    g.addColorStop(0.0, "#04060b"); // nadir (center)
    g.addColorStop(0.82, "#080d16");
    g.addColorStop(1.0, "#11192a"); // horizon rim
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }, []);

  return (
    <>
      <lineLoop geometry={ringGeo}>
        <lineBasicMaterial color="#5a7596" />
      </lineLoop>
      <mesh position={[0, -0.4, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[HORIZON_RADIUS, 96]} />
        <meshBasicMaterial map={groundTex} side={THREE.DoubleSide} />
      </mesh>
    </>
  );
}

function Cardinals() {
  const dirs: [string, number][] = [
    ["N", 0],
    ["E", 90],
    ["S", 180],
    ["W", 270],
  ];
  return (
    <>
      {dirs.map(([label, az]) => {
        const pos = altAzToVector3(2.5, az, HORIZON_RADIUS * 0.97);
        return (
          <Billboard key={label} position={pos}>
            <Text fontSize={5} color="#9fb2cc" anchorX="center" anchorY="middle">
              {label}
            </Text>
          </Billboard>
        );
      })}
    </>
  );
}

// ---------------------------------------------------------------------------
// Hover tooltip — a small HTML card that follows the cursor (position:fixed,
// pointer-events:none so it never blocks the canvas).
// ---------------------------------------------------------------------------

function DomeTooltip({ info }: { info: HoverInfo }) {
  const kind = info.pha
    ? 'Potentially hazardous'
    : info.neo
      ? 'Near-Earth object'
      : info.orbitClass || 'Object';
  return (
    <div
      className="dome-tooltip"
      style={{ left: info.clientX + 14, top: info.clientY + 14 }}
    >
      <div className="dome-tooltip-name mono">{info.designation}</div>
      {info.fullName && info.fullName !== info.designation && (
        <div className="dome-tooltip-full">{info.fullName}</div>
      )}
      <div className="dome-tooltip-meta">
        <span
          className="dome-tooltip-dot"
          style={{ background: hazardColor(info) }}
        />
        {kind}
      </div>
      <div className="dome-tooltip-meta muted">
        alt {info.alt.toFixed(1)}° · az {info.az.toFixed(1)}° ·{' '}
        {info.dist.toFixed(3)} AU
      </div>
      <div className="dome-tooltip-hint muted">click to open its record</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------

let _glowTex: THREE.CanvasTexture | null = null;

/** Soft white radial-gradient sprite, tinted per object — reads as a glowing
 * point of light rather than a flat blob. Built once, shared. */
function glowTexture(): THREE.CanvasTexture {
  if (_glowTex) return _glowTex;
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const ctx = c.getContext("2d")!;
  const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0.0, "rgba(255,255,255,1)");
  g.addColorStop(0.22, "rgba(255,255,255,0.85)");
  g.addColorStop(0.5, "rgba(255,255,255,0.3)");
  g.addColorStop(1.0, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 64, 64);
  _glowTex = new THREE.CanvasTexture(c);
  return _glowTex;
}

/** Interpolate an object's position at time `tMs` via direction vectors,
 * returning a unit direction (x,y,z), altitude, and distance. */
function sampleAt(
  samples: [number, number, number][],
  startMs: number,
  stepMs: number,
  tMs: number,
) {
  const len = samples.length;
  const f = Math.max(0, Math.min(len - 1, (tMs - startMs) / stepMs));
  const i = Math.floor(f);
  const j = Math.min(len - 1, i + 1);
  const frac = f - i;
  const [a0, z0, d0] = samples[i];
  const [a1, z1, d1] = samples[j];
  const v0 = altAzToVector3(a0, z0, 1);
  const v1 = altAzToVector3(a1, z1, 1);
  const x = v0[0] + (v1[0] - v0[0]) * frac;
  const y = v0[1] + (v1[1] - v0[1]) * frac;
  const z = v0[2] + (v1[2] - v0[2]) * frac;
  const mag = Math.hypot(x, y, z) || 1;
  const ny = y / mag;
  const alt = (Math.asin(Math.max(-1, Math.min(1, ny))) * 180) / Math.PI;
  const dist = d0 + (d1 - d0) * frac;
  return { x: x / mag, y: ny, z: z / mag, alt, dist };
}

/** Alt/az/distance for the hover readout at the current time. */
function readoutAt(
  obj: SkyObjectTrack,
  startMs: number,
  stepMs: number,
  tMs: number,
): { alt: number; az: number; dist: number } {
  const s = sampleAt(obj.samples, startMs, stepMs, tMs);
  let az = (Math.atan2(s.x, -s.z) * 180) / Math.PI;
  if (az < 0) az += 360;
  return { alt: s.alt, az, dist: s.dist };
}
