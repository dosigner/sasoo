import { useCallback, useMemo, useState } from 'react';
import { BarChart3, ChevronsDownUp, ChevronsUpDown, FileText, FolderDown, GitBranch, Loader2, RefreshCw, Sparkles, Target } from 'lucide-react';
import type { Figure, MermaidDiagram, Recipe, SynthesisResult, VisualizationItem, VisualizationPlan } from '@/lib/api';
import { runSynthesis } from '@/lib/api';
import { assignBlocks, pickReproRows } from '@/lib/synthesisBlocks';
import { S } from '@/lib/strings';
import { AppIcon } from '@/components/icons';
import Modal from '@/components/ui/Modal';
import { VisualizationGallery, useVisualizationActions } from '../VisualizationGallery';
import { DiagramCard } from './DiagramCard';
import { DiagramLightbox, type LightboxTarget } from './DiagramLightbox';
import { EquationChain } from './EquationChain';
import { FigureStrip } from './FigureStrip';
import { BlockSection, ProblemBlock, ReproductionBlock, SummaryBlock, problemFields } from './blocks';

const T = S.synthesis;

interface SynthesisViewProps {
  paperId: number | null;
  synthesis: SynthesisResult | null;
  visualizations: VisualizationPlan | null;
  legacyMermaid: MermaidDiagram | null;
  deepDive: Record<string, unknown> | null;
  figures: Figure[];
  recipe: Recipe | null;
  /** deep_dive가 아직 도는 중. 종합은 그 뒤에 자동으로 도착한다. */
  analysisRunning: boolean;
  onRefreshSynthesis?: () => Promise<void>;
  onOpenFigure: (anchor: string) => void;
  onOpenRecipe: () => void;
}

function SkeletonCard() {
  return (
    <div className="card p-0" role="status" aria-busy="true" aria-label={T.diagramGenerating}>
      <div className="px-4 pb-2 pt-3">
        <div className="h-3 w-40 animate-pulse rounded-sm bg-border" />
      </div>
      <div className="mx-4 mb-4 h-48 animate-pulse rounded-lg bg-border" />
    </div>
  );
}

