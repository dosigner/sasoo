import { describe, expect, it } from 'vitest';

import { normalizeMathDelimiters } from './mathDelimiters';

describe('normalizeMathDelimiters', () => {
  it('converts inline \\(...\\) to $...$', () => {
    expect(normalizeMathDelimiters('값은 \\(x^2\\) 이다')).toBe('값은 $x^2$ 이다');
  });

  it('converts display \\[...\\] to $$...$$', () => {
    expect(normalizeMathDelimiters('식: \\[E=mc^2\\]')).toBe('식: $$E=mc^2$$');
  });

  it('handles multiple math spans in one string', () => {
    expect(normalizeMathDelimiters('\\(a\\)와 \\(b\\)')).toBe('$a$와 $b$');
  });

  it('leaves existing $ and $$ delimiters untouched', () => {
    expect(normalizeMathDelimiters('$x$ 그리고 $$y$$')).toBe('$x$ 그리고 $$y$$');
  });

  it('leaves plain text without delimiters untouched', () => {
    expect(normalizeMathDelimiters('수식 없는 평범한 문장')).toBe('수식 없는 평범한 문장');
  });

  it('does NOT convert inside a fenced code block', () => {
    const src = '```\n\\(not math\\)\n```';
    expect(normalizeMathDelimiters(src)).toBe(src);
  });

  it('does NOT convert inside inline code', () => {
    const src = '코드 `\\(a\\)` 예시';
    expect(normalizeMathDelimiters(src)).toBe(src);
  });

  it('converts math outside code while preserving code inside the same string', () => {
    const src = '앞 \\(x\\) `\\(keep\\)` 뒤 \\[y\\]';
    expect(normalizeMathDelimiters(src)).toBe('앞 $x$ `\\(keep\\)` 뒤 $$y$$');
  });

  it('handles multiline display math', () => {
    expect(normalizeMathDelimiters('\\[\na+b\n\\]')).toBe('$$\na+b\n$$');
  });
});
