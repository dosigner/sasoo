import type {
  ArtifactStatus,
  AnalysisPhase,
  AnalysisResults,
  AnalysisStatus,
  Figure,
  Recipe,
  Table,
  VisualizationPlan,
} from '@/lib/api';

type PhaseTone = 'primary' | 'muted' | 'practical';

export interface MetaItem {
  label: string;
  value: string;
  accent?: boolean;
}

export interface PhaseSummary {
  summaryLine: string | null;
  collapsedMeta: string[];
  expandedMeta: string[];
  metaItems: MetaItem[];
  tone: PhaseTone;
}

// screening 메타 그리드 값 한국어 매핑. AnalysisResults.screening의 원본 필드(estimated_complexity,
// is_experimental)를 그대로 쓰지 않고 여기서 한 번 한국어 라벨로 옮긴다.
const COMPLEXITY_LABELS: Record<string, string> = {
  high: '높음',
  medium: '보통',
  low: '낮음',
};

const METHODOLOGY_LABELS = {
  experimental: '실험 논문',
  nonExperimental: '비실험 논문',
} as const;

// M1: screening.domain 표시용 한국어 라벨. 백엔드 enum(api/analysis_routes.py의
// SCREENING 스키마 "optics"|"bio"|"ai_ml"|"ee"|"general")에 맞춘 전용 맵이다.
// S.areas(연구자 프로필 관심 분야, optics_photonics 등)는 키 체계가 달라 재사용할 수 없다.
// 맵에 없는 값(모델이 스키마 밖 값을 내보낸 경우)은 원본 문자열을 그대로 표시한다.
export const DOMAIN_LABELS: Record<string, string> = {
  optics: '광학',
  bio: '바이오',
  ai_ml: 'AI·머신러닝',
  ee: '전기·전자',
  general: '일반',
};

export interface WorkbenchStatusSummary {
  runStateLabel: string;
  trustStateLabel: string;
  nextActionLabel: string;
  currentPhaseLabel: string;
  completedCount: number;
  totalCount: number;
  progressRatio: number;
}

// 상태부 진행 레일에 쓰는 단계명. ProgressTracker의 단계 리스트 라벨도 이 명칭을
// 재사용해 상태부 진행 레일과 표기를 통일한다.
export const STAGE_NAMES: string[] = ['스크리닝', '인용 분석', '시각 자료', '레시피', '심층 분석'];

