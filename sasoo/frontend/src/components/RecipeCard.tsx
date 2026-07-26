import { useState, useCallback } from 'react';
import type { Recipe } from '@/lib/api';
import { S } from '@/lib/strings';
import { AppIcon } from '@/components/icons';
import CascadeIn from '@/components/amicro/CascadeIn';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RecipeCardProps {
  recipe: Recipe | null;
  loading?: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateCsvFromRecipe(recipe: Recipe): string {
  const data = recipe.recipe as Record<string, unknown>;
  const rows: string[][] = [];

  // Header info
  rows.push(['Section', 'Key', 'Value']);
  rows.push(['Info', 'Title', String(data.title || '')]);
  rows.push(['Info', 'Objective', String(data.objective || '')]);
  rows.push(['Info', 'Confidence', data.confidence != null ? `${(Number(data.confidence) * 100).toFixed(0)}%` : '']);
  rows.push(['Info', 'Reproducibility', data.reproducibility_score != null ? `${(Number(data.reproducibility_score) * 100).toFixed(0)}%` : '']);

  // Materials
  const materials = (data.materials as string[]) || [];
  materials.forEach((m, i) => rows.push(['Material', `#${i + 1}`, m]));

  // Equipment
  const equipment = (data.equipment as string[]) || [];
  equipment.forEach((e, i) => rows.push(['Equipment', `#${i + 1}`, e]));

  // Parameters
  const params = (data.parameters as Record<string, string>[]) || [];
  params.forEach(p => {
    if (typeof p === 'object' && p.name) {
      rows.push(['Parameter', p.name, `${p.value || ''}${p.unit ? ' ' + p.unit : ''}${p.notes ? ' (' + p.notes + ')' : ''}`]);
    }
  });

  // Steps
  const steps = (data.steps as string[]) || [];
  steps.forEach((s, i) => rows.push(['Step', `#${i + 1}`, s]));

  // Critical notes
  const notes = (data.critical_notes as string[]) || [];
  notes.forEach((n, i) => rows.push(['Critical Note', `#${i + 1}`, n]));

  if (data.expected_results) rows.push(['Info', 'Expected Results', String(data.expected_results)]);
  if (data.safety_notes) rows.push(['Info', 'Safety Notes', String(data.safety_notes)]);

  // Escape CSV fields
  return rows.map(row =>
    row.map(cell => {
      const s = String(cell).replace(/"/g, '""');
      return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s}"` : s;
    }).join(',')
  ).join('\n');
}

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

  // Robustly parse parameters — handle both array of objects and other formats
  const rawParams = data.parameters;
  const parameters: { name: string; value: string; unit: string; notes: string }[] = [];
  if (Array.isArray(rawParams)) {
    rawParams.forEach((p: unknown) => {
      if (typeof p === 'object' && p !== null) {
        const obj = p as Record<string, unknown>;
        parameters.push({
          name: String(obj.name || obj.Name || obj.parameter || obj.key || ''),
          value: String(obj.value || obj.Value || obj.val || ''),
          unit: String(obj.unit || obj.Unit || obj.units || ''),
          notes: String(obj.notes || obj.Notes || obj.note || obj.context || ''),
        });
      } else if (typeof p === 'string') {
        // "Temperature: 500 C" format
        const match = p.match(/^(.+?):\s*(.+)$/);
        if (match) {
          parameters.push({ name: match[1].trim(), value: match[2].trim(), unit: '', notes: '' });
        } else {
          parameters.push({ name: p, value: '', unit: '', notes: '' });
        }
      }
    });
  }

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
          <div className="px-3 py-2 border-b border-border bg-surface/70">
            <h4 className="text-2xs font-medium uppercase tracking-wide text-fg-muted">
              {S.recipe.parameters} ({parameters.length})
            </h4>
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
                </tr>
              </thead>
              <tbody>
                {parameters.map((param, index) => (
                  <tr key={index} className="border-b border-border/50 last:border-b-0 hover:bg-surface-hover/30 transition-colors">
                    <td className="px-3 py-2 font-mono tabular-nums text-fg-muted">{index + 1}</td>
                    <td className="px-3 py-2 text-sm text-fg-secondary">{param.name || '-'}</td>
                    <td className="px-3 py-2 font-mono text-sm tabular-nums text-accent">{param.value || '-'}</td>
                    <td className="px-3 py-2 font-mono text-sm tabular-nums text-fg-muted">{param.unit || '-'}</td>
                    <td className="px-3 py-2 text-xs text-fg-muted">{param.notes || '-'}</td>
                  </tr>
                ))}
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
