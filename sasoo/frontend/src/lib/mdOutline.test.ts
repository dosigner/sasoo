import { describe, expect, it } from 'vitest';

import { extractOutline, slugify } from './mdOutline';

describe('slugify', () => {
  it('lowercases and dashes ASCII', () => {
    expect(slugify('Hello World')).toBe('hello-world');
  });

  it('keeps Korean letters (unicode-aware)', () => {
    expect(slugify('실험 방법')).toBe('실험-방법');
  });

  it('collapses and trims separators', () => {
    expect(slugify('  A -- B  ')).toBe('a-b');
  });

  it('falls back to "section" for empty result', () => {
    expect(slugify('!!!')).toBe('section');
  });
});

describe('extractOutline', () => {
  it('extracts ATX headings with level, text, slug', () => {
    const md = '# Title\n본문\n## 개요\n### 세부';
    expect(extractOutline(md)).toEqual([
      { level: 1, text: 'Title', slug: 'title' },
      { level: 2, text: '개요', slug: '개요' },
      { level: 3, text: '세부', slug: '세부' },
    ]);
  });

  it('strips emphasis markers from heading text', () => {
    expect(extractOutline('## **핵심** 요약')).toEqual([
      { level: 2, text: '핵심 요약', slug: '핵심-요약' },
    ]);
  });

  it('de-duplicates slugs', () => {
    expect(extractOutline('## A\n## A')).toEqual([
      { level: 2, text: 'A', slug: 'a' },
      { level: 2, text: 'A', slug: 'a-2' },
    ]);
  });

  it('ignores headings inside fenced code blocks', () => {
    const md = '## real\n```\n## not-a-heading\n```';
    expect(extractOutline(md)).toEqual([
      { level: 2, text: 'real', slug: 'real' },
    ]);
  });

  it('ignores lines without a space after hashes', () => {
    expect(extractOutline('#hashtag\n## ok')).toEqual([
      { level: 2, text: 'ok', slug: 'ok' },
    ]);
  });

  it('strips trailing closing hashes', () => {
    expect(extractOutline('## 제목 ##')).toEqual([
      { level: 2, text: '제목', slug: '제목' },
    ]);
  });

  it('returns empty for text without headings', () => {
    expect(extractOutline('그냥 문단입니다.')).toEqual([]);
  });
});
