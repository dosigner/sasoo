import { describe, expect, it } from 'vitest';

import { assetExtension, safeAssetFilename } from './download';

// downloadBlob itself is untested: it is branch-free DOM glue and vitest runs
// in the node environment, without a DOM.

describe('safeAssetFilename', () => {
  it('keeps 한글 and other non-ASCII letters', () => {
    expect(safeAssetFilename('그림 1 광학계', 'figure')).toBe('그림_1_광학계');
  });

  it('collapses runs of unsafe characters into one underscore', () => {
    expect(safeAssetFilename('Fig. 2 / 3 : results', 'figure')).toBe('Fig._2_3_results');
  });

  it('trims leading and trailing underscores', () => {
    expect(safeAssetFilename('  (Figure 4)  ', 'figure')).toBe('Figure_4');
  });

  it('falls back when nothing usable survives', () => {
    expect(safeAssetFilename('///', 'figure_7')).toBe('figure_7');
    expect(safeAssetFilename('', 'figure_7')).toBe('figure_7');
    expect(safeAssetFilename(null, 'figure_7')).toBe('figure_7');
  });
});

describe('assetExtension', () => {
  it('reads the extension from a path', () => {
    expect(assetExtension('/static/library/3/figures/fig_1.png')).toBe('png');
  });

  it('drops a query or hash appended by the backend', () => {
    expect(assetExtension('/static/a/b.webp?token=abc123')).toBe('webp');
    expect(assetExtension('/static/a/b.jpg#page=2')).toBe('jpg');
  });

  it('falls back when the path carries no extension', () => {
    // A dot-free path must not become the extension itself.
    expect(assetExtension('/static/a/b')).toBe('png');
    expect(assetExtension('/static/a.b/c')).toBe('png');
    expect(assetExtension(null)).toBe('png');
    expect(assetExtension('', 'svg')).toBe('svg');
  });
});
