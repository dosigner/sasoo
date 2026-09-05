import { describe, it, expect } from 'vitest';

import { detectCitations } from './citations';

describe('detectCitations — Latin forms', () => {
  it('detects "Fig. 3" as a figure', () => {
    const [m] = detectCitations('보다시피 Fig. 3에서 확인할 수 있다.');
    expect(m).toMatchObject({ raw: 'Fig. 3', type: 'figure', n: 3 });
  });

  it('detects "Figure 5" as a figure', () => {
    const [m] = detectCitations('Figure 5 shows the setup.');
    expect(m).toMatchObject({ raw: 'Figure 5', type: 'figure', n: 5 });
  });

  it('detects "Table 2" as a table', () => {
    const [m] = detectCitations('See Table 2 for details.');
    expect(m).toMatchObject({ raw: 'Table 2', type: 'table', n: 2 });
  });

  it('detects "p.12" as a page', () => {
    const [m] = detectCitations('설명은 p.12를 참고하라.');
    expect(m).toMatchObject({ raw: 'p.12', type: 'page', n: 12 });
  });
});

describe('detectCitations — Korean forms', () => {
  it('detects "그림 3" as a figure', () => {
    const [m] = detectCitations('그림 3에서 구조를 보여준다.');
    expect(m).toMatchObject({ raw: '그림 3', type: 'figure', n: 3 });
  });

  it('detects "표 2" as a table', () => {
    const [m] = detectCitations('표 2는 성능 비교 결과다.');
    expect(m).toMatchObject({ raw: '표 2', type: 'table', n: 2 });
  });

  it('does not treat "발표 3" as a table reference (표 lookbehind)', () => {
    expect(detectCitations('학회 발표 3건을 진행했다.')).toHaveLength(0);
  });

  it('detects "페이지 12" as a page', () => {
    const [m] = detectCitations('자세한 내용은 페이지 12를 보라.');
    expect(m).toMatchObject({ raw: '페이지 12', type: 'page', n: 12 });
  });

  it('detects "12페이지" (numeral-first) as a page', () => {
    const [m] = detectCitations('12페이지에 정의가 나온다.');
    expect(m).toMatchObject({ raw: '12페이지', type: 'page', n: 12 });
  });

  it('does not match "페이지" inside a longer word like "홈페이지" without a preceding digit', () => {
    expect(detectCitations('회사 홈페이지를 방문하라.')).toHaveLength(0);
  });
});

describe('detectCitations — multiple matches', () => {
  it('detects several citations left to right without overlap', () => {
    const matches = detectCitations('그림 3(p.12)과 표 2를 함께 보라.');
    expect(matches.map((m) => [m.type, m.n])).toEqual([
      ['figure', 3],
      ['page', 12],
      ['table', 2],
    ]);
  });

  it('returns an empty array when there is no citation', () => {
    expect(detectCitations('아무 참조도 없는 문장입니다.')).toHaveLength(0);
  });
});
