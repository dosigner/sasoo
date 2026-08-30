// Pixel size resolution for exported SVGs, kept DOM-free so it can be tested.
//
// Mermaid sets width="100%" + style="max-width: Wpx" and omits height whenever
// useMaxWidth is on (its calculateSvgSizeAttrs), so the only pixel dimensions
// live in the viewBox. parseFloat("100%") is 100, not NaN, so treating the
// attribute as pixels silently squashes every export to a 100px-wide sliver.

const PIXEL_SIZE = /^\d+(?:\.\d+)?(?:px)?$/;

export interface SvgPixelSize {
  width: number;
  height: number;
}

/** Explicit pixel attributes win; otherwise fall back to the viewBox, then to a default. */
export function resolveSvgPixelSize(
  widthAttr: string | null,
  heightAttr: string | null,
  viewBoxAttr: string | null
): SvgPixelSize {
  const parts = (viewBoxAttr ?? '').trim().split(/[\s,]+/).map(Number);
  const viewBox =
    parts.length === 4 && parts.every((n) => Number.isFinite(n)) ? parts : null;

  return {
    width: pick(pixels(widthAttr), viewBox?.[2], 1200),
    height: pick(pixels(heightAttr), viewBox?.[3], 800),
  };
}

/** NaN for anything that is not a plain pixel length ("100%", "auto", ""). */
function pixels(attr: string | null): number {
  const value = (attr ?? '').trim();
  return PIXEL_SIZE.test(value) ? parseFloat(value) : NaN;
}

function pick(attr: number, fromViewBox: number | undefined, fallback: number): number {
  if (attr > 0) return Math.ceil(attr);
  if (fromViewBox !== undefined && fromViewBox > 0) return Math.ceil(fromViewBox);
  return fallback;
}
