import { useState, useCallback, lazy, Suspense } from 'react';
import { AlertCircle, Loader2, Download, FolderDown, RefreshCw } from 'lucide-react';
import { getStaticUrl, repairMermaid, regenerateVisualization } from '@/lib/api';
import type { VisualizationItem, VisualizationPlan, MermaidDiagram } from '@/lib/api';
import { S } from '@/lib/strings';
import { assetExtension, downloadBlob, safeAssetFilename } from '@/lib/download';
import { AppIcon } from '@/components/icons';

const MermaidRenderer = lazy(() => import('./MermaidRenderer'));

function PaperBananaViewer({ item }: { item: VisualizationItem }) {
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  // Download the generated illustration. Served same-origin from the backend
  // (/static/...), so fetching it into a blob is enough.
  const handleDownload = useCallback(async () => {
    if (!item.image_url) return;
    setSaving(true);
    setSaveError('');
    try {
      const res = await fetch(getStaticUrl(item.image_url));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const base = safeAssetFilename(item.title, 'illustration');
      downloadBlob(`${base}.${assetExtension(item.image_url)}`, blob);
    } catch (err) {
      console.error('Illustration download failed:', err);
      setSaveError(S.figures.saveFailed);
    } finally {
      setSaving(false);
    }
  }, [item.image_url, item.title]);

  if (item.status === 'error') {
    return (
      <div className="flex flex-col items-center justify-center py-6 text-center">
        <AlertCircle className="w-6 h-6 text-danger mb-2" />
        <p className="text-sm text-danger">{S.mermaid.illustrationFailed}</p>
        {item.error_message && (
          <p className="text-2xs text-fg-muted mt-1">{item.error_message}</p>
        )}
      </div>
    );
  }

  if (!item.image_url) {
    return (
      <div className="flex items-center justify-center py-8" role="status" aria-busy="true">
        <Loader2 className="w-5 h-5 text-accent animate-spin" />
      </div>
    );
  }

  return (
    <div className="group relative overflow-hidden rounded-lg border border-border">
      <img
        src={getStaticUrl(item.image_url)}
        alt={item.title}
        className="w-full h-auto object-contain bg-surface"
        loading="lazy"
      />
      <button
        onClick={handleDownload}
        disabled={saving}
        className="absolute right-2 top-2 flex items-center justify-center rounded-md border border-border/60 bg-surface/90 p-1.5 text-fg-muted opacity-0 shadow-xs backdrop-blur-sm transition hover:text-fg focus-visible:opacity-100 group-hover:opacity-100 disabled:opacity-50"
        aria-label={S.figures.saveImage}
        title={S.figures.saveImage}
      >
        {saving ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Download className="h-4 w-4" />
        )}
      </button>
      {saveError && (
        <p className="flex items-center gap-1 border-t border-border px-2 py-1 text-2xs text-danger">
          <AlertCircle className="h-3 w-3" />
          {saveError}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Visualization Gallery (renders multiple items)
// ---------------------------------------------------------------------------

export function VisualizationGallery({
  visualizations,
  legacyMermaid,
  loading,
}: {
  visualizations: VisualizationPlan | null;
  legacyMermaid: MermaidDiagram | null;
  loading: boolean;
}) {
  // Locally regenerated/repaired items override the fetched plan until the
  // next reload (the backend persists them too).
  const [itemOverrides, setItemOverrides] = useState<Record<number, VisualizationItem>>({});
  const [regeneratingIds, setRegeneratingIds] = useState<Record<number, boolean>>({});
  const [regenerateErrors, setRegenerateErrors] = useState<Record<number, string>>({});
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState('');

  const handleExportAll = useCallback(
    async (paperId: number, items: VisualizationItem[]) => {
      setExporting(true);
      setExportError('');
      try {
        const { exportVisualizationsZip } = await import('@/lib/vizExport');
        await exportVisualizationsZip(paperId, items);
      } catch {
        setExportError(S.mermaid.exportFailed);
      } finally {
        setExporting(false);
      }
    },
    []
  );

  const handleRegenerate = useCallback(
    async (paperId: number, vizId: number) => {
      setRegeneratingIds((prev) => ({ ...prev, [vizId]: true }));
      setRegenerateErrors((prev) => ({ ...prev, [vizId]: '' }));
      try {
        const updated = await regenerateVisualization(paperId, vizId);
        setItemOverrides((prev) => ({ ...prev, [vizId]: updated }));
      } catch {
        setRegenerateErrors((prev) => ({
          ...prev,
          [vizId]: S.mermaid.regenerateFailed,
        }));
      } finally {
        setRegeneratingIds((prev) => ({ ...prev, [vizId]: false }));
      }
    },
    []
  );

  const makeRepairHandler = useCallback(
    (paperId: number, vizId: number | null) =>
      async (code: string, errorMessage: string): Promise<string | null> => {
        try {
          const result = await repairMermaid(paperId, {
            mermaid_code: code,
            error_message: errorMessage,
            viz_id: vizId,
          });
          return result.mermaid_code || null;
        } catch {
          return null;
        }
      },
    []
  );

  // If we have the new visualization plan, use it
  if (visualizations && visualizations.items.length > 0) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2 mb-2">
          <AppIcon name="experiment" className="w-4 h-4 text-accent" />
          <span className="text-sm font-semibold text-fg">
            {S.mermaid.visualizations}
          </span>
          <span className="badge text-2xs bg-accent/10 text-accent">
            {visualizations.items.length}
          </span>
          <button
            onClick={() =>
              handleExportAll(
                visualizations.paper_id,
                visualizations.items.map((it) => itemOverrides[it.id] ?? it)
              )
            }
            disabled={exporting}
            className="btn-ghost text-2xs px-2 py-0.5 ml-auto"
            title={S.mermaid.exportAll}
          >
            {exporting ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <FolderDown className="w-3 h-3" />
            )}
            {exporting ? S.mermaid.exporting : S.mermaid.exportAll}
          </button>
        </div>
        {exportError && <p className="text-2xs text-danger">{exportError}</p>}
        {visualizations.items.map((rawItem) => {
          const item = itemOverrides[rawItem.id] ?? rawItem;
          const isRegenerating = !!regeneratingIds[item.id];
          return (
          <div key={item.id} className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-fg-secondary">
                {item.id}. {item.title}
              </span>
              <span className={`badge text-2xs ${
                item.tool === 'mermaid'
                  ? 'bg-accent/10 text-accent'
                  : 'bg-warning/10 text-warning'
              }`}>
                {item.tool === 'mermaid' ? 'Mermaid' : 'PaperBanana'}
              </span>
              {item.tool === 'mermaid' && (
                <button
                  onClick={() => handleRegenerate(visualizations.paper_id, item.id)}
                  disabled={isRegenerating}
                  className="btn-ghost text-2xs px-2 py-0.5 ml-auto"
                  title={S.mermaid.regenerate}
                >
                  <RefreshCw
                    className={`w-3 h-3 ${isRegenerating ? 'animate-spin' : ''}`}
                  />
                  {isRegenerating ? S.mermaid.regenerating : S.mermaid.regenerate}
                </button>
              )}
            </div>
            {regenerateErrors[item.id] && (
              <p className="text-2xs text-danger">{regenerateErrors[item.id]}</p>
            )}
            {item.description && (
              <p className="text-xs text-fg-muted leading-relaxed">
                {item.description}
              </p>
            )}
            {item.tool === 'mermaid' && item.mermaid_code ? (
              <Suspense fallback={<div className="flex items-center gap-2 py-4 justify-center"><Loader2 className="w-4 h-4 text-accent animate-spin" /></div>}>
                <MermaidRenderer
                  diagram={{
                    paper_id: visualizations.paper_id,
                    mermaid_code: item.mermaid_code,
                    diagram_type: item.diagram_type,
                    description: item.description,
                  }}
                  loading={false}
                  title={item.title}
                  onRepair={makeRepairHandler(visualizations.paper_id, item.id)}
                />
              </Suspense>
            ) : item.tool === 'paperbanana' ? (
              <PaperBananaViewer item={item} />
            ) : item.status === 'error' ? (
              <div className="text-sm text-danger py-2">
                {item.error_message || S.mermaid.generationFailed}
              </div>
            ) : (
              <div className="flex items-center gap-2 py-4 justify-center" role="status" aria-busy="true">
                <Loader2 className="w-4 h-4 text-accent animate-spin" />
                <span className="text-xs text-fg-muted">{S.mermaid.generating}</span>
              </div>
            )}
          </div>
          );
        })}
      </div>
    );
  }

  // If deep_dive is done but visualizations haven't arrived yet, show generating state
  if (!loading && !legacyMermaid) {
    return (
      <div>
        <h3 className="text-sm font-semibold text-fg mb-3 flex items-center gap-2">
          <AppIcon name="experiment" className="w-4 h-4 text-accent" />
          {S.mermaid.visualizations}
        </h3>
        <div className="card flex flex-col items-center justify-center py-8 text-center">
          <Loader2 className="w-6 h-6 text-accent animate-spin mb-2" />
          <p className="text-sm text-fg-muted">
            {S.mermaid.generating}
          </p>
          <p className="text-2xs text-fg-muted mt-1">
            {S.mermaid.generatingTime}
          </p>
        </div>
      </div>
    );
  }

  // Fallback: legacy single mermaid diagram
  return (
    <Suspense fallback={<div className="flex items-center gap-2 py-4 justify-center"><Loader2 className="w-4 h-4 text-accent animate-spin" /></div>}>
      <MermaidRenderer
        diagram={legacyMermaid}
        loading={loading}
        onRepair={
          legacyMermaid
            ? makeRepairHandler(legacyMermaid.paper_id, null)
            : undefined
        }
      />
    </Suspense>
  );
}
