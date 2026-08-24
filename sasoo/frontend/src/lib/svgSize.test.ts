import { describe, expect, it } from 'vitest';

import { resolveSvgPixelSize } from './svgSize';

describe('resolveSvgPixelSize', () => {
  // The regression this file exists for: mermaid's useMaxWidth output.
  it('uses the viewBox when mermaid emits a percentage width and no height', () => {
    expect(resolveSvgPixelSize('100%', null, '0 0 1412 806')).toEqual({
      width: 1412,
      height: 806,
    });
  });

  it('keeps explicit pixel attributes', () => {
    expect(resolveSvgPixelSize('1412', '806', '0 0 1412 806')).toEqual({
      width: 1412,
      height: 806,
    });
  });

  it('accepts a px suffix and rounds fractional lengths up', () => {
    expect(resolveSvgPixelSize('640.5px', '480.2px', null)).toEqual({
      width: 641,
      height: 481,
    });
  });

  it('ignores non-pixel keywords', () => {
    expect(resolveSvgPixelSize('auto', 'auto', '0 0 300 200')).toEqual({
      width: 300,
      height: 200,
    });
  });

  it('handles a comma-separated viewBox with a non-zero origin', () => {
    expect(resolveSvgPixelSize('100%', null, '-8,-8,1024,768')).toEqual({
      width: 1024,
      height: 768,
    });
  });

  it('falls back to defaults when nothing usable is present', () => {
    expect(resolveSvgPixelSize(null, null, null)).toEqual({
      width: 1200,
      height: 800,
    });
    expect(resolveSvgPixelSize('0', '0', '0 0 0 0')).toEqual({
      width: 1200,
      height: 800,
    });
    expect(resolveSvgPixelSize('100%', null, 'not a viewbox')).toEqual({
      width: 1200,
      height: 800,
    });
  });
});
