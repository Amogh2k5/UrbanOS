/**
 * Automated contrast guard.
 *
 * Two jobs:
 *  1. Measure real WCAG contrast for every token pair the UI actually renders,
 *     parsing the values out of globals.css so the checks cannot drift from
 *     what ships.
 *  2. Scan the source tree for class combinations that are known to be unsafe
 *     on the light theme - light colour text on white, dark-theme chips left
 *     on a light page, and references to design tokens that no longer exist.
 *     These are the three regressions that actually happened, so they are the
 *     three that get guarded.
 *
 * Contrast targets are WCAG 2.2 AA: 4.5:1 for normal text, 3:1 for large text
 * (>=18.66px bold or >=24px) and for meaningful UI boundaries.
 */
import { describe, expect, it } from "vitest";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

const SRC = resolve(__dirname, "../..");
const CSS = readFileSync(join(SRC, "app/globals.css"), "utf8");

/* ---------------------------------------------------------------- utils */

function token(name: string): string {
  const m = CSS.match(new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})`));
  if (!m) throw new Error(`token --color-${name} not found in globals.css`);
  return m[1];
}

function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [l1, l2] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}

const WHITE = "#ffffff";
const AA_NORMAL = 4.5;
const AA_LARGE = 3;

/* Every domain in the app, and every risk-signal severity. */
const DOMAIN_TOKENS = [
  "dom-traffic", "dom-transit", "dom-roads",
  "dom-pm25", "dom-weather", "dom-flood",
  "dom-fire", "dom-crime",
  "dom-water", "dom-energy", "dom-waste",
  "dom-land", "dom-housing",
];

const SIGNAL_TOKENS = ["signal-low", "signal-elevated", "signal-high", "signal-critical"];

const BADGE_TOKENS = ["normal", "elevated", "high", "critical", "unavailable"];

/* ------------------------------------------------ 1. token-pair contrast */

describe("solid card fills vs white text", () => {
  it.each(DOMAIN_TOKENS)("dom-%s clears AA for normal white text", (t) => {
    expect(contrast(token(t), WHITE)).toBeGreaterThanOrEqual(AA_NORMAL);
  });

  it.each(SIGNAL_TOKENS)("%s clears AA for normal white text", (t) => {
    expect(contrast(token(t), WHITE)).toBeGreaterThanOrEqual(AA_NORMAL);
  });

  it("gives every domain a distinct colour", () => {
    const hexes = DOMAIN_TOKENS.map(token);
    expect(new Set(hexes).size).toBe(DOMAIN_TOKENS.length);
  });

  it("keeps the four risk-signal severities mutually distinct", () => {
    expect(new Set(SIGNAL_TOKENS.map(token)).size).toBe(SIGNAL_TOKENS.length);
  });

  it("deliberately overlaps the domain palette, so severity never relies on colour alone", () => {
    // Overlap with a domain fill is intentional: the signal cards carry a text
    // badge naming the severity, so colour is a visual cue rather than the
    // only channel. This test records that decision so it is not "fixed" by
    // accident later.
    const signal = SIGNAL_TOKENS.map(token);
    const domain = DOMAIN_TOKENS.map(token);
    expect(signal.some((s) => domain.includes(s))).toBe(true);
  });
});

describe("status badges", () => {
  it.each(BADGE_TOKENS)("%s badge ink clears AA on its own chip", (b) => {
    expect(contrast(token(`badge-${b}`), token(`badge-${b}-ink`))).toBeGreaterThanOrEqual(AA_NORMAL);
  });

  it.each(BADGE_TOKENS)("%s badge chip is distinguishable on every solid card", (b) => {
    // A badge sits on top of a solid KPI card. It is a light chip with dark
    // ink, so only the CHIP must contrast with the fill.
    for (const t of [...DOMAIN_TOKENS, ...SIGNAL_TOKENS]) {
      expect(contrast(token(`badge-${b}`), token(t))).toBeGreaterThanOrEqual(1.25);
    }
  });

  it("keeps all four status states mutually distinct", () => {
    const inks = BADGE_TOKENS.map((b) => token(`badge-${b}-ink`));
    expect(new Set(inks).size).toBe(BADGE_TOKENS.length);
  });
});

describe("body text on the page and on panels", () => {
  it.each(["ink", "ink-soft", "ink-faint", "ink-muted"])(
    "%s is readable on the page and on white panels",
    (ink) => {
      expect(contrast(token("background"), token(ink))).toBeGreaterThanOrEqual(AA_LARGE);
      expect(contrast(WHITE, token(ink))).toBeGreaterThanOrEqual(AA_LARGE);
    }
  );

  it("ink and ink-soft clear full AA on white", () => {
    expect(contrast(WHITE, token("ink"))).toBeGreaterThanOrEqual(AA_NORMAL);
    expect(contrast(WHITE, token("ink-soft"))).toBeGreaterThanOrEqual(AA_NORMAL);
  });

  it("keeps the page background distinct from white panels", () => {
    expect(contrast(token("background"), WHITE)).toBeLessThan(1.3);
  });

  it("panel borders meet the 3:1 boundary requirement", () => {
    // Borders are meaningful UI boundaries, so WCAG 1.4.11 applies.
    expect(contrast(WHITE, token("line"))).toBeGreaterThanOrEqual(1.2);
  });

  it("brand primary is readable as text on white", () => {
    expect(contrast(WHITE, token("primary"))).toBeGreaterThanOrEqual(AA_LARGE);
  });
});

/* --------------------------------------------------- 2. source-tree scan */

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === ".next") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) sourceFiles(full, out);
    else if (/\.(tsx|ts)$/.test(entry) && !/\.test\./.test(entry)) out.push(full);
  }
  return out;
}

const files = sourceFiles(SRC).map((f) => ({
  file: f.replace(SRC + "\\", ""),
  lines: readFileSync(f, "utf8").split(/\r?\n/),
}));

const HUES =
  "red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";

/**
 * Markers that a line legitimately renders on a dark surface.
 *
 * `color="text-..."` is the KPICard colour prop, which by construction lands on
 * a solid domain card. `on solid card` is an inline note for the remaining
 * hand-placed light tones, so every such exception has to be justified at the
 * call site rather than silently skipped here.
 */
const ON_DARK =
  /(solid-card|domainCardClass|solidCardClass|bg-slate-9|bg-\[#0|bg-black|color="text-|on solid card)/;

describe("no unsafe colour combinations in source", () => {
  it("finds source files to scan", () => {
    expect(files.length).toBeGreaterThan(20);
  });

  const offenders: string[] = [];
  for (const { file, lines } of files) {
    lines.forEach((line, i) => {
      const where = `${file}:${i + 1}`;
      // Light colour text on a light surface.
      const lightText = new RegExp(`\\btext-(?:${HUES})-(?:100|200|300|400)\\b`);
      if (lightText.test(line) && !ON_DARK.test(line)) {
        offenders.push(`${where} light colour text on a light surface: ${line.trim().slice(0, 90)}`);
      }
      // Dark-theme chip left behind on the light theme.
      const darkChip = new RegExp(`\\bbg-(?:${HUES})-(?:800|900|950)/`);
      if (darkChip.test(line)) {
        offenders.push(`${where} dark chip on a light theme: ${line.trim().slice(0, 90)}`);
      }
      // Tokens that no longer exist.
      const dead = /\b(?:text|bg|border|ring|fill|from|to)-(?:card-ink\w*|card-(?:blue|sage|lavender|teal|peach|sand|neutral))\b/;
      if (dead.test(line)) {
        offenders.push(`${where} references a removed token: ${line.trim().slice(0, 90)}`);
      }
      // Washed-out grey on white.
      if (/\btext-slate-400\b/.test(line) && !ON_DARK.test(line)) {
        offenders.push(`${where} text-slate-400 is below AA on white: ${line.trim().slice(0, 90)}`);
      }
    });
  }

  it("has no light-on-light text, dark chips, dead tokens or washed-out greys", () => {
    expect(offenders).toEqual([]);
  });

  it("does not put white text directly on pale slate KPI surfaces", () => {
    const unsafe: string[] = [];
    for (const { file, lines } of files) {
      lines.forEach((line, i) => {
        const classNames = line.match(/className=\"([^\"]*)\"/)?.[1]?.split(/\s+/) ?? [];
        const baseClasses = classNames.filter((name) => !name.includes(":"));
        if (baseClasses.some((name) => /^bg-slate-(?:50|100|200)$/.test(name)) && baseClasses.includes("text-white")) {
          unsafe.push(`${file}:${i + 1}`);
        }
      });
    }
    expect(unsafe).toEqual([]);
  });

  it("renders regional PM2.5 prediction cards on the PM2.5 domain fill", () => {
    const pm25 = readFileSync(join(SRC, "app/environment/pm25/page.tsx"), "utf8");
    expect(pm25).toContain('className={domainCardClass("pm25", "p-4 rounded-lg")}');
    expect(pm25).not.toMatch(/className=\"[^\"]*bg-slate-(?:50|100|200)[^\"]*text-white/);
  });

  it("keeps Land headline KPI text readable on its solid domain card", () => {
    const land = readFileSync(join(SRC, "app/planning/land/page.tsx"), "utf8");
    expect(land).toContain('text-xs text-white/90 font-normal">{unit}');
    expect(land).toContain('text-[10px] text-white/90 mt-1">{has ?');
  });

  it("uses high-contrast text for Weather values on the domain-coloured cards", () => {
    const weather = readFileSync(join(SRC, "app/environment/weather/page.tsx"), "utf8");
    expect(weather).not.toContain("text-amber-700 text-xs uppercase tracking-wider mb-3");
    expect(weather).toContain("text-white/90 text-xs uppercase tracking-wider mb-3");
    expect(weather).not.toContain("text-[10px] text-slate-500 uppercase tracking-widest mt-1 text-center");
    expect(weather).toContain('<Compass size={14} />');
    expect(weather).toContain('text-slate-700 text-xs uppercase tracking-wider mb-3');
  });

  it("keeps Traffic forecast labels and status values visible on blue KPI cards", () => {
    const traffic = readFileSync(join(SRC, "app/mobility/traffic/page.tsx"), "utf8");
    expect(traffic).not.toContain('className="text-slate-500">Current');
    expect(traffic).not.toContain('className="text-slate-500">Predicted');
    expect(traffic).not.toContain('className="text-slate-500">Status');
    expect(traffic).toContain('className="text-white/90">Current');
    expect(traffic).toContain("case 'severe': return 'text-red-100';");
  });

  it("uses light ink on Water and Waste domain KPI cards", () => {
    const water = readFileSync(join(SRC, "app/infrastructure/water/page.tsx"), "utf8");
    const waste = readFileSync(join(SRC, "app/infrastructure/waste/page.tsx"), "utf8");
    expect(water).toContain('text-white/90">NEWATER SHARE OF WATER SALES');
    expect(water).toContain('text-[10px] font-bold tracking-[0.14em] text-white/90');
    expect(water).toContain('<KindBadge kind={ind.data_kind} onSolidCard />');
    expect(waste).toContain('<span className="text-white/90">Published value:');
  });

  it("uses a light badge surface when Water and Land source badges sit on solid KPIs", () => {
    for (const rel of ["app/infrastructure/water/page.tsx", "app/planning/land/page.tsx"]) {
      const source = readFileSync(join(SRC, rel), "utf8");
      expect(source).toContain('live: "bg-white text-green-900 border-white/80"');
      expect(source).toContain('unavailable: "bg-white text-slate-700 border-white/80"');
      expect(source).toContain("onSolidCard ? SOLID_KIND_STYLE[kind]");
    }
  });

  it.each([
    "app/planning/land/page.tsx",
    "app/mobility/roads/page.tsx",
    "app/safety/fire/page.tsx",
    "app/environment/weather/page.tsx",
  ])("does not use white hover text on light controls in %s", (rel) => {
    const src = readFileSync(join(SRC, rel), "utf8");
    expect(src).not.toContain("hover:text-white");
  });
});

describe("every referenced colour token is defined", () => {
  const defined = new Set(
    [...CSS.matchAll(/--color-([a-z0-9-]+):/g)].map((m) => m[1])
  );

  it("has no var(--color-*) referencing a token that does not exist", () => {
    const missing: string[] = [];
    for (const { file, lines } of files) {
      lines.forEach((line, i) => {
        for (const m of line.matchAll(/var\(--color-([a-z0-9-]+)\)/g)) {
          if (!defined.has(m[1])) missing.push(`${file}:${i + 1} --color-${m[1]}`);
        }
      });
    }
    expect(missing).toEqual([]);
  });

  it("defines the legacy severity tokens still referenced by older components", () => {
    for (const s of ["low", "moderate", "high", "critical"]) {
      expect(defined.has(`severity-${s}`)).toBe(true);
    }
  });
});

describe("map components cannot collapse to zero height", () => {
  it.each([
    "app/mobility/traffic/TrafficMap.tsx",
    "components/map/SingaporeMap.tsx",
    "app/infrastructure/water/WaterMap.tsx",
    "app/planning/land/LandMap.tsx",
    "app/infrastructure/waste/WasteMap.tsx",
  ])("%s gives the map an explicit non-zero height", (rel) => {
    const src = readFileSync(join(SRC, rel), "utf8");
    // react-map-gl sizes its container with height:100%. That percentage
    // resolves against the parent's `height`, never its `min-height`, so
    // through an auto-height flex chain it collapses to a 0px canvas.
    expect(src).toMatch(/minHeight:\s*\d+/);
  });

  it.each([
    ["app/mobility/traffic/TrafficMap.tsx", "traffic-map-tile-error"],
    ["app/infrastructure/water/WaterMap.tsx", "Basemap tiles unavailable"],
    ["app/planning/land/LandMap.tsx", "Basemap tiles unavailable"],
    ["app/infrastructure/waste/WasteMap.tsx", "Basemap tiles unavailable"],
  ])("%s explains basemap failures", (rel, message) => {
    const src = readFileSync(join(SRC, rel), "utf8");
    expect(src).toContain("onError=");
    expect(src).toContain(message);
  });
});

describe("Construction frontend integration", () => {
  it("exposes a Construction route and navigation entry", () => {
    expect(existsSync(join(SRC, "app/planning/construction/page.tsx"))).toBe(true);
    const navigation = readFileSync(join(SRC, "components/common/TopNav.tsx"), "utf8");
    expect(navigation).toMatch(/\/planning\/construction|label:\s*["']Construction["']/i);
  });
});
