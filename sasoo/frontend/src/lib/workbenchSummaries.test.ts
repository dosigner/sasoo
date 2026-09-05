import { describe, it, expect } from 'vitest';

import { buildAnalysisConfirmCopy, buildPhaseSummary, buildWorkbenchStatusSummary, qualitySummaryContradictsCounts } from './workbenchSummaries';
import type { AnalysisResults, AnalysisStatus, CostSummary, EvidenceAnchor, PhaseInfo, PhaseStatusValue, Recipe } from '@/lib/api';

function makePhases(statuses: PhaseStatusValue[]): PhaseInfo[] {
  const phaseNames: AnalysisStatus['phases'][number]['phase'][] = [
    'screening',
    'citation',
    'visual',
    'recipe',
    'deep_dive',
  ];
  return phaseNames.map((phase, i) => ({
    phase,
    status: statuses[i],
    started_at: null,
    completed_at: null,
    model_used: null,
    tokens_in: null,
    tokens_out: null,
    cost_usd: null,
    error_message: null,
  }));
}

function makeStatus(statuses: PhaseStatusValue[], overallStatus: string, currentPhase: AnalysisStatus['current_phase']): AnalysisStatus {
  return {
    paper_id: 1,
    overall_status: overallStatus,
    phases: makePhases(statuses),
    progress_pct: 0,
    current_phase: currentPhase,
    total_cost_usd: 0,
    total_tokens_in: 0,
    total_tokens_out: 0,
  };
}

describe('buildWorkbenchStatusSummary — progressRatio', () => {
  it('완료 5/5: progressRatio는 1이다', () => {
    const status = makeStatus(['completed', 'completed', 'completed', 'completed', 'completed'], 'completed', null);
    const summary = buildWorkbenchStatusSummary({
      status,
      figures: [],
      tables: [],
      recipe: null,
      visualizations: null,
    });
    expect(summary.progressRatio).toBe(1);
    expect(summary.completedCount).toBe(5);
    expect(summary.totalCount).toBe(5);
    expect(typeof summary.runStateLabel).toBe('string');
    expect(summary.runStateLabel.length).toBeGreaterThan(0);
  });

  it('진행 중 3/5: progressRatio는 0.6이다', () => {
    const status = makeStatus(
      ['completed', 'completed', 'completed', 'running', 'pending'],
      'running',
      'recipe',
    );
    const summary = buildWorkbenchStatusSummary({
      status,
      figures: [],
      tables: [],
      recipe: null,
      visualizations: null,
    });
    expect(summary.progressRatio).toBeCloseTo(0.6);
    expect(summary.completedCount).toBe(3);
    expect(summary.totalCount).toBe(5);
    expect(summary.currentPhaseLabel).toBeTruthy();
  });

  it('대기 0/5: progressRatio는 0이다', () => {
    const status = makeStatus(
      ['pending', 'pending', 'pending', 'pending', 'pending'],
      'pending',
      null,
    );
    const summary = buildWorkbenchStatusSummary({
      status,
      figures: [],
      tables: [],
      recipe: null,
      visualizations: null,
    });
    expect(summary.progressRatio).toBe(0);
    expect(summary.completedCount).toBe(0);
    expect(summary.totalCount).toBe(5);
    expect(summary.runStateLabel).toBe('분석 전');
  });

  it('기존 반환 필드(runStateLabel, trustStateLabel, nextActionLabel, currentPhaseLabel, completedCount, totalCount)는 그대로 유지된다', () => {
    const status = makeStatus(['completed', 'pending', 'pending', 'pending', 'pending'], 'running', 'citation');
    const summary = buildWorkbenchStatusSummary({
      status,
      figures: [],
      tables: [],
      recipe: null,
      visualizations: null,
    });
    expect(summary).toEqual(
      expect.objectContaining({
        runStateLabel: expect.any(String),
        trustStateLabel: expect.any(String),
        nextActionLabel: expect.any(String),
        currentPhaseLabel: expect.any(String),
        completedCount: 1,
        totalCount: 5,
      }),
    );
  });

  it('완료 + 시각화 있음: trustStateLabel이 상태 라인에서 우선 표시되는 값("심층 분석 완료")을 갖는다', () => {
    // 상태 라인은 컴포넌트에서 trustStateLabel || runStateLabel 순으로 표시한다.
    // trustStateLabel이 항상 채워지는 값임을 여기서 보장해 렌더 쪽 우선순위 로직의 전제를 지킨다.
    const status = makeStatus(['completed', 'completed', 'completed', 'completed', 'completed'], 'completed', null);
    const summary = buildWorkbenchStatusSummary({
      status,
      figures: [],
      tables: [],
      recipe: null,
      visualizations: { paper_id: 1, items: [{ id: 1 } as never], total_count: 1, model_used: 'x', planned_at: null },
    });
    expect(summary.trustStateLabel).toBe('심층 분석 완료');
    expect(summary.trustStateLabel.length).toBeGreaterThan(0);
  });
});