export function SynthesisView({
  paperId,
  synthesis,
  visualizations,
  legacyMermaid,
  deepDive,
  figures,
  recipe,
  analysisRunning,
  onRefreshSynthesis,
  onOpenFigure,
  onOpenRecipe,
}: SynthesisViewProps) {
  const actions = useVisualizationActions();
  const [expandAll, setExpandAll] = useState(false);
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);

  const pid = paperId ?? visualizations?.paper_id ?? null;
  const items = useMemo(
    () => (visualizations?.items ?? []).map((it) => actions.itemOverrides[it.id] ?? it),
    [visualizations, actions.itemOverrides]
  );
  const blocks = useMemo(() => assignBlocks(items), [items]);

  const targets = useMemo<LightboxTarget[]>(() => {
    const out: LightboxTarget[] = [];
    if (blocks.concept) out.push({ item: blocks.concept, blockLabel: T.blockTitleMethod });
    for (const it of blocks.method) out.push({ item: it, blockLabel: T.blockTitleMethod });
    for (const it of blocks.result) out.push({ item: it, blockLabel: T.blockTitleResult });
    return out;
  }, [blocks]);
  const openItem = useCallback(
    (item: VisualizationItem) => {
      const idx = targets.findIndex((t) => t.item.id === item.id);
      if (idx >= 0) setLightboxIndex(idx);
    },
    [targets]
  );

  const build = useCallback(async () => {
    if (!pid) return;
    setBuilding(true);
    setBuildError('');
    try {
      await runSynthesis(pid);
      await onRefreshSynthesis?.();
    } catch {
      setBuildError(T.generationFailed);
    } finally {
      setBuilding(false);
    }
  }, [pid, onRefreshSynthesis]);

  const card = (item: VisualizationItem) => (
    <DiagramCard
      key={item.id}
      item={item}
      paperId={pid ?? 0}
      expandAll={expandAll}
      regenerating={!!actions.regeneratingIds[item.id]}
      regenerateError={actions.regenerateErrors[item.id]}
      onOpen={() => openItem(item)}
      onRegenerate={pid ? () => actions.handleRegenerate(pid, item.id) : undefined}
      onRepair={pid ? actions.makeRepairHandler(pid, item.id) : undefined}
    />
  );

  // 기존 논문: 종합 결과가 없으면 갤러리를 그대로 두고 만들기 버튼만 얹는다(스펙 §7).
  if (!synthesis) {
    return (
      <div className="space-y-4">
        {!analysisRunning && (
          <div className="card flex items-center gap-3">
            <Sparkles className="h-4 w-4 shrink-0 text-accent" />
            <p className="flex-1 text-xs leading-relaxed text-fg-muted">{T.createGuide}</p>
            <button className="btn-primary px-3 py-1.5 text-xs" disabled={building || !pid} onClick={() => void build()}>
              {building ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
              {building ? T.loading : T.createTitle}
            </button>
          </div>
        )}
        {buildError && <p className="text-2xs text-danger">{buildError}</p>}
        <VisualizationGallery visualizations={visualizations} legacyMermaid={legacyMermaid} loading={analysisRunning} />
      </div>
    );
  }

  const hasProblem = (() => {
    const f = problemFields(deepDive);
    return !!(f.asIs || f.toBe);
  })();
  const repro = pickReproRows(recipe?.recipe ?? null, synthesis.key_parameters);
  const diagramsPending = !visualizations && analysisRunning;
  const methodCount = blocks.method.length + (blocks.concept ? 1 : 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-fg">{T.viewTitle}</h2>
        <span className="text-2xs text-fg-muted tabular-nums">{T.diagramCount(items.length)}</span>
        <div className="ml-auto flex items-center gap-1">
          <button
            className="btn-ghost text-2xs px-2 py-1"
            disabled={actions.exporting || !pid || items.length === 0}
            onClick={() => pid && void actions.handleExportAll(pid, items)}
            title={T.exportAll}
          >
            {actions.exporting ? <Loader2 className="h-3 w-3 animate-spin" /> : <FolderDown className="h-3 w-3" />}
            {T.exportAll}
          </button>
          <button className="btn-ghost text-2xs px-2 py-1" onClick={() => setExpandAll((v) => !v)} aria-pressed={expandAll}>
            {expandAll ? <ChevronsDownUp className="h-3 w-3" /> : <ChevronsUpDown className="h-3 w-3" />}
            {expandAll ? T.collapseAll : T.expandAll}
          </button>
          <button className="btn-ghost text-2xs px-2 py-1" disabled={building || !pid} onClick={() => setConfirmOpen(true)}>
            <RefreshCw className={`h-3 w-3 ${building ? 'animate-spin' : ''}`} />
            {T.regenerateButton}
          </button>
        </div>
      </div>
      {actions.exportError && <p className="text-2xs text-danger">{actions.exportError}</p>}
      {buildError && <p className="text-2xs text-danger">{buildError}</p>}

      <BlockSection icon={<FileText className="h-4 w-4 text-accent" />} title={T.blockTitleSummary}>
        <SummaryBlock synthesis={synthesis} />
      </BlockSection>

      {hasProblem && (
        <BlockSection icon={<Target className="h-4 w-4 text-accent" />} title={T.blockTitleProblem}>
          <ProblemBlock deepDive={deepDive} />
        </BlockSection>
      )}

      <BlockSection
        icon={<GitBranch className="h-4 w-4 text-accent" />}
        title={T.blockTitleMethod}
        meta={methodCount > 0 ? T.diagramCount(methodCount) : undefined}
      >
        {blocks.concept ? card(blocks.concept) : diagramsPending ? <SkeletonCard /> : null}
        <EquationChain equations={synthesis.equations} expandAll={expandAll} />
        {blocks.method.map(card)}
        {diagramsPending && <SkeletonCard />}
      </BlockSection>

      <BlockSection
        icon={<BarChart3 className="h-4 w-4 text-accent" />}
        title={T.blockTitleResult}
        meta={blocks.result.length > 0 ? T.diagramCount(blocks.result.length) : undefined}
      >
        <FigureStrip refs={synthesis.result_figures} figures={figures} onOpenFigure={onOpenFigure} />
        {blocks.result.map(card)}
        {diagramsPending && <SkeletonCard />}
      </BlockSection>

      <BlockSection icon={<AppIcon name="recipe" className="h-4 w-4 text-accent" />} title={T.blockTitleRepro}>
        <ReproductionBlock rows={repro.rows} showNotes={repro.showNotes} onOpenRecipe={onOpenRecipe} />
      </BlockSection>

      {lightboxIndex !== null && pid && (
        <DiagramLightbox
          targets={targets}
          index={lightboxIndex}
          paperId={pid}
          onClose={() => setLightboxIndex(null)}
          onIndexChange={setLightboxIndex}
          makeRepairHandler={actions.makeRepairHandler}
        />
      )}

      <Modal open={confirmOpen} onClose={() => setConfirmOpen(false)}>
        <h3 className="mb-2 text-lg font-semibold text-fg">{T.regenerateButton}</h3>
        <div className="mb-4 space-y-1 text-sm text-fg-muted">
          <p>{T.regenerateConfirmBody}</p>
          <p className="font-medium text-accent">
            {synthesis.cost_usd ? T.regenerateCostLast(synthesis.cost_usd.toFixed(4)) : T.regenerateCostEstimate}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            className="btn-primary flex-1 py-2 text-sm"
            onClick={() => {
              setConfirmOpen(false);
              void build();
            }}
          >
            {T.regenerateConfirm}
          </button>
          <button className="btn-ghost flex-1 py-2 text-sm" onClick={() => setConfirmOpen(false)}>
            {T.regenerateCancel}
          </button>
        </div>
      </Modal>
    </div>
  );
}
