import { describe, expect, it } from 'vitest';

import {
  buildExplainPrompt,
  isSelectionTooLong,
  normalizeSelectionText,
  SELECTION_MAX_CHARS,
} from './selectionExplain';

describe('normalizeSelectionText', () => {
  it('collapses runs of whitespace/newlines into single spaces and trims', () => {
    expect(normalizeSelectionText('  hello\n\nworld   foo  ')).toBe('hello world foo');
  });
});

describe('buildExplainPrompt', () => {
  it('includes the page number and the quoted selection, plus a level line when given', () => {
    const prompt = buildExplainPrompt(12, '어떤 수식', 'masters');
    expect(prompt).toContain('p.12');
    expect(prompt).toContain('> 어떤 수식');
    expect(prompt).toContain('석사생');
  });
});

describe('isSelectionTooLong', () => {
  it('flags only text longer than SELECTION_MAX_CHARS', () => {
    expect(isSelectionTooLong('a'.repeat(SELECTION_MAX_CHARS))).toBe(false);
    expect(isSelectionTooLong('a'.repeat(SELECTION_MAX_CHARS + 1))).toBe(true);
  });
});