// I8: currentPhaseLabel(진행 중 문구용)도 STAGE_NAMES와 동일한 단계명을 쓴다.
// 예전엔 visual만 'Figure 검토'로 따로 불러 상태부·진행 레일과 표기가 어긋났다.
const PHASE_LABELS: Record<AnalysisPhase, string> = {
  screening: STAGE_NAMES[0],
  citation: STAGE_NAMES[1],
  visual: STAGE_NAMES[2],
  recipe: STAGE_NAMES[3],
  deep_dive: STAGE_NAMES[4],
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
  tables: Table[],
  visualizations: VisualizationPlan | null,
): PhaseSummary {
  if (!results) {
    return {
      summaryLine: null,
      collapsedMeta: [],
      expandedMeta: [],
      metaItems: [],
      tone: phase === 'screening' ? 'primary' : phase === 'visual' || phase === 'recipe' ? 'practical' : 'muted',
    };
  }

  const screening = results.screening ?? {};
  const citation = results.citation ?? {};
  const visual = results.visual ?? {};
  const deepDive = results.deep_dive ?? {};
  const recipeResult = recipe?.recipe ?? results.recipe ?? {};

  if (phase === 'screening') {
    const domainLabel =
      typeof screening.domain === 'string' && screening.domain.trim()
        ? DOMAIN_LABELS[screening.domain.trim()] ?? screening.domain.trim()
        : null;
    const domain = domainLabel ?? '미분류';
    const relevance = percent(screening.relevance_score);
    const agent = typeof screening.agent_recommended === 'string' ? screening.agent_recommended : null;
    const rawDomain = domainLabel;
    const methodologyLabel =
      screening.is_experimental === true
        ? METHODOLOGY_LABELS.experimental
        : screening.is_experimental === false
          ? METHODOLOGY_LABELS.nonExperimental
          : null;
    const complexityLabel =
      typeof screening.estimated_complexity === 'string' ? COMPLEXITY_LABELS[screening.estimated_complexity] ?? null : null;
    const metaItems: MetaItem[] = [
      rawDomain ? { label: '분야', value: rawDomain } : null,
      relevance ? { label: '관련도', value: relevance, accent: true } : null,
      methodologyLabel ? { label: '방법론', value: methodologyLabel } : null,
      complexityLabel ? { label: '복잡도', value: complexityLabel } : null,
    ].filter((item): item is MetaItem => item !== null);
    return {
      summaryLine: shortText(screening.summary, '논문의 핵심 맥락을 정리해요.'),
      collapsedMeta: [domain, relevance ? `관련도 ${relevance}` : '', agent ? `추천 ${agent}` : ''].filter(Boolean),
      expandedMeta: [],
      metaItems,
      tone: 'primary',
    };
  }

  if (phase === 'citation') {
    const totalRefs = typeof citation.total_references === 'number' ? citation.total_references : 0;
    const style = typeof citation.citation_style === 'string' ? citation.citation_style : '';
    const selfCount = typeof citation.self_citation_count === 'number' ? citation.self_citation_count : null;
    return {
      summaryLine: shortText(citation.summary, totalRefs > 0 ? '참고문헌 구조를 빠르게 훑어볼 수 있어요.' : '참고문헌 정보를 찾지 못했어요.'),
      collapsedMeta: [
        totalRefs > 0 ? `${totalRefs}개 참고문헌` : '참고문헌 없음',
        style,
        selfCount != null ? `자기 인용 ${selfCount}` : '',
      ].filter(Boolean),
      expandedMeta: [
        countList(citation.top_cited) > 0 ? `주요 인용 ${countList(citation.top_cited)}건` : '',
        Object.keys((citation.citation_distribution as Record<string, number> | undefined) ?? {}).length > 0 ? '섹션 분포 포함' : '',
      ].filter(Boolean),
      metaItems: [],
      tone: 'muted',
    };
  }

  if (phase === 'visual') {
    const figureCount =
      typeof visual.figure_count === 'number' && visual.figure_count > 0
        ? visual.figure_count
        : figures.length;
    const tableCount =
      typeof visual.tables_found === 'number' && visual.tables_found > 0
        ? visual.tables_found
        : tables.length;
    return {
      summaryLine: shortText(
        visual.quality_summary,
        figureCount > 0 || tableCount > 0
          ? '추출한 figure와 table을 함께 정리했어요.'
          : '추출한 시각 자료가 없어요.'
      ),
      collapsedMeta: [
        figureCount > 0 ? `Figure ${figureCount}개` : 'Figure 없음',
        tableCount > 0 ? `표 ${tableCount}개` : '표 없음',
        typeof visual.equations_found === 'number' ? `수식 ${visual.equations_found}` : '',
      ].filter(Boolean),
      expandedMeta: [
        countList(visual.diagram_types) > 0 ? `유형 ${countList(visual.diagram_types)}개` : '',
        countList(visual.key_findings_from_visuals) > 0 ? `핵심 발견 ${countList(visual.key_findings_from_visuals)}개` : '',
      ].filter(Boolean),
      metaItems: [],
      tone: 'practical',
    };
  }

  if (phase === 'recipe') {
    const params = Array.isArray(recipeResult.parameters) ? recipeResult.parameters.length : 0;
    const confidence = percent(recipeResult.confidence);
    const title = typeof recipeResult.title === 'string' ? recipeResult.title : '';
    return {
      summaryLine: title || (params > 0 ? '실험 재현을 위한 핵심 정보를 정리했어요.' : '레시피 정보를 더 확인해야 해요.'),
      collapsedMeta: [
        title ? '레시피 추출됨' : recipe ? '레시피 준비됨' : '레시피 없음',
        params > 0 ? `파라미터 ${params}개` : '파라미터 없음',
        confidence ? `신뢰도 ${confidence}` : '',
      ].filter(Boolean),
      expandedMeta: [
        countList(recipeResult.materials) > 0 ? `재료 ${countList(recipeResult.materials)}개` : '',
        countList(recipeResult.steps) > 0 ? `절차 ${countList(recipeResult.steps)}단계` : '',
      ].filter(Boolean),
      metaItems: [],
      tone: 'practical',
    };
  }

  const strengths = countList(deepDive.strengths);
  const weaknesses = countList(deepDive.weaknesses);
  const vizCount = visualizations?.items.length ?? 0;

  return {
    summaryLine: shortText(deepDive.detailed_analysis, vizCount > 0 ? '심층 분석과 시각화를 준비했어요.' : '심층 분석 결과를 정리했어요.'),
    collapsedMeta: [
      vizCount > 0 ? `시각화 ${vizCount}개` : '시각화 대기',
      strengths > 0 ? `강점 ${strengths}` : '',
      weaknesses > 0 ? `약점 ${weaknesses}` : '',
    ].filter(Boolean),
    expandedMeta: [
      countList(deepDive.follow_up_questions) > 0 ? `후속 질문 ${countList(deepDive.follow_up_questions)}개` : '',
      countList(deepDive.practical_applications) > 0 ? `응용 ${countList(deepDive.practical_applications)}개` : '',
    ].filter(Boolean),
    metaItems: [],
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

export function buildWorkbenchStatusSummary({
  status,
  artifactStatus,
  figures,
  tables,
  recipe,
  visualizations,
  terminalState,
}: {
  status: AnalysisStatus | null;
  artifactStatus?: ArtifactStatus | null;
  figures: Figure[];
  tables: Table[];
  recipe: Recipe | null;
  visualizations: VisualizationPlan | null;
  terminalState?: 'cancelled' | null;
}): WorkbenchStatusSummary {
  const totalCount = status?.phases.length ?? 5;
  const completedCount = status?.phases.filter((phase) => phase.status === 'completed').length ?? 0;
  const progressRatio = totalCount > 0 ? completedCount / totalCount : 0;
  const currentPhase = status?.current_phase;
  const currentPhaseLabel = currentPhase ? PHASE_LABELS[currentPhase] : '분석 대기';
  const hasFigures = figures.length > 0;
  const hasTables = tables.length > 0;
  const hasRecipe = Boolean(recipe);
  const hasVisualizations = Boolean(visualizations?.items.length);
  const textReady = artifactStatus?.text_ready;
  const visualReady = artifactStatus?.visual_ready;
  const visualState = artifactStatus?.visual_state;

  const fallbackTrustState = hasVisualizations
    ? '심층 분석 완료'
    : hasRecipe
      ? '레시피 검토 가능'
      : '결과 준비됨';
  const trustStateLabel =
    textReady === false
      ? '본문 준비 중'
      : visualState === 'error'
        ? '시각 자료 동기화 오류'
        : visualState === 'running'
          ? '시각 자료 동기화 중'
          : visualState === 'partial' || (textReady === true && visualReady === false)
            ? '시각 자료 일부만 준비됨'
            : fallbackTrustState;

  if (terminalState === 'cancelled') {
    return {
      runStateLabel: '취소됨',
      trustStateLabel,
      nextActionLabel: completedCount > 0 ? '끝낸 결과를 검토하거나 다시 분석하세요.' : '준비가 되면 분석을 다시 시작하세요.',
      currentPhaseLabel,
      completedCount,
      totalCount,
      progressRatio,
    };
  }

  if (!status || status.overall_status === 'pending') {
    const nextActionLabel =
      textReady === false
        ? '본문 정리가 끝나면 요약, Figure/Table, 레시피를 순서대로 준비해요.'
        : visualState === 'running'
          ? '시각 자료를 동기화하고 있어요. 잠시 후 Figure/Table 탭을 확인하세요.'
          : visualState === 'error'
            ? '시각 artifact 동기화 상태를 확인한 뒤 다시 시도하세요.'
            : '분석을 시작하면 요약, Figure/Table, 레시피 흐름을 순서대로 준비해요.';
    return {
      runStateLabel: '분석 전',
      trustStateLabel,
      nextActionLabel,
      currentPhaseLabel,
      completedCount,
      totalCount,
      progressRatio,
    };
  }

  if (status.overall_status === 'running' || status.overall_status === 'analyzing') {
    if (textReady === false) {
      return {
        runStateLabel: `${currentPhaseLabel} 진행 중`,
        trustStateLabel,
        nextActionLabel: '본문 정리가 끝나면 핵심 주장과 질문 도우미가 열려요.',
        currentPhaseLabel,
        completedCount,
        totalCount,
        progressRatio,
      };
    }
    if (visualState === 'error') {
      return {
        runStateLabel: `${currentPhaseLabel} 진행 중`,
        trustStateLabel,
        nextActionLabel: hasFigures || hasTables
          ? '사용 가능한 Figure/Table을 먼저 검토하고 시각 artifact 상태를 다시 확인하세요.'
          : '시각 artifact 동기화 상태를 확인한 뒤 다시 시도하세요.',
        currentPhaseLabel,
        completedCount,
        totalCount,
        progressRatio,
      };
    }
    if (visualState === 'running') {
      return {
        runStateLabel: `${currentPhaseLabel} 진행 중`,
        trustStateLabel,
        nextActionLabel: hasFigures || hasTables
          ? '동기화가 계속되는 동안 현재 Figure/Table 결과를 먼저 검토하세요.'
          : '시각 자료를 동기화하고 있어요. Figure/Table 탭을 순서대로 채워요.',
        currentPhaseLabel,
        completedCount,
        totalCount,
        progressRatio,
      };
    }
    if (visualState === 'partial' || (textReady === true && visualReady === false)) {
      return {
        runStateLabel: `${currentPhaseLabel} 진행 중`,
        trustStateLabel,
        nextActionLabel: hasFigures || hasTables
          ? '준비한 Figure/Table부터 검토하고 부족한 시각 자료는 다시 확인하세요.'
          : '일부 시각 자료만 준비했어요. 동기화가 끝나면 Figure/Table 탭을 다시 확인하세요.',
        currentPhaseLabel,
        completedCount,
        totalCount,
        progressRatio,
      };
    }
    if (hasRecipe) {
      return {
        runStateLabel: `${currentPhaseLabel} 진행 중`,
        trustStateLabel,
        nextActionLabel: '재현 파라미터를 먼저 확인하고 필요한 질문을 정리하세요.',
        currentPhaseLabel,
        completedCount,
        totalCount,
        progressRatio,
      };
    }
    if (hasFigures || hasTables) {
      return {
        runStateLabel: `${currentPhaseLabel} 진행 중`,
        trustStateLabel,
        nextActionLabel: hasTables && !hasFigures
          ? '검출한 Table과 구조 복구 상태를 먼저 검토하세요.'
          : '주요 Figure와 Table을 먼저 검토하세요.',
        currentPhaseLabel,
        completedCount,
        totalCount,
        progressRatio,
      };
    }
    if (completedCount > 0) {
      return {
        runStateLabel: `${currentPhaseLabel} 진행 중`,
        trustStateLabel,
        nextActionLabel: '핵심 주장과 인용 맥락을 먼저 확인하세요.',
        currentPhaseLabel,
        completedCount,
        totalCount,
        progressRatio,
      };
    }

    return {
      runStateLabel: `${currentPhaseLabel} 진행 중`,
      trustStateLabel,
      nextActionLabel: '스크리닝이 끝나면 핵심 주장과 질문 도우미가 열려요.',
      currentPhaseLabel,
      completedCount,
      totalCount,
      progressRatio,
    };
  }

  if (status.overall_status === 'error') {
    return {
      runStateLabel: completedCount > 0 ? '부분 완료' : '분석 실패',
      trustStateLabel,
      nextActionLabel: completedCount > 0 ? '남아 있는 결과를 검토한 뒤 재분석하세요.' : '설정을 확인한 뒤 다시 분석을 시작하세요.',
      currentPhaseLabel,
      completedCount,
      totalCount,
      progressRatio,
    };
  }

  return {
    runStateLabel: '분석 완료',
    trustStateLabel,
    nextActionLabel: hasVisualizations
      ? '핵심 주장, Figure, Table, 레시피를 교차 검토하세요.'
      : '준비한 결과를 순서대로 검토하세요.',
    currentPhaseLabel,
    completedCount,
    totalCount,
    progressRatio,
  };
}
