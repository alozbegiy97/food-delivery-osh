import { memo, useId } from 'react';

import type { DishArtKind } from './dishArtKind';

/*
 * Dish artwork of the "Печь" direction (DEC-161 rev. 47): original drawings
 * made for this project in MA-4.6, shown while a dish has no photo. A photo
 * from the API (`image_url`) always wins; the caller decides. The drawings
 * are top-down "studio shots" without a background: the container paints
 * the backdrop with the `plate` / `plate-hi` tokens.
 *
 * The colours below are the colours of the food itself (crust, cheese,
 * basil...). They are deliberately fixed here and are not design tokens
 * (DEC-161 rev. 47); no text is ever drawn over them.
 *
 * Everything is plain JSX: no innerHTML, no external images or files. The
 * topping layout comes from a seeded generator evaluated once at module
 * load, so every render (and every test) draws the same picture.
 */

// ---------- deterministic geometry ----------

type Point = readonly [x: number, y: number, k: number];

function seeded(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 16807) % 2147483647;
    return state / 2147483647;
  };
}

const r1 = (value: number) => Math.round(value * 10) / 10;

/** Up to `count` points inside a circle of `maxR` around the centre, `minDist` apart. */
function scatter(next: () => number, count: number, maxR: number, minDist: number): Point[] {
  const points: Point[] = [];
  for (let attempt = 0; points.length < count && attempt < 900; attempt += 1) {
    const angle = next() * Math.PI * 2;
    const radius = Math.sqrt(next()) * maxR;
    const x = 100 + Math.cos(angle) * radius;
    const y = 100 + Math.sin(angle) * radius;
    if (points.every(([px, py]) => Math.hypot(px - x, py - y) > minDist)) {
      points.push([r1(x), r1(y), r1(next() * 100) / 100]);
    }
  }
  return points;
}

/** Charred spots on the rim of the crust: [cx, cy, rx, ry, rotation, opacity]. */
function rimSpots(next: () => number, count: number) {
  return Array.from({ length: count }, () => {
    const angle = next() * Math.PI * 2;
    const radius = 84 + next() * 6;
    return [
      r1(100 + Math.cos(angle) * radius),
      r1(100 + Math.sin(angle) * radius),
      r1(2 + next() * 4),
      r1(1.4 + next() * 2),
      r1((angle * 180) / Math.PI + 90),
      r1(0.35 + next() * 0.35),
    ] as const;
  });
}

const pizzaRandom = seeded(48271);
const PIZZA = {
  rim: rimSpots(pizzaRandom, 14),
  browned: scatter(pizzaRandom, 16, 66, 14),
  mozzarella: scatter(pizzaRandom, 5, 54, 30),
  basil: scatter(pizzaRandom, 6, 60, 24),
};

const burgerRandom = seeded(4242);
const BURGER = { seeds: scatter(burgerRandom, 46, 64, 9.5) };

const wrapRandom = seeded(777);
const WRAP_FILLING_COLOURS = ['#9a5328', '#7a3e1c', '#b66a33', '#4e9a3a', '#d2452e', '#f4efe2'];
const WRAP = {
  filling: Array.from({ length: 26 }, (_, index) => {
    const angle = wrapRandom() * Math.PI * 2;
    const radius = Math.sqrt(wrapRandom());
    return [
      r1(160 + Math.cos(angle) * radius * 14),
      r1(100 + Math.sin(angle) * radius * 24),
      r1(2.2 + wrapRandom() * 3),
      WRAP_FILLING_COLOURS[index % WRAP_FILLING_COLOURS.length],
    ] as const;
  }),
};

// ---------- shared pieces ----------

/** Unique, CSS-safe prefix for the ids inside one drawing. */
function useArtId(): string {
  return `dish${useId().replace(/[^A-Za-z0-9]/g, '')}`;
}

function CommonDefs({ id, seed, lite }: { id: string; seed: number; lite: boolean }) {
  return (
    <defs>
      {/* Filters are the expensive part; the light version leaves them out. */}
      {!lite && (
        <>
          {/* Slightly irregular edges: hand-made dough and melted cheese. */}
          <filter id={`${id}-wobble`} x="-10%" y="-10%" width="120%" height="120%">
            <feTurbulence type="fractalNoise" baseFrequency="0.045" numOctaves={2} seed={seed} />
            <feDisplacementMap
              in="SourceGraphic"
              scale={9}
              xChannelSelector="R"
              yChannelSelector="G"
            />
          </filter>
          {/* Fine photographic grain. */}
          <filter id={`${id}-grain`}>
            <feTurbulence
              type="fractalNoise"
              baseFrequency="1.1"
              numOctaves={1}
              seed={seed}
              stitchTiles="stitch"
            />
            <feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.55 0" />
          </filter>
        </>
      )}
      {/* One light from the top left, as in a studio shot. */}
      <radialGradient id={`${id}-light`} cx="0.36" cy="0.3" r="0.78">
        <stop offset="0" stopColor="#ffffff" stopOpacity="0.24" />
        <stop offset="0.5" stopColor="#ffffff" stopOpacity="0" />
        <stop offset="1" stopColor="#000000" stopOpacity="0.32" />
      </radialGradient>
      <clipPath id={`${id}-clip`}>
        <circle cx="100" cy="100" r="93" />
      </clipPath>
    </defs>
  );
}

