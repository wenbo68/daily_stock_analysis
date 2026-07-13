import type { TieredResult, TieredRunStatus } from '../../api/tiered';

// showplayer badge recipe: soft tinted fill + matching inset ring, no border.
export const TAG_BASE =
  'inline-flex items-center rounded px-[9px] py-0.5 text-xs font-semibold ring-1 ring-inset';

export const DIRECTION_TAG: Record<TieredResult['direction'], string> = {
  buy: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
  hold: 'bg-amber-500/20 text-amber-300 ring-amber-500/30',
  sell: 'bg-red-500/20 text-red-300 ring-red-500/30',
  unknown: 'bg-gray-500/20 text-gray-300 ring-gray-500/30',
};

// -300 shades on purpose: the app-wide index.css redefines
// --color-emerald-400/--color-red-400 as bare HSL triplets for its own
// hsl(var(...)) tokens, which silently voids Tailwind's bg-*-400 utilities.
export const STATUS_DOT: Record<TieredRunStatus, string> = {
  running: 'bg-sky-300',
  done: 'bg-emerald-300',
  failed: 'bg-red-300',
};

// One tint per kind of selection, so the pill rows under the form and the
// history filters read at a glance (showplayer's ActiveLabels palette idea).
export const PILL_TONE = {
  ticker: 'bg-sky-500/20 text-sky-300 ring-sky-500/30',
  depth: 'bg-violet-500/20 text-violet-300 ring-violet-500/30',
  capital: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
  risk: 'bg-orange-500/20 text-orange-300 ring-orange-500/30',
  date: 'bg-lime-500/20 text-lime-300 ring-lime-500/30',
  shares: 'bg-blue-500/20 text-blue-300 ring-blue-500/30',
  neutral: 'bg-gray-500/20 text-gray-300 ring-gray-500/30',
} as const;

// Inline text link, showplayer blue.
export const ALT_LINK = 'text-blue-400 hover:text-blue-300 hover:underline';
