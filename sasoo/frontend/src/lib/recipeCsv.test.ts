import { describe, expect, it } from 'vitest';
import type { EvidenceAnchor, Recipe } from '@/lib/api';
import { RECIPE_CSV_HEADER, generateCsvFromRecipe } from '@/lib/recipeCsv';

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

describe('generateCsvFromRecipe', () => {
  it('헤더는 기존 3열 뒤에 근거 6열을 붙인다', () => {
    const [header] = rows(generateCsvFromRecipe(recipeWith(null)));
    expect(header.slice(0, 3)).toEqual(['Section', 'Key', 'Value']);
    expect(header).toEqual([...RECIPE_CSV_HEADER]);
    expect(header).toHaveLength(9);
  });

  it('모든 행의 열 수가 헤더와 같다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({})]));
    for (const row of rows(csv)) {
      expect(row.length).toBeGreaterThanOrEqual(9);
    }
  });

  it('검증 메타 행을 상단에 남긴다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({})]));
    expect(csv).toContain('Meta,Verifier,ev1/norm-v1');
    expect(csv).toContain('Meta,Evidence Verified,1/1');
  });

  it('VERIFIED 행만 확인된 인용 열을 채운다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({})]));
    const paramRow = rows(csv).find((row) => row[0] === 'Parameter' && row[1] === 'temp');
    expect(paramRow).toBeDefined();
    expect(paramRow![3]).toBe('VERIFIED');
    expect(paramRow![6]).toBe('annealed at 500 C');   // Evidence Quote (verified)
    expect(paramRow![7]).toBe('');                     // Claimed Quote (unverified)
  });

  it('미검증 행은 주장 인용을 별도 열에 넣고 확인 열은 비운다', () => {
    const csv = generateCsvFromRecipe(
      recipeWith([anchor({ display_status: 'UNVERIFIED_NOT_FOUND', matched_quote: null, matched_page: null })]),
    );
    const paramRow = rows(csv).find((row) => row[0] === 'Parameter' && row[1] === 'temp');
    expect(paramRow![3]).toBe('UNVERIFIED_NOT_FOUND');
    expect(paramRow![6]).toBe('');
    expect(paramRow![7]).toBe('annealed at 500 C');
  });

  it('앵커가 없는 파라미터는 UNVERIFIED_NOT_RUN으로 나간다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({})]));
    const paramRow = rows(csv).find((row) => row[0] === 'Parameter' && row[1] === 'power');
    expect(paramRow![3]).toBe('UNVERIFIED_NOT_RUN');
  });

  it('Info·Material·Step 행의 근거 열은 비어 있다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({})]));
    for (const row of rows(csv)) {
      if (['Info', 'Material', 'Equipment', 'Step', 'Critical Note', 'Meta'].includes(row[0])) {
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
