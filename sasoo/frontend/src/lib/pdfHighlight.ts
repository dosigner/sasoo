/**
 * 백엔드 bbox(PDF 포인트, 좌하단 원점)를 페이지 div 안의 퍼센트 사각형으로 바꾼다.
 *
 * 직접 `pageHeight - y`를 계산하지 않고 pdf.js의 convertToViewportRectangle을 쓴다 —
 * 회전과 CropBox 오프셋을 pdf.js가 흡수한다. 결과를 퍼센트로 두면 줌이 바뀌어도
 * 다시 계산할 필요가 없다.
 */

export interface ViewportLike {
  width: number;
  height: number;
  convertToViewportRectangle(rect: number[]): number[];
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
  if (!Array.isArray(bbox) || bbox.length !== 4 || bbox.some((n) => !Number.isFinite(n))) {
    return null;
  }
  let converted: number[];
  try {
    converted = viewport.convertToViewportRectangle([bbox[0], bbox[1], bbox[2], bbox[3]]);
  } catch {
    // pdf.js 뷰포트 변환 실패는 하이라이트만 조용히 생략한다 — 페이지 이동/렌더 이벤트를
    // 죽이면 안 된다(리뷰 지적 I-3).
    return null;
  }
  if (!converted || converted.length !== 4 || converted.some((n) => !Number.isFinite(n))) {
    return null;
  }

  const left = Math.min(converted[0], converted[2]);
  const right = Math.max(converted[0], converted[2]);
  const top = Math.min(converted[1], converted[3]);
  const bottom = Math.max(converted[1], converted[3]);
  const width = right - left;
  const height = bottom - top;
  if (width <= 0 || height <= 0 || viewport.width <= 0 || viewport.height <= 0) {
    return null;
  }

  return {
    leftPct: (left / viewport.width) * 100,
    topPct: (top / viewport.height) * 100,
    widthPct: (width / viewport.width) * 100,
    heightPct: (height / viewport.height) * 100,
  };
}
