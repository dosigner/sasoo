import { describe, expect, it } from 'vitest';
import type { EvidenceAnchor, Recipe } from '@/lib/api';
import { RECIPE_CSV_HEADER, generateCsvFromRecipe } from '@/lib/recipeCsv';

// 열 위치를 숫자로 흩뿌리면 열 순서를 바꿀 때 어디가 깨졌는지 못 읽는다.
const COL = {
  section: 0,
  key: 1,
  value: 2,
  status: 3,
  method: 4,
  foundQuote: 5,
  foundPage: 6,
  claimedQuote: 7,
  claimedPage: 8,
} as const;

function anchor(overrides: Partial<EvidenceAnchor>): EvidenceAnchor {
  return {
    target_index: 0,
    target_key: 'p000:temp',
    target_label: 'temp',
    source_tag: 'explicit',
    claimed_quote: 'annealed at 500 C',
    claimed_page: 3,
    quote_status: 'verified_exact',
    page_status: 'match',
    value_status: 'value_in_quote',
    display_status: 'VERIFIED',
    match_method: 'exact',
    match_ratio: 1,
    matched_quote: 'annealed at 500 C',
    matched_page: 3,
    bbox: null,
    corpus: 'pdf_text',
    failure_detail: null,
    verifier_version: 'ev1',
    normalizer_version: 'norm-v1',
    ...overrides,
  };
}

function recipeWith(anchors: EvidenceAnchor[] | null): Recipe {
  return {
    paper_id: 1,
    model_used: 'gemini',
    created_at: '2026-08-06',
    recipe: {
      title: '레시피',
      objective: '목적',
      materials: ['재료 A'],
      parameters: [
        { name: 'temp', value: '500', unit: 'C', notes: 'Methods' },
        { name: 'power', value: '3.2', unit: 'mW', notes: '' },
      ],
      steps: ['1단계'],
    },
    evidence: anchors
      ? {
          verifier_version: 'ev1',
          normalizer_version: 'norm-v1',
          summary: { total: anchors.length, verified: 1, by_display_status: {} },
          anchors,
        }
      : null,
  };
}

function rows(csv: string): string[][] {
  return csv.split('\n').map((line) => line.split(','));
}

function paramRow(csv: string, name: string): string[] {
  const row = rows(csv).find((r) => r[COL.section] === 'Parameter' && r[COL.key] === name);
  expect(row).toBeDefined();
  return row!;
}

describe('generateCsvFromRecipe — 열 계약', () => {
  it('헤더는 9열이고 이름이 상태 중립 한국어다 (DEC-012)', () => {
    const [header] = rows(generateCsvFromRecipe(recipeWith(null)));
    expect(header).toEqual([
      '구분',
      '항목',
      '값',
      '검증 상태',
      '검증 방법',
      '발견 인용',
      '발견 페이지',
      '주장 인용',
      '주장 페이지',
    ]);
    expect(header).toEqual([...RECIPE_CSV_HEADER]);
    expect(header).toHaveLength(9);
  });

  it('열 이름에 "verified" 같은 검증 도장을 남기지 않는다', () => {
    // 이름이 상태를 단정하면 미검증 행을 채우는 순간 조용한 승격이 된다.
    const header = RECIPE_CSV_HEADER.join(' ').toLowerCase();
    expect(header).not.toContain('verified');
    expect(header).not.toContain('확인');
  });

  it('모든 행의 열 수가 헤더와 같다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({})]));
    for (const row of rows(csv)) {
      expect(row.length).toBeGreaterThanOrEqual(9);
    }
  });

  it('Info·Material·Step 행의 근거 열은 비어 있다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({})]));
    for (const row of rows(csv)) {
      if (['Info', 'Material', 'Equipment', 'Step', 'Critical Note', 'Meta'].includes(row[COL.section])) {
        expect(row.slice(3).every((cell) => cell === '')).toBe(true);
      }
    }
  });

  it('인용의 쉼표·따옴표·개행을 이스케이프한다', () => {
    const csv = generateCsvFromRecipe(
      recipeWith([anchor({ matched_quote: 'a "quoted", multi\nline span' })]),
    );
    expect(csv).toContain('"a ""quoted"", multi\nline span"');
  });
});

describe('generateCsvFromRecipe — 상태와 방법은 화면과 같은 한국어 라벨', () => {
  it('검증 상태를 코드가 아니라 화면 라벨로 적는다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({})]));
    expect(paramRow(csv, 'temp')[COL.status]).toBe('원문 확인');
    expect(csv).not.toContain('UNVERIFIED_');
  });

  it('검증 방법도 한국어 라벨이다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({ match_method: 'normalized' })]));
    expect(paramRow(csv, 'temp')[COL.method]).toBe('표기 정규화 일치');
  });

  it('모르는 방법 코드는 원본 문자열을 그대로 남긴다 (정보를 버리지 않는다)', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({ match_method: 'future_method' })]));
    expect(paramRow(csv, 'temp')[COL.method]).toBe('future_method');
  });

  it('앵커가 없는 파라미터는 검증 미실행으로 나간다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({})]));
    expect(paramRow(csv, 'power')[COL.status]).toBe('검증 미실행');
  });
});