describe('buildWorkbenchStatusSummary — displayStatusLabel/statusTone', () => {
  it('미분석(status 없음): displayStatusLabel은 runStateLabel("분석 전")이고 톤은 accent다', () => {
    const summary = buildWorkbenchStatusSummary({
      status: null,
      figures: [],
      tables: [],
      recipe: null,
      visualizations: null,
    });
    expect(summary.displayStatusLabel).toBe('분석 전');
    expect(summary.displayStatusLabel).toBe(summary.runStateLabel);
    expect(summary.statusTone).toBe('accent');
  });

  it('진행 중: displayStatusLabel은 runStateLabel("~진행 중")이고 톤은 accent다', () => {
    const status = makeStatus(
      ['completed', 'completed', 'completed', 'running', 'pending'],
      'running',
      'recipe',
    );
    const summary = buildWorkbenchStatusSummary({
      status,
      figures: [],
      tables: [],
      recipe: null,
      visualizations: null,
    });
    expect(summary.displayStatusLabel).toBe(summary.runStateLabel);
    expect(summary.displayStatusLabel).toContain('진행 중');
    expect(summary.statusTone).toBe('accent');
  });

  it('실패: displayStatusLabel은 runStateLabel("분석 실패")이고 톤은 danger다', () => {
    const status = makeStatus(
      ['pending', 'pending', 'pending', 'pending', 'pending'],
      'error',
      null,
    );
    const summary = buildWorkbenchStatusSummary({
      status,
      figures: [],
      tables: [],
      recipe: null,
      visualizations: null,
    });
    expect(summary.displayStatusLabel).toBe('분석 실패');
    expect(summary.displayStatusLabel).toBe(summary.runStateLabel);
    expect(summary.statusTone).toBe('danger');
  });

  it('취소됨(terminalState cancelled): displayStatusLabel은 runStateLabel("취소됨")이고 톤은 danger다', () => {
    const status = makeStatus(
      ['completed', 'running', 'pending', 'pending', 'pending'],
      'running',
      'citation',
    );
    const summary = buildWorkbenchStatusSummary({
      status,
      figures: [],
      tables: [],
      recipe: null,
      visualizations: null,
      terminalState: 'cancelled',
    });
    expect(summary.displayStatusLabel).toBe('취소됨');
    expect(summary.displayStatusLabel).toBe(summary.runStateLabel);
    expect(summary.statusTone).toBe('danger');
  });

  it('완료: displayStatusLabel은 trustStateLabel이고 톤은 success다', () => {
    const status = makeStatus(['completed', 'completed', 'completed', 'completed', 'completed'], 'completed', null);
    const summary = buildWorkbenchStatusSummary({
      status,
      figures: [],
      tables: [],
      recipe: null,
      visualizations: null,
    });
    expect(summary.displayStatusLabel).toBe(summary.trustStateLabel);
    expect(summary.statusTone).toBe('success');
  });
});

