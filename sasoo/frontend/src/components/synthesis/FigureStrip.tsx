import type { Figure, SynthesisFigureRef } from '@/lib/api';
import { getLibraryAssetUrl } from '@/lib/api';
import { S } from '@/lib/strings';

const T = S.synthesis;
const figureNumber = (raw: string | null | undefined) => raw?.match(/\d+/)?.[0] ?? null;

/** 그림 참조 스트립. 원본 크기로 그리지 않고 그림 탭으로 보낸다(스펙 §3.4). */
export function FigureStrip({
  refs,
  figures,
  onOpenFigure,
}: {
  refs: SynthesisFigureRef[];
  figures: Figure[];
  onOpenFigure: (anchor: string) => void;
}) {
  const rows = refs
    .map((ref) => {
      const num = figureNumber(ref.figure_num);
      const fig = num ? figures.find((f) => figureNumber(f.figure_num) === num) : undefined;
      return { ref, num, fig };
    })
    .filter((r): r is { ref: SynthesisFigureRef; num: string; fig: Figure } => !!r.num && !!r.fig?.file_path);
  if (rows.length === 0) return null;
  return (
    <div className="flex gap-3 overflow-x-auto pb-1">
      {rows.map(({ ref, num, fig }) => (
        <button
          key={num}
          type="button"
          onClick={() => onOpenFigure(`figure-${num}`)}
          className="group flex w-max shrink-0 flex-col items-start gap-1 text-left"
          title={T.openInFigures}
        >
          <img
            src={getLibraryAssetUrl(fig.file_path)}
            alt={fig.caption ?? T.figureLabel(num)}
            className="h-[140px] w-auto rounded-md border border-border bg-surface object-contain transition group-hover:border-accent/60"
            loading="lazy"
          />
          <span className="text-2xs font-medium text-fg-secondary">{T.figureLabel(num)}</span>
          <span className="line-clamp-2 max-w-[240px] text-2xs text-fg-muted">{ref.interpretation}</span>
        </button>
      ))}
    </div>
  );
}
