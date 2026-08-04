import { describe, it, expect } from 'vitest';

import { buildWorkbenchStatusSummary } from './workbenchSummaries';
import type { AnalysisStatus, PhaseInfo, PhaseStatusValue } from '@/lib/api';

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

describe('buildWorkbenchStatusSummary — stageNames/progressRatio', () => {
  it('완료 5/5: progressRatio는 1이고 stageNames는 5단계다', () => {
    const status = makeStatus(['completed', 'completed', 'completed', 'completed', 'completed'], 'completed', null);
    const summary = buildWorkbenchStatusSummary({
      status,
      figures: [],
      tables: [],
      recipe: null,
      visualizations: null,
    });
    expect(summary.stageNames.length).toBe(5);
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
    expect(summary.stageNames.length).toBe(5);
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
    expect(summary.stageNames.length).toBe(5);
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
});
