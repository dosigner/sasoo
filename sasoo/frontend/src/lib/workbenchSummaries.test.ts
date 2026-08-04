import { describe, it, expect } from 'vitest';

import { buildPhaseSummary, buildWorkbenchStatusSummary } from './workbenchSummaries';
import type { AnalysisResults, AnalysisStatus, PhaseInfo, PhaseStatusValue } from '@/lib/api';

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
