import { useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import logoImg from '@/assets/logo.png';
import { getPapers, getSettings, type Paper, type Settings } from '@/lib/api';
import { S } from '@/lib/strings';
import UploadPanel from '@/components/home/UploadPanel';
import RecentPaperRow, { formatPaperDate } from '@/components/home/RecentPaperRow';

export default function Upload() {
  const navigate = useNavigate();

  const [settingsSnapshot, setSettingsSnapshot] = useState<Settings | null>(null);
  const [systemReady, setSystemReady] = useState<boolean | null>(null);
  const [recentAnalyses, setRecentAnalyses] = useState<Paper[]>([]);
  const [recentLibrary, setRecentLibrary] = useState<Paper[]>([]);

  useEffect(() => {
    let cancelled = false;

    getSettings()
      .then((data) => {
        if (cancelled) return;
        setSettingsSnapshot(data);
        setSystemReady(true);
      })
      .catch(() => {
        if (cancelled) return;
        setSystemReady(false);
      });

    Promise.all([
      getPapers({
        page: 1,
        page_size: 4,
        sort_by: 'analyzed_at',
        sort_order: 'desc',
      }),
      getPapers({
        page: 1,
        page_size: 4,
        sort_by: 'created_at',
        sort_order: 'desc',
      }),
    ])
      .then(([analysisResponse, libraryResponse]) => {
        if (cancelled) return;
        setRecentAnalyses(analysisResponse.papers.filter((paper) => paper.analyzed_at).slice(0, 4));
        setRecentLibrary(libraryResponse.papers.slice(0, 4));
      })
      .catch(() => {
        if (cancelled) return;
        setRecentAnalyses([]);
        setRecentLibrary([]);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const systemStatusClass =
    systemReady === null
      ? 'archive-inline-status archive-inline-status-muted'
      : systemReady
        ? 'archive-inline-status archive-inline-status-success'
        : 'archive-inline-status archive-inline-status-error';

  const handleOpenRecent = useCallback(
    (id: string) => {
      navigate(`/workbench/${id}`);
    },
    [navigate]
  );

  const systemSummary = [
    {
      label: S.upload.systemLibrary,
      value: settingsSnapshot?.library_path || S.upload.systemNotConfigured,
    },
    {
      label: S.upload.systemAuto,
      value: settingsSnapshot?.auto_analyze ? S.upload.systemAutoOn : S.upload.systemAutoOff,
    },
    {
      label: S.upload.systemTheme,
      value: settingsSnapshot?.theme === 'light' ? S.settings.light : S.settings.dark,
    },
  ];

  return (
    <div className="page-container-wide">
      <section className="page-header-dense mb-4">
        <div>
          <div className="archive-kicker">{S.upload.heroKicker}</div>
          <div className="mt-3 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-border/80 bg-surface/85">
              <img src={logoImg} alt="Sasoo" className="h-7 w-7 rounded-xl" />
            </div>
            <div>
              <h1 className="text-[1.45rem] font-semibold tracking-[-0.05em] text-fg">
                {S.app.name}
              </h1>
              <p className="text-sm text-fg-muted">{S.upload.heroBody}</p>
            </div>
          </div>
        </div>
        <div className="page-status-strip">
          <span className={systemStatusClass}>
            <span className={`h-2 w-2 rounded-full ${systemReady ? 'bg-success' : systemReady === false ? 'bg-warning' : 'bg-fg-muted'}`} />
            {systemReady === null
              ? S.settings.loadingSettings
              : systemReady
                ? S.upload.systemReady
                : S.upload.systemOffline}
          </span>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.18fr)_minmax(24rem,34rem)]">
        <UploadPanel />

        <div className="grid gap-4">
          <section className="archive-panel panel-compact">
            <div className="archive-kicker">{S.upload.recentAnalyses}</div>
            <div className="mt-3 grid gap-3">
              {recentAnalyses.length > 0 ? (
                recentAnalyses.map((paper) => (
                  <RecentPaperRow
                    key={`recent-analysis-${paper.id}`}
                    paper={paper}
                    metaLabel={S.upload.lastAnalyzed}
                    metaValue={formatPaperDate(paper.analyzed_at)}
                    onOpen={handleOpenRecent}
                  />
                ))
              ) : (
                <div className="rounded-surface bg-surface/30 px-4 py-5 text-sm leading-6 text-fg-muted">
                  {S.upload.recentAnalysesEmpty}
                </div>
              )}
            </div>
          </section>

          <section className="archive-panel panel-compact">
            <div className="archive-kicker">{S.upload.recentLibrary}</div>
            <div className="mt-3 grid gap-3">
              {recentLibrary.length > 0 ? (
                recentLibrary.map((paper) => (
                  <RecentPaperRow
                    key={`recent-library-${paper.id}`}
                    paper={paper}
                    metaLabel={S.upload.addedLabel}
                    metaValue={formatPaperDate(paper.created_at)}
                    onOpen={handleOpenRecent}
                  />
                ))
              ) : (
                <div className="rounded-surface bg-surface/30 px-4 py-5 text-sm leading-6 text-fg-muted">
                  {S.upload.recentLibraryEmpty}
                </div>
              )}
            </div>
          </section>

          <section className="archive-panel panel-compact">
            <div className="archive-kicker">{S.upload.systemTitle}</div>
            <div className="mt-3 grid gap-3">
              {systemSummary.map((item) => (
                <div
                  key={item.label}
                  className="flex items-center justify-between gap-4 rounded-surface bg-surface/30 px-4 py-3"
                >
                  <span className="text-2xs uppercase tracking-[0.16em] text-fg-muted">{item.label}</span>
                  <span className="max-w-[65%] truncate text-right text-base text-fg">{item.value}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      </section>
    </div>
  );
}