function makeResults(screening: Record<string, unknown> | null): AnalysisResults {
  return {
    paper_id: 1,
    status: {} as AnalysisStatus,
    screening,
    citation: null,
    visual: null,
    recipe: null,
    deep_dive: null,
  };
}

describe('buildPhaseSummary(screening) — metaItems', () => {
  it('전체 필드가 있으면 분야·관련도·방법론·복잡도 4항목을 라벨/값 형태로 반환한다', () => {
    const results = makeResults({
      domain: 'Optics',
      relevance_score: 0.95,
      is_experimental: true,
      estimated_complexity: 'high',
    });
    const summary = buildPhaseSummary('screening', results, null, [], [], null);
    expect(summary.metaItems).toEqual([
      { label: '분야', value: 'Optics' },
      { label: '관련도', value: '95%', accent: true },
      { label: '방법론', value: '실험 논문' },
      { label: '복잡도', value: '높음' },
    ]);
  });

  it('원본 값이 결측이면 해당 항목이 생략된다', () => {
    const results = makeResults({ domain: 'Optics' });
    const summary = buildPhaseSummary('screening', results, null, [], [], null);
    expect(summary.metaItems).toEqual([{ label: '분야', value: 'Optics' }]);
  });

  it('estimated_complexity가 medium/low면 보통/낮음으로, is_experimental이 false면 비실험 논문으로 매핑된다', () => {
    const medium = buildPhaseSummary(
      'screening',
      makeResults({ estimated_complexity: 'medium', is_experimental: false }),
      null,
      [],
      [],
      null,
    );
    expect(medium.metaItems).toEqual([
      { label: '방법론', value: '비실험 논문' },
      { label: '복잡도', value: '보통' },
    ]);

    const low = buildPhaseSummary(
      'screening',
      makeResults({ estimated_complexity: 'low' }),
      null,
      [],
      [],
      null,
    );
    expect(low.metaItems).toEqual([{ label: '복잡도', value: '낮음' }]);
  });

  it('screening 결과가 전혀 없으면 metaItems는 빈 배열이다', () => {
    const summary = buildPhaseSummary('screening', null, null, [], [], null);
    expect(summary.metaItems).toEqual([]);
  });
});

function makeRecipeResults(recipeData: Record<string, unknown> | null): AnalysisResults {
  return {
    paper_id: 1,
    status: {} as AnalysisStatus,
    screening: null,
    citation: null,
    visual: null,
    recipe: recipeData,
    deep_dive: null,
  };
}

// RecipeCard.tsx의 evidenceCounts와 같은 경로(attachEvidence→summarizeAnchoredEvidence)를
// 태우기 위한 최소 Recipe 픽스처. anchor.target_label은 parseRecipeParameters가 만드는
// row.name과 정확히 같아야 fail-closed 매칭을 통과한다.
function makeRecipeWithEvidence(paramNames: string[], verifiedIndexes: number[], title = ''): Recipe {
  return {
    paper_id: 1,
    recipe: { title, parameters: paramNames.map((name) => ({ name, value: '1' })) },
    model_used: null,
    created_at: null,
    evidence: {
      verifier_version: 'v1',
      normalizer_version: 'v1',
      summary: { total: paramNames.length, verified: verifiedIndexes.length, by_display_status: {} },
      anchors: paramNames.map((name, i): EvidenceAnchor => ({
        target_index: i,
        target_key: name,
        target_label: name,
        source_tag: null,
        claimed_quote: null,
        claimed_page: null,
        quote_status: '',
        page_status: '',
        value_status: '',
        display_status: verifiedIndexes.includes(i) ? 'VERIFIED' : 'UNVERIFIED_NOT_FOUND',
        match_method: null,
        match_ratio: null,
        matched_quote: null,
        matched_page: null,
        bbox: null,
        corpus: '',
        failure_detail: null,
        verifier_version: 'v1',
        normalizer_version: 'v1',
      })),
    },
  };
}

