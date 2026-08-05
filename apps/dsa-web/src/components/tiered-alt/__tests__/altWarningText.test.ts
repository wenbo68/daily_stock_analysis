import { describe, expect, it } from 'vitest';
import { UI_TEXT, formatUiText, type UiTextKey } from '../../../i18n/uiText';
import { friendlyWarning } from '../altWarningText';

const t = (key: UiTextKey, params?: Record<string, string | number>) =>
  formatUiText(UI_TEXT.en[key], params);

describe('friendlyWarning — debate stage notes lead with the AI role', () => {
  it('a retried grade sheet names its lister', () => {
    const note = friendlyWarning(
      'first analyst grade sheet needed a retry — first reply was invalid',
      t,
    );
    expect(note?.keyword).toBe('AI reply');
    expect(note?.text).toBe('Lister 1 — the first reply was invalid; the retry succeeded.');
  });

  it('the two analysts produce two distinguishable notes', () => {
    const second = friendlyWarning(
      'second analyst grade sheet needed a retry — first reply was invalid',
      t,
    );
    expect(second?.text).toContain('Lister 2');
  });

  it('an invalid-after-retry sheet names its lister too', () => {
    const note = friendlyWarning(
      'first analyst grade sheet invalid after retry: unknown grade keys: technicals.levels.resistance_1',
      t,
    );
    expect(note?.text).toBe('Lister 1 — the reply was still invalid after a retry.');
  });

  it('check and deciding rounds use their vote labels', () => {
    expect(
      friendlyWarning('check round needed a retry — first reply was invalid', t)?.text,
    ).toContain('Check vote');
    expect(
      friendlyWarning('deciding round was not JSON even after a retry', t)?.text,
    ).toContain('Deciding vote');
  });

  it('an unmapped stage keeps its raw name rather than inventing a label', () => {
    const note = friendlyWarning(
      'defender opening needed a retry — first reply was invalid',
      t,
    );
    expect(note?.text).toContain('defender opening');
  });
});

describe('friendlyWarning — v12 voided-run notes are translated', () => {
  it('both grade sheets failing translates (v12 wording)', () => {
    const note = friendlyWarning(
      'both analyst grade sheets invalid after retry — tier-2 verdict voided',
      t,
    );
    expect(note?.text).toBe(
      'Both analysts kept returning invalid grade sheets — the deep analysis was voided.',
    );
  });

  it('the old v8 "lists" wording still translates', () => {
    const note = friendlyWarning(
      'both analyst lists invalid after retry — tier-2 verdict voided',
      t,
    );
    expect(note?.text).toContain('deep analysis was voided');
  });

  it('the no-outlook note translates with the re-run advice', () => {
    const note = friendlyWarning(
      'debate produced no verdict — no outlook (re-run)',
      t,
    );
    expect(note?.text).toContain('re-run');
  });

  it('one failed sheet names the failed lister', () => {
    const note = friendlyWarning(
      'second analyst grade sheet invalid after retry — proceeding with the other sheet only',
      t,
    );
    expect(note?.text).toContain('Lister 2');
  });
});
