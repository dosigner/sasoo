import type {
  AnalysisPhase,
  AnalysisResults,
  AnalysisStatus,
  Figure,
  Recipe,
  VisualizationPlan,
} from '@/lib/api';

type PhaseTone = 'primary' | 'muted' | 'practical';

export interface PhaseSummary {
  summaryLine: string | null;
  collapsedMeta: string[];
  expandedMeta: string[];
  tone: PhaseTone;
}

export interface WorkbenchStatusSummary {
  runStateLabel: string;
  trustStateLabel: string;
  nextActionLabel: string;
  currentPhaseLabel: string;
  completedCount: number;
  totalCount: number;
}

const PHASE_LABELS: Record<AnalysisPhase, string> = {
  screening: '스크리닝',
  citation: '인용 분석',
  visual: 'Figure 검토',
  recipe: '레시피',
  deep_dive: '심층 분석',
};

function percent(value: unknown): string | null {
  if (typeof value !== 'number' || Number.isNaN(value)) return null;
  const normalized = value <= 1 ? value * 100 : value;
  return `${Math.round(normalized)}%`;
}

function shortText(value: unknown, fallback: string): string {
  if (typeof value !== 'string' || !value.trim()) return fallback;
  const trimmed = value.trim().replace(/\s+/g, ' ');
  return trimmed.length > 88 ? `${trimmed.slice(0, 85)}...` : trimmed;
}