describe('buildPhaseSummary(recipe) — summaryLine은 title 중복 대신 파라미터/근거 사실 요약', () => {
  it('recipe(evidence 포함)가 있으면 "파라미터 N개, 근거 확인 M건"을 보여주고 title을 반복하지 않는다', () => {
    const results = makeRecipeResults({
      title: '광섬유 도핑 공정 재현',
      parameters: [{ name: 'A', value: '1' }, { name: 'B', value: '2' }, { name: 'C', value: '3' }],
    });
    const recipe = makeRecipeWithEvidence(['A', 'B', 'C'], [0, 2], '광섬유 도핑 공정 재현');
    const summary = buildPhaseSummary('recipe', results, recipe, [], [], null);
    expect(summary.summaryLine).toBe('파라미터 3개, 근거 확인 2건');
    expect(summary.summaryLine).not.toBe('광섬유 도핑 공정 재현');
  });

  it('recipe 객체(evidence) 없이 results.recipe만 있으면 근거 수를 계산할 수 없어 고정 문구를 보여준다', () => {
    const results = makeRecipeResults({
      title: '광섬유 도핑 공정 재현',
      parameters: [{ name: 'A', value: '1' }],
    });
    const summary = buildPhaseSummary('recipe', results, null, [], [], null);
    expect(summary.summaryLine).toBe('재현 파라미터와 근거를 정리했어요.');
  });

  it('파라미터가 0개면 추출 실패를 알리는 문구를 보여준다', () => {
    const results = makeRecipeResults({ title: '제목만 있음', parameters: [] });
    const summary = buildPhaseSummary('recipe', results, null, [], [], null);
    expect(summary.summaryLine).toBe('레시피 정보를 더 확인해야 해요.');
  });
});

describe('buildPhaseSummary(deep_dive) — 신구 스키마 요약', () => {
  function makeDeepDiveResults(deepDive: Record<string, unknown>): AnalysisResults {
    return {
      paper_id: 1,
      status: {} as AnalysisStatus,
      screening: null,
      citation: null,
      visual: null,
      recipe: null,
      deep_dive: deepDive,
    };
  }

  it('신 스키마면 problem_definition이 요약줄이 된다', () => {
    const summary = buildPhaseSummary(
      'deep_dive',
      makeDeepDiveResults({ problem_definition: '수차 보정이 느린 것이 문제다', strengths: ['a'] }),
      null,
      [],
      [],
      null,
    );
    expect(summary.summaryLine).toBe('수차 보정이 느린 것이 문제다');
  });

  it('구 캐시(detailed_analysis만 있음)면 그 본문이 요약줄로 남는다', () => {
    const summary = buildPhaseSummary(
      'deep_dive',
      makeDeepDiveResults({ detailed_analysis: '옛 형식의 분석 본문' }),
      null,
      [],
      [],
      null,
    );
    expect(summary.summaryLine).toBe('옛 형식의 분석 본문');
  });
});

describe('qualitySummaryContradictsCounts', () => {
  it('개수가 1개 이상인데 서술에 부정 표현이 있으면 모순으로 판정한다', () => {
    expect(qualitySummaryContradictsCounts('이 논문에서는 그림과 표를 추출하지 못했어요.', 17, 1)).toBe(true);
    expect(qualitySummaryContradictsCounts('no figure was extracted', 3, 0)).toBe(true);
  });

  it('개수가 0이면 서술 내용과 무관하게 모순이 아니다', () => {
    expect(qualitySummaryContradictsCounts('그림과 표를 추출하지 못했어요.', 0, 0)).toBe(false);
  });

  it('개수가 1개 이상이고 서술에 부정 표현이 없으면 모순이 아니다', () => {
    expect(qualitySummaryContradictsCounts('다이어그램 위주로 잘 정리됐어요.', 5, 0)).toBe(false);
  });
});

function makeVisualResults(visual: Record<string, unknown> | null): AnalysisResults {
  return {
    paper_id: 1,
    status: {} as AnalysisStatus,
    screening: null,
    citation: null,
    visual,
    recipe: null,
    deep_dive: null,
  };
}

