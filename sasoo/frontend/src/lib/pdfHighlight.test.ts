import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { bboxToPercentRect, type PercentRect, type ViewportLike } from '@/lib/pdfHighlight';

const installedSource = readFileSync(createRequire(import.meta.url).resolve('pdfjs-dist'), 'utf8');
function installedClass(name: string): string {
  const start = installedSource.indexOf(`class ${name} {`);
  const end = installedSource.indexOf('\n}\n', start);
  if (start < 0 || end < start) throw new Error(`Installed PDF.js class ${name} was not found`);
  return installedSource.slice(start, end + 2);
}

// Use the installed geometry classes without importing browser rendering globals.
const InstalledPageViewport = runInNewContext(
  `${installedClass('Util')}\n${installedClass('PageViewport')}\nPageViewport`,
) as new (options: {
  viewBox: number[]; userUnit: number; scale: number; rotation: number;
}) => ViewportLike;

function viewport(width = 595, height = 842, scale = 1): ViewportLike {
  return new InstalledPageViewport({ viewBox: [0, 0, width, height], userUnit: 1, scale, rotation: 0 });
}

function expectRect(actual: PercentRect | null, expected: PercentRect) {
  expect(actual).not.toBeNull();
  // Percent comparisons allow only floating-point roundoff.
  for (const key of Object.keys(expected) as (keyof PercentRect)[]) {
    expect(actual![key]).toBeCloseTo(expected[key], 10);
  }
}

describe('bboxToPercentRect', () => {
  it('uses the actual installed PDF.js viewport API', () => {
    const actual = new InstalledPageViewport({
      viewBox: [0, 0, 595, 842], userUnit: 1, scale: 1, rotation: 0,
    });
    expect(typeof actual.convertToViewportPoint).toBe('function');
    expectRect(bboxToPercentRect([59.5, 421, 297.5, 505.2], actual), {
      leftPct: 10, topPct: 40, widthPct: 40, heightPct: 10,
    });
  });

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
    expect(rect).toEqual(bboxToPercentRect([59.5, 421, 297.5, 505.2], viewport()));
  });

  it('면적 0·비정상 값은 null이다', () => {
    expect(bboxToPercentRect([10, 10, 10, 10], viewport())).toBeNull();
    expect(bboxToPercentRect([10, 10, 10, 20], viewport())).toBeNull();
    expect(bboxToPercentRect([10, 10, 20, 10], viewport())).toBeNull();
    expect(bboxToPercentRect([Number.NaN, 1, 2, 3], viewport())).toBeNull();
    expect(bboxToPercentRect([1, 2, Number.POSITIVE_INFINITY, 3], viewport())).toBeNull();
    expect(bboxToPercentRect([1, 2, 3], viewport())).toBeNull();
  });

  it('convertToViewportPoint가 던지면 null을 반환한다 (하이라이트만 생략, 점프는 유지)', () => {
    const throwingViewport: ViewportLike = {
      width: 595,
      height: 842,
      convertToViewportPoint(): number[] {
        throw new Error('pdf.js internal failure');
      },
    };
    expect(bboxToPercentRect([59.5, 421, 297.5, 505.2], throwingViewport)).toBeNull();
  });

  it.each([
    [0, { leftPct: 10, topPct: 40, widthPct: 40, heightPct: 10 }],
    [90, { leftPct: 50, topPct: 10, widthPct: 10, heightPct: 40 }],
    [180, { leftPct: 50, topPct: 50, widthPct: 40, heightPct: 10 }],
    [270, { leftPct: 40, topPct: 50, widthPct: 10, heightPct: 40 }],
  ] as const)('keeps raw PDF coordinates with installed viewport rotation %i', (rotation, expected) => {
    const actual = new InstalledPageViewport({
      viewBox: [0, 0, 595, 842], userUnit: 1, scale: 1, rotation,
    });
    expectRect(bboxToPercentRect([59.5, 421, 297.5, 505.2], actual), expected);
  });

  it.each([
    { scale: 1, userUnit: 1 },
    { scale: 1, userUnit: 2 },
    { scale: 2, userUnit: 2 },
    { scale: 0.5, userUnit: 2 },
    { scale: 1e200, userUnit: 1 },
  ])('keeps CropBox offsets and percentages at scale $scale / UserUnit $userUnit', ({ scale, userUnit }) => {
    const actual = new InstalledPageViewport({
      viewBox: [10, 20, 605, 862], userUnit, scale, rotation: 0,
    });
    expectRect(bboxToPercentRect([69.5, 441, 307.5, 525.2], actual), {
      leftPct: 10, topPct: 40, widthPct: 40, heightPct: 10,
    });
  });

  it.each([0, -1, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])(
    'rejects viewport width or height %s', (value) => {
      const invalidWidth = viewport();
      invalidWidth.width = value;
      expect(bboxToPercentRect([1, 2, 3, 4], invalidWidth)).toBeNull();
      const invalidHeight = viewport();
      invalidHeight.height = value;
      expect(bboxToPercentRect([1, 2, 3, 4], invalidHeight)).toBeNull();
    },
  );

  it('rejects invalid converted points and overflowing percentages', () => {
    for (const point of [[Number.NaN, 1], [1, Number.POSITIVE_INFINITY], [1], []]) {
      expect(bboxToPercentRect([1, 2, 3, 4], {
        width: 100, height: 100, convertToViewportPoint: () => point,
      })).toBeNull();
    }
    const tiny = viewport();
    tiny.width = Number.MIN_VALUE;
    expect(bboxToPercentRect([1, 2, 3, 4], tiny)).toBeNull();
  });

  it('uses all four corners for a non-axis-aligned transform', () => {
    expectRect(bboxToPercentRect([0, 0, 10, 10], {
      width: 100, height: 100, convertToViewportPoint: (x, y) => [x - y + 50, x + y],
    }), { leftPct: 40, topPct: 0, widthPct: 20, heightPct: 20 });
  });

  it('rejects singular transforms even when their bounding rectangle has area', () => {
    expect(bboxToPercentRect([0, 0, 10, 10], {
      width: 100, height: 100, convertToViewportPoint: (x, y) => [x + y, x + y],
    })).toBeNull();
  });
});