function Finish({ id, grain = true }: { id: string; grain?: boolean }) {
  return (
    <g data-layer="light">
      {grain && (
        <g clipPath={`url(#${id}-clip)`}>
          <rect width="200" height="200" filter={`url(#${id}-grain)`} opacity="0.16" />
        </g>
      )}
      <circle cx="100" cy="100" r="93" fill={`url(#${id}-light)`} />
    </g>
  );
}

// ---------- drawings ----------

function Pizza({ id, lite }: { id: string; lite: boolean }) {
  const wobble = lite ? undefined : `url(#${id}-wobble)`;
  return (
    <>
      <defs>
        <radialGradient id={`${id}-crust`}>
          <stop offset="0.8" stopColor="#f5d08f" />
          <stop offset="0.9" stopColor="#e2a457" />
          <stop offset="0.97" stopColor="#b3652a" />
          <stop offset="1" stopColor="#7a3a16" />
        </radialGradient>
        <radialGradient id={`${id}-sauce`}>
          <stop offset="0" stopColor="#cf4526" />
          <stop offset="1" stopColor="#8d2313" />
        </radialGradient>
        <radialGradient id={`${id}-cheese`} cx="0.45" cy="0.4">
          <stop offset="0" stopColor="#ffe7a3" />
          <stop offset="0.55" stopColor="#f4bf55" />
          <stop offset="0.9" stopColor="#e09a35" />
          <stop offset="1" stopColor="#c9782a" />
        </radialGradient>
        <radialGradient id={`${id}-mozzarella`} cx="0.4" cy="0.35">
          <stop offset="0" stopColor="#fffdf6" />
          <stop offset="0.8" stopColor="#fbefd2" />
          <stop offset="1" stopColor="#e9c98e" />
        </radialGradient>
        <linearGradient id={`${id}-basil`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#4c9a3f" />
          <stop offset="1" stopColor="#1f5d22" />
        </linearGradient>
      </defs>
      <g data-layer="crust">
        <circle cx="100" cy="100" r="93" fill={`url(#${id}-crust)`} filter={wobble} />
        {PIZZA.rim.map(([cx, cy, rx, ry, rotate, opacity], index) => (
          <ellipse
            key={index}
            cx={cx}
            cy={cy}
            rx={rx}
            ry={ry}
            transform={`rotate(${rotate} ${cx} ${cy})`}
            fill="#4a210c"
            opacity={opacity}
          />
        ))}
      </g>
      <circle
        data-layer="sauce"
        cx="100"
        cy="100"
        r="80"
        fill={`url(#${id}-sauce)`}
        filter={wobble}
      />
      <g data-layer="cheese">
        <circle cx="100" cy="100" r="76" fill={`url(#${id}-cheese)`} filter={wobble} />
        {PIZZA.browned.map(([cx, cy, k], index) => (
          <circle
            key={index}
            cx={cx}
            cy={cy}
            r={r1(3 + k * 5)}
            fill="#b8601f"
            opacity={r1(0.22 + k * 0.3)}
          />
        ))}
      </g>
      <g data-layer="mozzarella">
        {PIZZA.mozzarella.map(([cx, cy, k], index) => (
          <circle
            key={index}
            cx={cx}
            cy={cy}
            r={r1(11 + k * 4)}
            fill={`url(#${id}-mozzarella)`}
            filter={wobble}
          />
        ))}
      </g>
      <g data-layer="basil">
        {PIZZA.basil.map(([x, y, k], index) => (
          <g key={index} transform={`translate(${x} ${y}) rotate(${r1(k * 360)}) scale(1.15)`}>
            <path d="M0-11C7-7 8 5 0 12C-8 5-7-7 0-11Z" fill={`url(#${id}-basil)`} />
            <path d="M0-9V10" stroke="#174a1b" strokeWidth="0.9" opacity="0.6" />
          </g>
        ))}
      </g>
      <Finish id={id} grain={!lite} />
    </>
  );
}

function Burger({ id, lite }: { id: string; lite: boolean }) {
  const wobble = lite ? undefined : `url(#${id}-wobble)`;
  return (
    <>
      <defs>
        <radialGradient id={`${id}-bun`} cx="0.42" cy="0.38">
          <stop offset="0" stopColor="#f8cd88" />
          <stop offset="0.55" stopColor="#e29a4b" />
          <stop offset="0.88" stopColor="#b0632a" />
          <stop offset="1" stopColor="#743914" />
        </radialGradient>
      </defs>
      <g data-layer="lettuce">
        <circle cx="100" cy="100" r="91" fill="#6aa23a" filter={wobble} />
        <circle cx="100" cy="100" r="87" fill="#4d8a2c" opacity="0.55" filter={wobble} />
      </g>
      <g data-layer="cheddar" fill="#f5b335" filter={wobble}>
        <polygon points="22,122 58,170 12,160" />
        <polygon points="168,38 190,86 150,58" />
      </g>
      <g data-layer="bun">
        <circle cx="100" cy="100" r="81" fill={`url(#${id}-bun)`} />
        {BURGER.seeds.map(([cx, cy, k], index) => (
          <ellipse
            key={index}
            cx={cx}
            cy={cy}
            rx="3.3"
            ry="1.7"
            transform={`rotate(${r1(k * 180)} ${cx} ${cy})`}
            fill="#fbf0d4"
            stroke="#c99a5a"
            strokeWidth="0.5"
          />
        ))}
      </g>
      <Finish id={id} grain={!lite} />
    </>
  );
}

function Wrap({ id }: { id: string }) {
  return (
    <>
      <defs>
        <linearGradient id={`${id}-lavash`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#f2d5a4" />
          <stop offset="0.5" stopColor="#dca868" />
          <stop offset="1" stopColor="#eecb94" />
        </linearGradient>
        <linearGradient id={`${id}-paper`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#fbf8f1" />
          <stop offset="1" stopColor="#e5dccb" />
        </linearGradient>
      </defs>
      <g transform="rotate(-32 100 100)">
        <g data-layer="lavash">
          <rect x="16" y="66" width="152" height="68" rx="32" fill={`url(#${id}-lavash)`} />
          {[0, 1, 2, 3, 4, 5].map((index) => (
            <path
              key={index}
              d={`M${96 + index * 11} 70l-10 60`}
              stroke="#8a4a1d"
              strokeWidth="3"
              strokeLinecap="round"
              opacity="0.28"
            />
          ))}
        </g>
        <g data-layer="paper">
          <rect x="12" y="60" width="72" height="80" rx="12" fill={`url(#${id}-paper)`} />
          <path d="M30 62v76M52 62v76" stroke="#d6ccb9" strokeWidth="1.2" />
        </g>
        <g data-layer="filling">
          <ellipse cx="160" cy="100" rx="22" ry="34" fill="#e3b678" />
          <ellipse cx="160" cy="100" rx="17" ry="28" fill="#8e4b22" />
          {WRAP.filling.map(([cx, cy, r, fill], index) => (
            <circle key={index} cx={cx} cy={cy} r={r} fill={fill} />
          ))}
        </g>
      </g>
      <g data-layer="light">
        <circle cx="100" cy="100" r="93" fill={`url(#${id}-light)`} opacity="0.7" />
      </g>
    </>
  );
}

const SEED: Record<DishArtKind, number> = { pizza: 41, burger: 31, wrap: 17 };

interface DishArtProps {
  kind: DishArtKind;
  className?: string;
  /**
   * Light version for small images (cards, categories; MA-4.6-B): the same
   * picture without the edge and grain filters, which cost the most on weak
   * phones and are hardly visible at that size. Default false (full).
   */
  lite?: boolean;
}

/**
 * Decorative dish drawing (aria-hidden): the dish name is always given as
 * text next to it. Size it with `className`; it keeps a 1:1 view box.
 */
export const DishArt = memo(function DishArt({ kind, className, lite = false }: DishArtProps) {
  const id = useArtId();
  return (
    <svg
      viewBox="0 0 200 200"
      aria-hidden="true"
      focusable="false"
      data-dish-art={kind}
      className={className}
    >
      <CommonDefs id={id} seed={SEED[kind]} lite={lite} />
      {kind === 'pizza' ? (
        <Pizza id={id} lite={lite} />
      ) : kind === 'burger' ? (
        <Burger id={id} lite={lite} />
      ) : (
        <Wrap id={id} />
      )}
    </svg>
  );
});