function countList(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

export function buildPhaseSummary(
  phase: 'screening' | 'citation' | 'visual' | 'recipe' | 'deep_dive',
  results: AnalysisResults | null,
  recipe: Recipe | null,
  figures: Figure[],
  visualizations: VisualizationPlan | null,
): PhaseSummary {
  if (!results) {
    return {
      summaryLine: null,
      collapsedMeta: [],
      expandedMeta: [],
      tone: phase === 'screening' ? 'primary' : phase === 'visual' || phase === 'recipe' ? 'practical' : 'muted',
    };
  }

  const screening = results.screening ?? {};
  const citation = results.citation ?? {};
  const visual = results.visual ?? {};
  const deepDive = results.deep_dive ?? {};
  const recipeResult = recipe?.recipe ?? results.recipe ?? {};

  if (phase === 'screening') {
    const domain = typeof screening.domain === 'string' ? screening.domain : '미분류';
    const relevance = percent(screening.relevance_score);
    const agent = typeof screening.agent_recommended === 'string' ? screening.agent_recommended : null;
    return {
      summaryLine: shortText(screening.summary, '논문의 핵심 맥락을 정리합니다.'),
      collapsedMeta: [domain, relevance ? `관련도 ${relevance}` : '', agent ? `추천 ${agent}` : ''].filter(Boolean),
      expandedMeta: [
        typeof screening.methodology_type === 'string' ? screening.methodology_type : '',
        typeof screening.estimated_complexity === 'string' ? `복잡도 ${screening.estimated_complexity}` : '',
        screening.is_experimental === true ? '실험 논문' : screening.is_experimental === false ? '비실험 논문' : '',
      ].filter(Boolean),
      tone: 'primary',
    };
  }

  if (phase === 'citation') {
    const totalRefs = typeof citation.total_references === 'number' ? citation.total_references : 0;
    const style = typeof citation.citation_style === 'string' ? citation.citation_style : '';
    const selfCount = typeof citation.self_citation_count === 'number' ? citation.self_citation_count : null;
    return {
      summaryLine: shortText(citation.summary, totalRefs > 0 ? '참고문헌 구조를 빠르게 훑어볼 수 있습니다.' : '참고문헌 정보를 찾지 못했습니다.'),
      collapsedMeta: [
        totalRefs > 0 ? `${totalRefs}개 참고문헌` : '참고문헌 없음',
        style,
        selfCount != null ? `자기 인용 ${selfCount}` : '',
      ].filter(Boolean),
      expandedMeta: [
        countList(citation.top_cited) > 0 ? `주요 인용 ${countList(citation.top_cited)}건` : '',
        Object.keys((citation.citation_distribution as Record<string, number> | undefined) ?? {}).length > 0 ? '섹션 분포 포함' : '',
      ].filter(Boolean),
      tone: 'muted',
    };
  }

  if (phase === 'visual') {
    const figureCount =
      typeof visual.figure_count === 'number' && visual.figure_count > 0
        ? visual.figure_count
        : figures.length;
    return {
      summaryLine: shortText(visual.quality_summary, figureCount > 0 ? '추출된 figure와 데이터 시각 요소를 정리했습니다.' : '추출된 figure가 없습니다.'),
      collapsedMeta: [
        figureCount > 0 ? `Figure ${figureCount}개` : 'Figure 없음',
        typeof visual.tables_found === 'number' ? `표 ${visual.tables_found}` : '',
        typeof visual.equations_found === 'number' ? `수식 ${visual.equations_found}` : '',
      ].filter(Boolean),
      expandedMeta: [
        countList(visual.diagram_types) > 0 ? `유형 ${countList(visual.diagram_types)}개` : '',
        countList(visual.key_findings_from_visuals) > 0 ? `핵심 발견 ${countList(visual.key_findings_from_visuals)}개` : '',
      ].filter(Boolean),
      tone: 'practical',
    };
  }

  if (phase === 'recipe') {
    const params = Array.isArray(recipeResult.parameters) ? recipeResult.parameters.length : 0;
    const confidence = percent(recipeResult.confidence);
    const title = typeof recipeResult.title === 'string' ? recipeResult.title : '';
    return {
      summaryLine: title || (params > 0 ? '실험 재현을 위한 핵심 정보가 정리되어 있습니다.' : '레시피 정보를 더 확인해야 합니다.'),
      collapsedMeta: [
        title ? '레시피 추출됨' : recipe ? '레시피 준비됨' : '레시피 없음',
        params > 0 ? `파라미터 ${params}개` : '파라미터 없음',
        confidence ? `신뢰도 ${confidence}` : '',
      ].filter(Boolean),
      expandedMeta: [
        countList(recipeResult.materials) > 0 ? `재료 ${countList(recipeResult.materials)}개` : '',
        countList(recipeResult.steps) > 0 ? `절차 ${countList(recipeResult.steps)}단계` : '',
      ].filter(Boolean),
      tone: 'practical',
    };
  }

  const strengths = countList(deepDive.strengths);
  const weaknesses = countList(deepDive.weaknesses);
  const vizCount = visualizations?.items.length ?? 0;

  return {
    summaryLine: shortText(deepDive.detailed_analysis, vizCount > 0 ? '심층 분석과 시각화가 준비되어 있습니다.' : '심층 분석 결과를 정리했습니다.'),
    collapsedMeta: [
      vizCount > 0 ? `시각화 ${vizCount}개` : '시각화 대기',
      strengths > 0 ? `강점 ${strengths}` : '',
      weaknesses > 0 ? `약점 ${weaknesses}` : '',
    ].filter(Boolean),
    expandedMeta: [
      countList(deepDive.follow_up_questions) > 0 ? `후속 질문 ${countList(deepDive.follow_up_questions)}개` : '',
      countList(deepDive.practical_applications) > 0 ? `응용 ${countList(deepDive.practical_applications)}개` : '',
    ].filter(Boolean),
    tone: 'muted',
  };
}

export function buildChatStarterPrompts({
  results,
  figures,
  recipe,
}: {
  results: AnalysisResults | null;
  figures: Figure[];
  recipe: Recipe | null;
}): string[] {
  const prompts = ['이 논문의 핵심 기여는?'];

  if (figures.length > 0) {
    prompts.push('이 figure가 의미하는 바는?');
  }

  if (recipe) {
    prompts.push('실험 재현 시 위험 요소는?');
  } else if (results?.deep_dive || results?.screening) {
    prompts.push('이 연구의 약점은 무엇인가?');
  }

  return prompts.slice(0, 3);
}

export function statusMeta(status: AnalysisStatus | null): string | null {
  if (!status || status.overall_status === 'pending') return null;
  if (status.overall_status === 'running' || status.overall_status === 'analyzing') {
    return `분석 ${Math.round(status.progress_pct || 0)}%`;
  }
  return '분석 완료';
}

export function buildWorkbenchStatusSummary({
  status,
  figures,
  recipe,
  visualizations,
  terminalState,
}: {
  status: AnalysisStatus | null;
  figures: Figure[];
  recipe: Recipe | null;
  visualizations: VisualizationPlan | null;
  terminalState?: 'cancelled' | null;
}): WorkbenchStatusSummary {
  const totalCount = status?.phases.length ?? 5;
  const completedCount = status?.phases.filter((phase) => phase.status === 'completed').length ?? 0;
  const currentPhase = status?.current_phase;
  const currentPhaseLabel = currentPhase ? PHASE_LABELS[currentPhase] : '분석 대기';
  const hasFigures = figures.length > 0;
  const hasRecipe = Boolean(recipe);
  const hasVisualizations = Boolean(visualizations?.items.length);

  if (terminalState === 'cancelled') {
    return {
      runStateLabel: '취소됨',
      trustStateLabel: completedCount > 0 ? '부분 결과 유지' : '분석 대기',
      nextActionLabel: completedCount > 0 ? '완료된 결과를 검토하거나 다시 분석하세요.' : '준비가 되면 분석을 다시 시작하세요.',
      currentPhaseLabel,
      completedCount,
      totalCount,
    };
  }

  if (!status || status.overall_status === 'pending') {
    return {
      runStateLabel: '분석 전',
      trustStateLabel: '분석 대기',
      nextActionLabel: '분석을 시작하면 요약, Figure, 레시피 흐름이 순서대로 준비됩니다.',
      currentPhaseLabel,
      completedCount,
      totalCount,
    };
  }

  if (status.overall_status === 'running' || status.overall_status === 'analyzing') {
    if (hasRecipe) {
      return {
        runStateLabel: `${currentPhaseLabel} 진행 중`,
        trustStateLabel: '레시피 초안 준비됨',
        nextActionLabel: '재현 파라미터를 먼저 확인하고 필요한 질문을 정리하세요.',
        currentPhaseLabel,
        completedCount,
        totalCount,
      };
    }
    if (hasFigures) {
      return {
        runStateLabel: `${currentPhaseLabel} 진행 중`,
        trustStateLabel: 'Figure 검토 가능',
        nextActionLabel: '주요 Figure와 캡션을 먼저 검토하세요.',
        currentPhaseLabel,
        completedCount,
        totalCount,
      };
    }
    if (completedCount > 0) {
      return {
        runStateLabel: `${currentPhaseLabel} 진행 중`,
        trustStateLabel: '초기 판독 가능',
        nextActionLabel: '핵심 주장과 인용 맥락을 먼저 확인하세요.',
        currentPhaseLabel,
        completedCount,
        totalCount,
      };
    }

    return {
      runStateLabel: `${currentPhaseLabel} 진행 중`,
      trustStateLabel: '결과 준비 중',
      nextActionLabel: '스크리닝이 끝나면 핵심 주장과 질문 도우미가 열립니다.',
      currentPhaseLabel,
      completedCount,
      totalCount,
    };
  }

  if (status.overall_status === 'error') {
    return {
      runStateLabel: completedCount > 0 ? '부분 완료' : '분석 실패',
      trustStateLabel: hasRecipe ? '레시피 초안 유지' : hasFigures ? 'Figure 검토 가능' : '재시도 필요',
      nextActionLabel: completedCount > 0 ? '남아 있는 결과를 검토한 뒤 재분석하세요.' : '설정을 확인한 뒤 다시 분석을 시작하세요.',
      currentPhaseLabel,
      completedCount,
      totalCount,
    };
  }

  return {
    runStateLabel: '분석 완료',
    trustStateLabel: hasVisualizations ? '심층 분석 완료' : hasRecipe ? '레시피 검토 가능' : '결과 준비됨',
    nextActionLabel: hasVisualizations
      ? '핵심 주장, Figure, 레시피를 교차 검토하세요.'
      : '준비된 결과를 순서대로 검토하세요.',
    currentPhaseLabel,
    completedCount,
    totalCount,
  };
}
