import type { TieredDimension, TieredResult, TieredRunStatus } from '../../api/tiered';

// showplayer badge recipe: soft tinted fill + matching inset ring, no border.
export const TAG_BASE =
  'inline-flex items-center rounded px-[9px] py-0.5 text-xs font-semibold ring-1 ring-inset';

export const DIRECTION_TAG: Record<TieredResult['direction'], string> = {
  buy: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
  hold: 'bg-amber-500/20 text-amber-300 ring-amber-500/30',
  sell: 'bg-red-500/20 text-red-300 ring-red-500/30',
  unknown: 'bg-gray-500/20 text-gray-300 ring-gray-500/30',
};

export const COVERAGE_TAG: Record<TieredDimension['coverage'], string> = {
  full: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
  partial: 'bg-amber-500/20 text-amber-300 ring-amber-500/30',
  unavailable: 'bg-red-500/20 text-red-300 ring-red-500/30',
};

export const STATUS_DOT: Record<TieredRunStatus, string> = {
  running: 'bg-sky-400',
  done: 'bg-emerald-400',
  failed: 'bg-red-400',
};

// Inline text link, showplayer blue.
export const ALT_LINK = 'text-blue-400 hover:text-blue-300 hover:underline';
