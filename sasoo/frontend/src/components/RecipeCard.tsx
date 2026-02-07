import { useState, useCallback } from 'react';
import {
  FlaskConical,
  Download,
  Check,
  AlertTriangle,
} from 'lucide-react';
import type { Recipe } from '@/lib/api';

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
        <div className="h-4 w-4 bg-surface-700 rounded" />
        <div className="h-4 bg-surface-700 rounded w-40" />
      </div>
      <div className="space-y-2">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="flex gap-4">
            <div className="h-3 bg-surface-700 rounded w-24" />
            <div className="h-3 bg-surface-700 rounded w-16" />
            <div className="h-3 bg-surface-700 rounded w-20" />
            <div className="h-3 bg-surface-700 rounded w-16" />
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
        <h3 className="text-sm font-semibold text-surface-200 mb-3 flex items-center gap-2">
          <FlaskConical className="w-4 h-4 text-primary-400" />
          Reproducibility Recipe
        </h3>
        <div className="card flex flex-col items-center justify-center py-8 text-center">
          <FlaskConical className="w-8 h-8 text-surface-600 mb-2" />
          <p className="text-sm text-surface-400">
            Recipe not yet generated. Run analysis to extract parameters.
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
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-surface-200 flex items-center gap-2">
          <FlaskConical className="w-4 h-4 text-primary-400" />
          {title}
        </h3>
        <button
          onClick={exportCsv}
          className="btn-ghost text-2xs px-2 py-1"
          title="Export as CSV"
        >
          {exported ? (
            <>
              <Check className="w-3 h-3 text-emerald-400" />
              Exported
            </>
          ) : (
            <>
              <Download className="w-3 h-3" />
              CSV
            </>
          )}
        </button>
      </div>

      {/* Scores */}
      {(confidence !== undefined || reproducibilityScore !== undefined) && (
        <div className="card p-3 mb-3 flex items-center gap-4">
          {confidence !== undefined && (
            <div className="text-xs text-surface-400">
              Confidence: <span className="text-surface-200 font-mono">{(confidence * 100).toFixed(0)}%</span>
            </div>
          )}
          {reproducibilityScore !== undefined && (
            <div className="text-xs text-surface-400">
              Reproducibility: <span className="text-surface-200 font-mono">{(reproducibilityScore * 100).toFixed(0)}%</span>
            </div>
          )}
        </div>
      )}

      {/* Objective */}
      {objective && (
        <div className="card p-3 mb-3">
          <p className="text-xs text-surface-300 leading-relaxed">
            <span className="font-semibold text-surface-200">Objective: </span>
            {objective}
          </p>
        </div>
      )}

      {/* Materials */}
      {materials.length > 0 && (
        <div className="card p-3 mb-3">
          <h4 className="text-xs font-semibold text-surface-200 mb-2">Materials</h4>
          <ul className="space-y-1">
            {materials.map((m, i) => (
              <li key={i} className="text-2xs text-surface-400 flex items-start gap-1.5">
                <span className="text-primary-400 mt-0.5">-</span>
                {m}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Parameters Table */}
      {parameters.length > 0 && (
        <div className="card p-0 overflow-hidden mb-3">
          <div className="px-3 py-2 border-b border-surface-700 bg-surface-800/70">
            <h4 className="text-xs font-semibold text-surface-200">
              Parameters ({parameters.length})
            </h4>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-surface-700 bg-surface-800/30">
                  <th className="text-left font-semibold text-surface-400 px-3 py-2 w-8">#</th>
                  <th className="text-left font-semibold text-surface-300 px-3 py-2">Parameter</th>
                  <th className="text-left font-semibold text-surface-300 px-3 py-2">Value</th>
                  <th className="text-left font-semibold text-surface-300 px-3 py-2">Unit</th>
                  <th className="text-left font-semibold text-surface-300 px-3 py-2">Notes</th>
                </tr>
              </thead>
              <tbody>
                {parameters.map((param, index) => (
                  <tr key={index} className="border-b border-surface-700/50 last:border-b-0 hover:bg-surface-700/30 transition-colors">
                    <td className="px-3 py-2 text-surface-500 font-mono">{index + 1}</td>
                    <td className="px-3 py-2 font-medium text-surface-200">{param.name || '-'}</td>
                    <td className="px-3 py-2 text-primary-300 font-mono">{param.value || '-'}</td>
                    <td className="px-3 py-2 text-surface-400">{param.unit || '-'}</td>
                    <td className="px-3 py-2 text-surface-500 text-2xs">{param.notes || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* No parameters warning */}
      {parameters.length === 0 && (
        <div className="card p-3 mb-3 border-amber-500/20 bg-amber-500/5">
          <p className="text-xs text-amber-300/80">
            No parameters were extracted. This may indicate the paper lacks explicit experimental details
            or the Methods section was not fully captured.
          </p>
        </div>
      )}

      {/* Steps */}
      {steps.length > 0 && (
        <div className="card p-3 mb-3">
          <h4 className="text-xs font-semibold text-surface-200 mb-2">Steps</h4>
          <ol className="space-y-1.5">
            {steps.map((step, i) => (
              <li key={i} className="text-2xs text-surface-400 leading-relaxed">
                <span className="text-primary-400 font-medium mr-1">{i + 1}.</span>
                {step}
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* Critical Notes */}
      {criticalNotes.length > 0 && (
        <div className="mb-3">
          <h4 className="text-xs font-semibold text-surface-200 mb-2">Critical Notes</h4>
          <div className="space-y-1.5">
            {criticalNotes.map((note, index) => (
              <div
                key={index}
                className="flex items-start gap-2 bg-amber-500/5 border border-amber-500/20 rounded-lg px-3 py-2"
              >
                <AlertTriangle className="w-3 h-3 text-amber-400 mt-0.5 shrink-0" />
                <p className="text-2xs text-amber-300/80 leading-relaxed">
                  {note}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Missing Info */}
      {missingInfo.length > 0 && (
        <div className="card p-3 mb-3 border-red-500/20 bg-red-500/5">
          <h4 className="text-xs font-semibold text-red-300 mb-1.5">Missing Information</h4>
          <ul className="space-y-1">
            {missingInfo.map((info, index) => (
              <li key={index} className="text-2xs text-red-300/70 flex items-start gap-1.5">
                <span className="text-red-400 mt-0.5">?</span>
                {info}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
