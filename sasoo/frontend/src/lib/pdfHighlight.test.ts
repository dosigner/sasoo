import { describe, expect, it } from 'vitest';
import { bboxToPercentRect, type ViewportLike } from '@/lib/pdfHighlight';

/** 회전 없음·scale 1인 pdf.js viewport의 변환을 흉내낸다: y축만 뒤집는다. */
function viewport(width = 595, height = 842, scale = 1): ViewportLike {
  return {
    width: width * scale,
    height: height * scale,
    convertToViewportRectangle(rect: number[]): number[] {
      const [x0, y0, x1, y1] = rect;
      return [x0 * scale, (height - y1) * scale, x1 * scale, (height - y0) * scale];
    },
  };
}

describe('bboxToPercentRect', () => {
  it('좌하단 원점 bbox를 퍼센트 사각형으로 바꾼다', () => {
    const rect = bboxToPercentRect([59.5, 421, 297.5, 505.2], viewport());
    expect(rect).not.toBeNull();
    expect(rect!.leftPct).toBeCloseTo(10, 1);
    expect(rect!.widthPct).toBeCloseTo(40, 1);
    expect(rect!.topPct).toBeCloseTo(40, 1);
    expect(rect!.heightPct).toBeCloseTo(10, 1);
  });

  it('확대해도 퍼센트가 같다 (줌마다 재계산할 필요가 없다)', () => {
    const at100 = bboxToPercentRect([59.5, 421, 297.5, 505.2], viewport(595, 842, 1));
    const at200 = bboxToPercentRect([59.5, 421, 297.5, 505.2], viewport(595, 842, 2));
    expect(at200!.leftPct).toBeCloseTo(at100!.leftPct, 5);
    expect(at200!.heightPct).toBeCloseTo(at100!.heightPct, 5);
  });

  it('좌표가 뒤집혀 들어와도 정규화한다', () => {
    const rect = bboxToPercentRect([297.5, 505.2, 59.5, 421], viewport());
    expect(rect!.widthPct).toBeGreaterThan(0);
    expect(rect!.heightPct).toBeGreaterThan(0);
  });

  it('면적 0·비정상 값은 null이다', () => {
    expect(bboxToPercentRect([10, 10, 10, 10], viewport())).toBeNull();
    expect(bboxToPercentRect([Number.NaN, 1, 2, 3], viewport())).toBeNull();
    expect(bboxToPercentRect([1, 2, 3], viewport())).toBeNull();
  });
});
