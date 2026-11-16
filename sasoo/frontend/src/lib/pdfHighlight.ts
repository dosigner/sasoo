/** Convert an unrotated PDF user-space box to percentages of the page viewport. */

export interface ViewportLike {
  width: number;
  height: number;
  convertToViewportPoint(x: number, y: number): number[];
}

export interface PercentRect {
  leftPct: number;
  topPct: number;
  widthPct: number;
  heightPct: number;
}

export function bboxToPercentRect(
  bbox: readonly number[],
  viewport: ViewportLike,
): PercentRect | null {
  if (!Array.isArray(bbox) || bbox.length !== 4 || bbox.some((n) => !Number.isFinite(n))
    || !Number.isFinite(viewport.width) || !Number.isFinite(viewport.height)
    || viewport.width <= 0 || viewport.height <= 0) {
    return null;
  }
  let points: number[][];
  try {
    // The viewport owns rotation, CropBox offsets and UserUnit scaling.
    points = [
      viewport.convertToViewportPoint(bbox[0], bbox[1]),
      viewport.convertToViewportPoint(bbox[2], bbox[1]),
      viewport.convertToViewportPoint(bbox[0], bbox[3]),
      viewport.convertToViewportPoint(bbox[2], bbox[3]),
    ];
  } catch {
    // A failed highlight must not interrupt page navigation.
    return null;
  }
  if (points.some((point) => !Array.isArray(point) || point.length !== 2
    || point.some((n) => !Number.isFinite(n)))) {
    return null;
  }

  const left = Math.min(...points.map(([x]) => x));
  const right = Math.max(...points.map(([x]) => x));
  const top = Math.min(...points.map(([, y]) => y));
  const bottom = Math.max(...points.map(([, y]) => y));
  const width = right - left;
  const height = bottom - top;
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return null;
  }

  const edgeX = points[1].map((value, index) => value - points[0][index]);
  const edgeY = points[2].map((value, index) => value - points[0][index]);
  const scaleX = Math.max(...edgeX.map(Math.abs));
  const scaleY = Math.max(...edgeY.map(Math.abs));
  // Normalize before the determinant to avoid overflow for large valid scales.
  const area = (edgeX[0] / scaleX) * (edgeY[1] / scaleY)
    - (edgeX[1] / scaleX) * (edgeY[0] / scaleY);
  if (!Number.isFinite(area) || area === 0) {
    return null;
  }

  const rect = {
    leftPct: (left / viewport.width) * 100,
    topPct: (top / viewport.height) * 100,
    widthPct: (width / viewport.width) * 100,
    heightPct: (height / viewport.height) * 100,
  };
  return Object.values(rect).every(Number.isFinite) ? rect : null;
}
