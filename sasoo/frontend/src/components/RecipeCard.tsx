import { useState, useCallback } from 'react';
import type { EvidenceAnchor, Recipe } from '@/lib/api';
import { S } from '@/lib/strings';
import { AppIcon } from '@/components/icons';
import CascadeIn from '@/components/amicro/CascadeIn';
import { Badge, Tooltip } from '@/components/ui';
import {
  attachEvidence,
  evidenceBadge,
  evidenceSummaryTone,
  evidenceTarget,
  evidenceTooltip,
  parseRecipeParameters,
  resolveDisplayStatus,
  summarizeAnchoredEvidence,
} from '@/lib/evidence';
import { generateCsvFromRecipe } from '@/lib/recipeCsv';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RecipeCardProps {
  recipe: Recipe | null;
  loading?: boolean;
  onJumpToEvidence?: (anchor: EvidenceAnchor) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function downloadCsv(content: string, filename: string) {
  const bom = '\uFEFF'; // UTF-8 BOM for Excel compatibility
  const blob = new Blob([bom + content], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function RecipeSkeleton() {
  return (
    <div className="card animate-pulse">
      <div className="flex items-center gap-2 mb-4">
        <div className="h-4 w-4 bg-border rounded" />
        <div className="h-4 bg-border rounded w-40" />
      </div>
      <div className="space-y-2">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="flex gap-4">
            <div className="h-3 bg-border rounded w-24" />
            <div className="h-3 bg-border rounded w-16" />
            <div className="h-3 bg-border rounded w-20" />
            <div className="h-3 bg-border rounded w-16" />
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function RecipeCard({
  recipe,
  loading = false,
  onJumpToEvidence,
}: RecipeCardProps) {
  const [exported, setExported] = useState(false);

  const exportCsv = useCallback(() => {
    if (!recipe) return;
    const csv = generateCsvFromRecipe(recipe);
    const title = (recipe.recipe as Record<string, unknown>).title || 'recipe';
    const filename = `${String(title).replace(/[^a-zA-Z0-9]/g, '_').substring(0, 50)}.csv`;
    downloadCsv(csv, filename);
    setExported(true);
    setTimeout(() => setExported(false), 2000);
  }, [recipe]);

  if (loading) {
    return <RecipeSkeleton />;
  }

  if (!recipe) {
    return (
      <div>
        <h3 className="text-sm font-semibold text-fg mb-3 flex items-center gap-2">
          <AppIcon name="recipe" className="w-4 h-4 text-accent" />
          {S.recipe.title}
        </h3>
        <div className="card flex flex-col items-center justify-center py-8 text-center">
          <AppIcon name="recipe" className="w-8 h-8 text-fg-muted mb-2" />
          <p className="text-sm text-fg-muted">
            {S.recipe.noRecipe}
          </p>
        </div>
      </div>
    );
  }

  const data = recipe.recipe as Record<string, unknown>;
  const title = (data.title as string) || 'Recipe';
  const objective = (data.objective as string) || '';
  const materials = (data.materials as string[]) || [];
  const steps = (data.steps as string[]) || [];
  const criticalNotes = (data.critical_notes as string[]) || [];
  const missingInfo = (data.missing_info as string[]) || [];
  const confidence = data.confidence as number | undefined;
  const reproducibilityScore = data.reproducibility_score as number | undefined;

  // 파라미터 파싱은 lib/evidence.ts로 옮겼다 — 백엔드 검증기와 규칙을 맞추고 단위 테스트를 붙이기 위해.
  const parameters = parseRecipeParameters(data.parameters);
  const anchored = attachEvidence(parameters, recipe.evidence ?? null);
  const evidenceSummary = recipe.evidence?.summary ?? null;
  // 배지는 백엔드 summary 원본이 아니라 화면에 실제 붙은 anchored 결과로 센다 —
  // fail-closed로 숨겨진 앵커가 있으면 백엔드 summary와 표 숫자가 어긋난다.
  const evidenceCounts = summarizeAnchoredEvidence(anchored);

  return (
    <div>
      {/* Header — signature 3px accent bar on the left */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="flex items-center gap-2 border-l-[3px] border-accent pl-2.5 text-sm font-semibold text-fg">
          <AppIcon name="recipe" className="w-4 h-4 text-accent" />
          {title}
        </h3>
        <button
          onClick={exportCsv}
          className="btn-ghost text-2xs px-2 py-1"
          title={S.recipe.exportCsv}
        >
          {exported ? (
            <>
              <AppIcon name="success" className="w-3 h-3 text-success" />
              {S.recipe.exported}
            </>
          ) : (
            <>
              <AppIcon name="download" className="w-3 h-3" />
              {S.recipe.exportCsv}
            </>
          )}
        </button>
      </div>

      {/* Scores */}
      {(confidence !== undefined || reproducibilityScore !== undefined) && (
        <CascadeIn index={0}>
        <div className="card p-3 mb-3 flex items-center gap-4">
          {confidence !== undefined && (
            <div className="text-xs text-fg-muted">
              {S.recipe.confidence} <span className="text-fg font-mono">{(confidence * 100).toFixed(0)}%</span>
            </div>
          )}
          {reproducibilityScore !== undefined && (
            <div className="text-xs text-fg-muted">
              {S.recipe.reproducibility} <span className="text-fg font-mono">{(reproducibilityScore * 100).toFixed(0)}%</span>
            </div>
          )}
        </div>
        </CascadeIn>
      )}

      {/* Objective */}
      {objective && (
        <CascadeIn index={1}>
        <div className="card p-3 mb-3">
          <p className="text-xs text-fg-secondary leading-relaxed">
            <span className="font-semibold text-fg">{S.recipe.objective} </span>
            {objective}
          </p>
        </div>
        </CascadeIn>
      )}

      {/* Materials */}
      {materials.length > 0 && (
        <CascadeIn index={2}>
        <div className="card p-3 mb-3">
          <h4 className="mb-2 text-2xs font-medium uppercase tracking-wide text-fg-muted">{S.recipe.materials}</h4>
          <ul className="space-y-1">
            {materials.map((m, i) => (
              <li key={i} className="text-xs text-fg-muted flex items-start gap-1.5">
                <span className="text-accent mt-0.5">-</span>
                {m}
              </li>
            ))}
          </ul>
        </div>
        </CascadeIn>
      )}

      {/* Parameters Table */}
      {parameters.length > 0 && (
        <CascadeIn index={3}>
        <div className="card p-0 overflow-hidden mb-3">
          <div className="px-3 py-2 border-b border-border bg-surface/70 flex items-center justify-between gap-2">
            <h4 className="text-2xs font-medium uppercase tracking-wide text-fg-muted">
              {S.recipe.parameters} ({parameters.length})
            </h4>
            {evidenceSummary && (
              <Badge variant={evidenceSummaryTone(evidenceCounts.verified, evidenceCounts.total)}>
                {S.recipe.evidence.summaryBadge(evidenceCounts.verified, evidenceCounts.total)}
              </Badge>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border bg-surface/30">
                  <th className="text-left font-semibold text-fg-muted px-3 py-2 w-8">#</th>
                  <th className="text-left font-semibold text-fg-secondary px-3 py-2">Parameter</th>
                  <th className="text-left font-semibold text-fg-secondary px-3 py-2">Value</th>
                  <th className="text-left font-semibold text-fg-secondary px-3 py-2">Unit</th>
                  <th className="text-left font-semibold text-fg-secondary px-3 py-2">Notes</th>
                  <th className="text-left font-semibold text-fg-secondary px-3 py-2">{S.recipe.evidence.column}</th>
                </tr>
              </thead>
              <tbody>
                {anchored.map(({ row, anchor }) => {
                  const status = resolveDisplayStatus(anchor);
                  const badge = evidenceBadge(status);
                  const target = evidenceTarget(anchor);
                  return (
                    <tr key={row.index} className="border-b border-border/50 last:border-b-0 hover:bg-surface-hover/30 transition-colors">
                      <td className="px-3 py-2 font-mono tabular-nums text-fg-muted">{row.index + 1}</td>
                      <td className="px-3 py-2 text-sm text-fg-secondary">{row.name || '-'}</td>
                      <td className="px-3 py-2 font-mono text-sm tabular-nums text-accent">{row.value || '-'}</td>
                      <td className="px-3 py-2 font-mono text-sm tabular-nums text-fg-muted">{row.unit || '-'}</td>
                      <td className="px-3 py-2 text-xs text-fg-muted">{row.notes || '-'}</td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Tooltip
                            content={<span className="block max-w-xs whitespace-pre-wrap">{evidenceTooltip(anchor)}</span>}
                          >
                            <span aria-label={badge.label}>
                              <Badge variant={badge.tone}>
                                <AppIcon name={badge.icon} className="w-3 h-3 mr-1" />
                                {badge.label}
                              </Badge>
                            </span>
                          </Tooltip>
                          {anchor && target && onJumpToEvidence && (
                            <button
                              type="button"
                              onClick={() => onJumpToEvidence(anchor)}
                              className="btn-ghost text-2xs px-1.5 py-0.5"
                              title={S.recipe.evidence.jump}
                            >
                              {target.confirmed
                                ? S.recipe.evidence.confirmedPage(target.page)
                                : S.recipe.evidence.candidatePage(target.page)}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        </CascadeIn>
      )}

      {/* No parameters warning */}
      {parameters.length === 0 && (
        <CascadeIn index={3}>
        <div className="card p-3 mb-3 border-warning/20 bg-warning/5">
          <p className="text-xs text-warning/80">
            {S.recipe.noParams}
          </p>
        </div>
        </CascadeIn>
      )}

      {/* Steps */}
      {steps.length > 0 && (
        <CascadeIn index={4}>
        <div className="card p-3 mb-3">
          <h4 className="mb-2 text-2xs font-medium uppercase tracking-wide text-fg-muted">{S.recipe.steps}</h4>
          <ol className="space-y-1.5">
            {steps.map((step, i) => (
              <li key={i} className="text-xs text-fg-muted leading-relaxed">
                <span className="text-accent font-medium mr-1">{i + 1}.</span>
                {step}
              </li>
            ))}
          </ol>
        </div>
        </CascadeIn>
      )}

      {/* Critical Notes */}
      {criticalNotes.length > 0 && (
        <CascadeIn index={5}>
        <div className="mb-3">
          <h4 className="mb-2 text-2xs font-medium uppercase tracking-wide text-fg-muted">{S.recipe.criticalNotes}</h4>
          <div className="space-y-1.5">
            {criticalNotes.map((note, index) => (
              <div
                key={index}
                className="flex items-start gap-2 bg-warning/5 border border-warning/20 rounded-lg px-3 py-2"
              >
                <AppIcon name="warning" className="w-3 h-3 text-warning mt-0.5 shrink-0" />
                <p className="text-xs text-warning/80 leading-relaxed">
                  {note}
                </p>
              </div>
            ))}
          </div>
        </div>
        </CascadeIn>
      )}

      {/* Missing Info */}
      {missingInfo.length > 0 && (
        <CascadeIn index={6}>
        <div className="card p-3 mb-3 border-danger/20 bg-danger/5">
          <h4 className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-danger">{S.recipe.missingInfo}</h4>
          <ul className="space-y-1">
            {missingInfo.map((info, index) => (
              <li key={index} className="text-xs text-danger/70 flex items-start gap-1.5">
                <span className="text-danger mt-0.5">?</span>
                {info}
              </li>
            ))}
          </ul>
        </div>
        </CascadeIn>
      )}
    </div>
  );
}