describe('buildPhaseSummary(visual) — 개수 사실과 모델 서술의 분리', () => {
  it('(a) 그림 17, 표 1, 모델 서술이 "추출하지 못했다"면 첫 줄은 개수 문장이고 모델 서술은 숨겨진다', () => {
    const results = makeVisualResults({
      figure_count: 17,
      tables_found: 1,
      quality_summary: '이 논문에서는 그림과 표를 추출하지 못해 텍스트 분석만으로 진행했어요.',
    });
    const summary = buildPhaseSummary('visual', results, null, [], [], null);
    expect(summary.summaryLine).toBe('그림 17개와 표 1개를 추출했어요.');
    expect(summary.figureLine).toBe('그림 17개를 추출했어요.');
    expect(summary.tableLine).toBe('표 1개를 복구했어요.');
    expect(summary.detailLine).toBeNull();
  });

  it('(b) 그림 0, 표 0이면 추출 실패를 알리는 부정 문장을 보여준다', () => {
    const results = makeVisualResults({ figure_count: 0, tables_found: 0, quality_summary: '텍스트 위주 논문이에요.' });
    const summary = buildPhaseSummary('visual', results, null, [], [], null);
    expect(summary.summaryLine).toBe('그림과 표를 추출하지 못해 텍스트 분석만으로 진행했어요.');
    expect(summary.figureLine).toBe('그림과 표를 추출하지 못해 텍스트 분석만으로 진행했어요.');
    expect(summary.tableLine).toBe('그림과 표를 추출하지 못해 텍스트 분석만으로 진행했어요.');
  });

  it('(c) 개수와 모순 없는 모델 서술은 둘째 줄(detailLine)로 유지된다', () => {
    const results = makeVisualResults({
      figure_count: 5,
      tables_found: 0,
      quality_summary: '광학계 다이어그램 위주로 시각 자료가 잘 정리돼 있어요.',
    });
    const summary = buildPhaseSummary('visual', results, null, [], [], null);
    expect(summary.figureLine).toBe('그림 5개를 추출했어요.');
    expect(summary.detailLine).toBe('광학계 다이어그램 위주로 시각 자료가 잘 정리돼 있어요.');
  });

  it('(d) 그림 탭과 표 탭 문장은 서로 다르다', () => {
    const results = makeVisualResults({ figure_count: 17, tables_found: 1 });
    const summary = buildPhaseSummary('visual', results, null, [], [], null);
    expect(summary.figureLine).not.toBe(summary.tableLine);
    expect(summary.figureLine).toContain('그림');
    expect(summary.tableLine).toContain('표');
  });

  it('figureCount/tableCount는 visual 필드가 없으면 figures/tables 배열 길이로 대체된다', () => {
    const results = makeVisualResults({});
    const summary = buildPhaseSummary(
      'visual',
      results,
      null,
      [{ id: 1 } as never, { id: 2 } as never],
      [{ id: 1 } as never],
      null,
    );
    expect(summary.figureLine).toBe('그림 2개를 추출했어요.');
    expect(summary.tableLine).toBe('표 1개를 복구했어요.');
  });
});

function makeCostSummary(perPaperTotals: number[], avgCostPerPaper: number): CostSummary {
  return {
    monthly_costs: [],
    per_paper_costs: perPaperTotals.map((total_usd, i) => ({
      paper_id: i + 1,
      title: `paper-${i + 1}`,
      total_usd,
      tokens_in: 0,
      tokens_out: 0,
      phases: {},
    })),
    by_model: [],
    current_month: { month: '2026-09', cost_usd: 0, tokens_in: 0, tokens_out: 0, papers_analyzed: perPaperTotals.length },
    totals: {
      total_papers: perPaperTotals.length,
      total_cost_usd: perPaperTotals.reduce((a, b) => a + b, 0),
      avg_cost_per_paper: avgCostPerPaper,
      total_tokens_in: 0,
      total_tokens_out: 0,
    },
    efficiency: {
      phase_call_counts: {},
      estimated_cached_calls_saved: 0,
      estimated_cached_cost_usd_saved: 0,
      uncertain_table_repair_calls: 0,
      review_required_tables: 0,
    },
  };
}