describe('generateCsvFromRecipe — 발견 인용 노출 범위 (DEC-012)', () => {
  it('VERIFIED는 발견 인용과 발견 페이지를 채운다', () => {
    const row = paramRow(generateCsvFromRecipe(recipeWith([anchor({})])), 'temp');
    expect(row[COL.foundQuote]).toBe('annealed at 500 C');
    expect(row[COL.foundPage]).toBe('3');
  });

  it('PAGE_MISMATCH도 발견 인용과 발견 페이지를 채운다', () => {
    // 페이지만 어긋난 near-miss는 인용 자체가 원문에 축자로 있다 — 숨기면 정보 손실이다.
    const csv = generateCsvFromRecipe(
      recipeWith([
        anchor({
          display_status: 'UNVERIFIED_PAGE_MISMATCH',
          page_status: 'mismatch',
          matched_page: 7,
          matched_quote: 'annealed at 500 C',
        }),
      ]),
    );
    const row = paramRow(csv, 'temp');
    expect(row[COL.status]).toBe('다른 페이지에서 발견');
    expect(row[COL.foundQuote]).toBe('annealed at 500 C');
    expect(row[COL.foundPage]).toBe('7');
    expect(row[COL.claimedPage]).toBe('3');
  });

  it('부분 일치·모호·값 불일치는 발견 인용과 발견 페이지를 함께 비운다', () => {
    // partial은 위조 인용 81%가 통과한 실측이 있다. 이 목록을 넓히지 마라.
    // 페이지만 남기면 찾지도 못한 위치를 "발견"이라 부르는 셈이라 인용과 같이 막는다.
    for (const status of ['UNVERIFIED_PARTIAL', 'UNVERIFIED_AMBIGUOUS', 'UNVERIFIED_VALUE_MISMATCH'] as const) {
      const csv = generateCsvFromRecipe(
        recipeWith([anchor({ display_status: status, matched_quote: '위조된 원문 조각', matched_page: 8 })]),
      );
      const row = paramRow(csv, 'temp');
      expect(row[COL.foundQuote]).toBe('');
      expect(row[COL.foundPage]).toBe('');
      expect(csv).not.toContain('위조된 원문 조각');
      // 주장 페이지는 남는다 — LLM이 무엇을 주장했는지는 상태와 무관한 기록이다.
      expect(row[COL.claimedPage]).toBe('3');
    }
  });

  it('원문에서 찾지 못한 행은 발견 인용이 비고 주장 인용만 남는다', () => {
    const csv = generateCsvFromRecipe(
      recipeWith([
        anchor({ display_status: 'UNVERIFIED_NOT_FOUND', matched_quote: null, matched_page: null }),
      ]),
    );
    const row = paramRow(csv, 'temp');
    expect(row[COL.foundQuote]).toBe('');
    expect(row[COL.foundPage]).toBe('');
    expect(row[COL.claimedQuote]).toBe('annealed at 500 C');
  });

  it('주장 인용과 주장 페이지는 상태와 무관하게 그대로 싣는다', () => {
    // 두 열은 "LLM이 뭐라고 했는가"의 기록이다. 검증 결과에 따라 지우면 재현이 안 된다.
    const verified = paramRow(generateCsvFromRecipe(recipeWith([anchor({})])), 'temp');
    expect(verified[COL.claimedQuote]).toBe('annealed at 500 C');
    expect(verified[COL.claimedPage]).toBe('3');
  });
});

describe('generateCsvFromRecipe — 메타 행', () => {
  it('검증기 버전을 남긴다', () => {
    expect(generateCsvFromRecipe(recipeWith([anchor({})]))).toContain('Meta,Verifier,ev1/norm-v1');
  });

  it('검증 요약은 백엔드 summary가 아니라 화면과 같은 분모로 센다', () => {
    // 파라미터 2개 중 앵커는 1개(VERIFIED). 백엔드 summary는 1/1이라고 하지만
    // 화면과 CSV에는 2행이 있으므로 1/2가 맞다.
    const csv = generateCsvFromRecipe(recipeWith([anchor({})]));
    expect(csv).toContain('Meta,Evidence Verified,1/2');
    expect(csv).not.toContain('Meta,Evidence Verified,1/1');
  });

  it('라벨 불일치로 숨겨진 앵커는 분자에서 빠진다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({ target_label: '엉뚱한이름' })]));
    expect(csv).toContain('Meta,Evidence Verified,0/2');
  });

  it('근거 기록이 없으면 not_run으로 표시한다', () => {
    expect(generateCsvFromRecipe(recipeWith(null))).toContain('Meta,Verifier,not_run');
  });
});
