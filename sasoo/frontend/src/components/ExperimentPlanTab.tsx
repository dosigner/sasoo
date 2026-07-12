import { useState, useCallback } from 'react';
import {
  FlaskConical,
  Loader2,
  AlertCircle,
  CheckCircle2,
  AlertTriangle,
  Clock,
  MessageSquare,
} from 'lucide-react';
import {
  getExperimentPlan,
  generateExperimentPlan,
  type ExperimentPlan,
  ApiError,
} from '@/lib/api';

// ---------------------------------------------------------------------------
// Types (matching backend JSON schema)
// ---------------------------------------------------------------------------

interface Equipment {
  name: string;
  specification?: string;
  essential?: boolean;
}

interface Material {
  name: string;
  purity?: string;
  supplier?: string;
  quantity?: string;
  essential?: boolean;
}

interface ProcedureStep {
  step: number;
  title: string;
  description: string;
  duration?: string;
  critical_params?: string[];
}

interface Warning {
  type: string;
  severity: string;
  message: string;
}

interface PlanContent {
  title?: string;
  objective?: string;
  equipment_checklist?: Equipment[];
  materials_checklist?: Material[];
  procedure_steps?: ProcedureStep[];
  warnings?: Warning[];
  estimated_total_time?: string;
  estimated_difficulty?: string;
  mentor_comments?: string[];
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ExperimentPlanTabProps {
  paperId: string;
  recipeAvailable: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const severityEmoji: Record<string, string> = {
  high: '🔴',
  medium: '🟡',
  low: '🟢',
};

const difficultyLabel: Record<string, string> = {
  easy: '쉬움',
  moderate: '보통',
  hard: '어려움',
};

const warningTypeLabel: Record<string, string> = {
  missing_param: '누락 파라미터',
  safety: '안전 주의',
  calibration: '보정 필요',
  environment: '환경 조건',
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ExperimentPlanTab({ paperId, recipeAvailable }: ExperimentPlanTabProps) {
  const [plan, setPlan] = useState<ExperimentPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  // Try to load existing plan
  const loadPlan = useCallback(async () => {
    if (!paperId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getExperimentPlan(paperId);
      setPlan(result);
      setLoaded(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        // No plan yet, that's fine
        setLoaded(true);
      } else {
        setError('실험 계획서를 불러오지 못했어요.');
      }
    } finally {
      setLoading(false);
    }
  }, [paperId]);

  // Generate new plan
  const handleGenerate = useCallback(async () => {
    if (!paperId) return;
    setGenerating(true);
    setError(null);
    try {
      const result = await generateExperimentPlan(paperId);
      setPlan(result);
      setLoaded(true);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message || '실험 계획서를 만들지 못했어요.');
      } else {
        setError('실험 계획서를 만들지 못했어요.');
      }
    } finally {
      setGenerating(false);
    }
  }, [paperId]);

  // Auto-load on first render
  if (!loaded && !loading) {
    loadPlan();
  }

  // Recipe not available
  if (!recipeAvailable) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center px-6">
        <FlaskConical className="w-10 h-10 text-fg-muted mb-3" />
        <h3 className="text-sm font-semibold text-fg-secondary mb-1">
          분석을 끝내면 실험 계획서를 만들 수 있어요
        </h3>
        <p className="text-xs text-fg-muted">
          Phase 3 (Recipe Extraction)이 끝나면 사용할 수 있어요.
        </p>
      </div>
    );
  }

  // Loading state
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-5 h-5 text-accent animate-spin" />
        <span className="ml-2 text-sm text-fg-muted">불러오고 있어요...</span>
      </div>
    );
  }

  // No plan yet — show generate button
  if (!plan) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center px-6">
        <FlaskConical className="w-10 h-10 text-accent mb-3" />
        <h3 className="text-sm font-semibold text-fg mb-1">
          실험 재현 가이드 생성
        </h3>
        <p className="text-xs text-fg-muted mb-4 max-w-sm">
          Recipe Card를 기반으로 실험 장비, 재료, 절차, 주의사항을 포함한 재현 가이드를 만들어요.
        </p>
        {error && (
          <div className="flex items-center gap-1.5 text-xs text-danger mb-3">
            <AlertCircle className="w-3.5 h-3.5" />
            {error}
          </div>
        )}
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="btn-primary text-xs py-2 px-5"
        >
          {generating ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
              만들고 있어요...
            </>
          ) : (
            <>
              <FlaskConical className="w-3.5 h-3.5 mr-1.5" />
              실험 계획서 생성
            </>
          )}
        </button>
      </div>
    );
  }

  // Render plan
  const content = plan.content as PlanContent;

  return (
    <div className="space-y-4 py-2">
      {/* Header */}
      {content.title && (
        <div>
          <h3 className="text-base font-semibold text-fg">
            {content.title}
          </h3>
          {content.objective && (
            <p className="text-xs text-fg-muted mt-1">{content.objective}</p>
          )}
        </div>
      )}

      {/* Meta badges */}
      <div className="flex flex-wrap gap-2">
        {content.estimated_total_time && (
          <span className="badge text-2xs bg-accent/10 text-accent">
            <Clock className="w-3 h-3 mr-1" />
            {content.estimated_total_time}
          </span>
        )}
        {content.estimated_difficulty && (
          <span className={`badge text-2xs ${
            content.estimated_difficulty === 'hard'
              ? 'bg-danger/10 text-danger'
              : content.estimated_difficulty === 'moderate'
                ? 'bg-warning/10 text-warning'
                : 'bg-success/10 text-success'
          }`}>
            난이도: {difficultyLabel[content.estimated_difficulty] || content.estimated_difficulty}
          </span>
        )}
        {plan.cost_usd > 0 && (
          <span className="badge text-2xs bg-surface text-fg-muted">
            ${plan.cost_usd.toFixed(4)}
          </span>
        )}
      </div>

      {/* Warnings (shown prominently at top) */}
      {content.warnings && content.warnings.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-semibold text-warning flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5" />
            주의사항 ({content.warnings.length})
          </h4>
          {content.warnings.map((w, i) => (
            <div
              key={i}
              className={`flex items-start gap-2 px-3 py-2 rounded-lg text-xs ${
                w.severity === 'high'
                  ? 'bg-danger/10 border border-danger/20 text-danger'
                  : w.severity === 'medium'
                    ? 'bg-warning/10 border border-warning/20 text-warning'
                    : 'bg-surface/50 border border-border text-fg-secondary'
              }`}
            >
              <span className="shrink-0 mt-0.5">{severityEmoji[w.severity] || '🟡'}</span>
              <div>
                <span className="font-medium">{warningTypeLabel[w.type] || w.type}: </span>
                {w.message}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Equipment checklist */}
      {content.equipment_checklist && content.equipment_checklist.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-fg mb-2">
            장비 체크리스트
          </h4>
          <div className="space-y-1">
            {content.equipment_checklist.map((eq, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <CheckCircle2 className={`w-3.5 h-3.5 shrink-0 ${eq.essential ? 'text-accent' : 'text-fg-muted'}`} />
                <span className="text-fg">{eq.name}</span>
                {eq.specification && (
                  <span className="text-fg-muted">— {eq.specification}</span>
                )}
                {eq.essential && (
                  <span className="badge text-2xs bg-accent/10 text-accent">필수</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Materials checklist */}
      {content.materials_checklist && content.materials_checklist.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-fg mb-2">
            재료/시약 체크리스트
          </h4>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-fg-muted border-b border-border">
                  <th className="text-left py-1.5 pr-3">재료</th>
                  <th className="text-left py-1.5 pr-3">순도</th>
                  <th className="text-left py-1.5 pr-3">필요량</th>
                  <th className="text-left py-1.5">공급처</th>
                </tr>
              </thead>
              <tbody>
                {content.materials_checklist.map((m, i) => (
                  <tr key={i} className="border-b border-border/50">
                    <td className="py-1.5 pr-3 text-fg">
                      {m.name}
                      {m.essential && <span className="ml-1 text-accent">*</span>}
                    </td>
                    <td className="py-1.5 pr-3 text-fg-muted">{m.purity || '-'}</td>
                    <td className="py-1.5 pr-3 text-fg-muted">{m.quantity || '-'}</td>
                    <td className="py-1.5 text-fg-muted">{m.supplier || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Procedure steps */}
      {content.procedure_steps && content.procedure_steps.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-fg mb-2">
            실험 절차
          </h4>
          <div className="space-y-3">
            {content.procedure_steps.map((step) => (
              <div key={step.step} className="flex gap-3">
                <div className="shrink-0 w-6 h-6 rounded-full bg-accent/20 text-accent flex items-center justify-center text-xs font-semibold">
                  {step.step}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-fg">{step.title}</span>
                    {step.duration && (
                      <span className="badge text-2xs bg-surface text-fg-muted">
                        <Clock className="w-2.5 h-2.5 mr-0.5" />
                        {step.duration}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-fg-muted mt-0.5 leading-relaxed">
                    {step.description}
                  </p>
                  {step.critical_params && step.critical_params.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {step.critical_params.map((p, j) => (
                        <span key={j} className="badge text-2xs bg-warning/10 text-warning">
                          {p}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Mentor comments */}
      {content.mentor_comments && content.mentor_comments.length > 0 && (
        <div className="bg-surface/50 border border-border rounded-xl p-3">
          <h4 className="text-xs font-semibold text-accent mb-2 flex items-center gap-1.5">
            <MessageSquare className="w-3.5 h-3.5" />
            사수의 한마디
          </h4>
          <div className="space-y-1.5">
            {content.mentor_comments.map((comment, i) => (
              <p key={i} className="text-xs text-fg-secondary leading-relaxed">
                &ldquo;{comment}&rdquo;
              </p>
            ))}
          </div>
        </div>
      )}

      {/* Regenerate button */}
      <div className="pt-2 border-t border-border/50">
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="btn-ghost text-xs py-1.5 px-3 text-fg-muted hover:text-accent"
        >
          {generating ? (
            <>
              <Loader2 className="w-3 h-3 animate-spin mr-1" />
              다시 만들고 있어요...
            </>
          ) : (
            '다시 생성'
          )}
        </button>
      </div>
    </div>
  );
}