describe('buildAnalysisConfirmCopy — 4가지 최초/재분석 x 이력유무 조합', () => {
  it('최초 분석 + 이력 없음: 제목은 "분석을 시작할까요?", 확인 버튼은 "분석 시작", 추정 비용 문구를 보여준다', () => {
    const copy = buildAnalysisConfirmCopy({
      isReanalyze: false,
      provider: 'openai',
      costSummary: makeCostSummary([], 0),
    });
    expect(copy.title).toBe('분석을 시작할까요?');
    expect(copy.confirmLabel).toBe('분석 시작');
    expect(copy.reanalyzeNotice).toBeNull();
    expect(copy.providerLine).toBe('논문 분석에 OpenAI를 사용해요.');
    expect(copy.costLine).toContain('추정값');
    expect(copy.costLine).toContain('OpenAI');
  });

  it('최초 분석 + 이력 있음: 실측 평균/최대 비용 문구를 보여준다', () => {
    const copy = buildAnalysisConfirmCopy({
      isReanalyze: false,
      provider: 'gemini',
      costSummary: makeCostSummary([0.01, 0.015, 0.008], 0.011),
    });
    expect(copy.title).toBe('분석을 시작할까요?');
    expect(copy.confirmLabel).toBe('분석 시작');
    expect(copy.providerLine).toBe('논문 분석에 Google Gemini를 사용해요.');
    expect(copy.costLine).toBe('전체 평균 $0.011 / 논문 (최대 $0.015)');
  });

  it('재분석 + 이력 없음: 제목은 "다시 분석할까요?", 대체 안내와 "다시 분석" 버튼을 보여준다', () => {
    const copy = buildAnalysisConfirmCopy({
      isReanalyze: true,
      provider: 'openai',
      costSummary: makeCostSummary([], 0),
    });
    expect(copy.title).toBe('다시 분석할까요?');
    expect(copy.confirmLabel).toBe('다시 분석');
    expect(copy.reanalyzeNotice).toBe(
      '기존 분석 결과(요약, 인용, 그림과 표, 레시피, 시각화)가 새 결과로 대체돼요.',
    );
    expect(copy.costLine).toContain('추정값');
  });

  it('재분석 + 이력 있음: 대체 안내와 실측 비용 문구를 함께 보여준다', () => {
    const copy = buildAnalysisConfirmCopy({
      isReanalyze: true,
      provider: 'gemini',
      costSummary: makeCostSummary([0.02, 0.03], 0.025),
    });
    expect(copy.title).toBe('다시 분석할까요?');
    expect(copy.confirmLabel).toBe('다시 분석');
    expect(copy.reanalyzeNotice).toBe(
      '기존 분석 결과(요약, 인용, 그림과 표, 레시피, 시각화)가 새 결과로 대체돼요.',
    );
    expect(copy.costLine).toBe('전체 평균 $0.025 / 논문 (최대 $0.030)');
  });

  it('비용 조회 실패(costSummary=null)면 비용 줄을 숨기고 나머지는 정상 렌더된다', () => {
    const copy = buildAnalysisConfirmCopy({
      isReanalyze: false,
      provider: 'openai',
      costSummary: null,
    });
    expect(copy.costLine).toBeNull();
    expect(copy.title).toBe('분석을 시작할까요?');
    expect(copy.providerLine).toBe('논문 분석에 OpenAI를 사용해요.');
  });

  it('공급사 조회 실패(provider=null)면 provider 줄은 숨기고 이력 없음 비용 줄은 일반 문구로 대체된다', () => {
    const copy = buildAnalysisConfirmCopy({
      isReanalyze: false,
      provider: null,
      costSummary: makeCostSummary([], 0),
    });
    expect(copy.providerLine).toBeNull();
    expect(copy.costLine).toBe('첫 분석이라 추정값이에요. 예상 비용은 논문당 $0.01 ~ $0.05예요.');
  });
});
