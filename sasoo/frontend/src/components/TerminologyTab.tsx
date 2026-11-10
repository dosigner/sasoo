import { useContext, useMemo, useState } from 'react';
import { Search, X } from 'lucide-react';
import { AppIcon } from './icons';
import { ContentState, Modal } from './ui';
import { TerminologyContext, useSharedReadingGuide } from '@/lib/readingGuideContext';
import type { TerminologyEntry } from '@/lib/readingGuide';

const scopeLabel = (entry: TerminologyEntry) => entry.scope === 'paper' ? '이 논문' : entry.scope === 'field' ? '분야 기본' : '기존 표기 사전';

export default function TerminologyTab({ paperId, onSearchInPdf }: {
  paperId: string | null;
  onSearchInPdf?: (term: string, page: number | null) => void;
}) {
  const terms = useContext(TerminologyContext);
  const { status, guide, error, errorType, reload, generate, cancel } = useSharedReadingGuide();
  const [query, setQuery] = useState('');
  const [selection, setSelection] = useState<{ terms: typeof terms; selected: string[] }>({ terms, selected: [] });
  const selected = selection.terms === terms ? selection.selected : selection.selected.filter(name => terms.some(term => term.term === name));
  if (selection.terms !== terms) setSelection({ terms, selected });
  const setSelected = (next: string[] | ((current: string[]) => string[])) => setSelection(current => ({
    terms, selected: typeof next === 'function' ? next(current.selected) : next,
  }));
  const [confirmOpen, setConfirmOpen] = useState(false);
  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return terms.filter(term => `${term.term} ${term.korean} ${term.definition}`.toLocaleLowerCase().includes(needle));
  }, [query, terms]);
  const compared = terms.filter(term => selected.includes(term.term));
  const isRegenerate = Boolean(guide);
  const busy = status === 'generating';

  const toggle = (term: string) => setSelected(current => current.includes(term)
    ? current.filter(item => item !== term) : current.length < 3 ? [...current, term] : current);
  const search = (entry: TerminologyEntry) => onSearchInPdf?.(entry.term.replace(/\s*\([A-Z][A-Z0-9-]*\)$/, ''), entry.page);

  if (status === 'loading') return <ContentState icon={props => <AppIcon name="library" {...props} />}
    title="용어 사전을 불러오고 있어요" loading tone="muted" />;

  return <section className="space-y-5" aria-label="용어 사전">
    <Modal open={confirmOpen} onClose={() => setConfirmOpen(false)}
      title={isRegenerate ? '읽기 안내와 용어 사전 다시 만들기' : '읽기 안내와 용어 사전 만들기'}>
      <h3 className="mb-2 text-lg font-semibold text-fg">읽기 안내와 용어 사전을 함께 만들어요</h3>
      <p className="mb-3 text-sm text-fg-secondary">논문의 분야 기본 용어와 핵심 용어를 정리해 저장해요. 생성할 때 AI 사용 비용이 발생하며, 이후 검색과 hover에는 추가 호출이 없어요.</p>
      {isRegenerate && <p className="mb-4 text-sm text-fg-secondary">완료되면 기존 읽기 안내와 사전을 새 결과로 바꿔요. 실패하거나 취소하면 기존 결과를 유지해요.</p>}
      <div className="flex gap-2">
        <button type="button" className="btn-primary flex-1 py-2 text-sm" onClick={() => {
          setConfirmOpen(false);
          void generate();
        }}>만들기</button>
        <button type="button" className="btn-ghost flex-1 py-2 text-sm" onClick={() => setConfirmOpen(false)}>닫기</button>
      </div>
    </Modal>

    <div className="workbench-tab-heading">
      <div className="min-w-0 flex-1">
        <h3 className="flex items-center gap-2 text-lg font-semibold text-fg"><AppIcon name="library" className="h-4 w-4 text-accent" />용어 사전</h3>
        <p className="mt-1 text-sm text-fg-secondary">영어 용어의 한국어 뜻을 확인하고, 최대 3개를 나란히 비교해요.</p>
      </div>
      {!busy && status !== 'error' && <button type="button" disabled={!paperId} onClick={() => setConfirmOpen(true)}
        className={`${terms.length ? 'btn-ghost' : 'btn-primary'} shrink-0 px-3 py-1.5 text-xs`}>
        {isRegenerate ? '다시 만들기' : '사전 만들기'}
      </button>}
    </div>

    {busy && <div role="status" className="flex items-center justify-between gap-3 text-sm text-fg-secondary">
      <span className="flex items-center gap-2"><AppIcon name="spinner" className="h-4 w-4 animate-spin" />읽기 안내와 용어 사전을 만들고 있어요.</span>
      <button type="button" className="btn-ghost shrink-0 px-2 py-1 text-xs" onClick={cancel}>생성 취소</button>
    </div>}

    {status === 'error' && <ContentState icon={props => <AppIcon name="error" {...props} />} tone="error"
      title={errorType === 'load' ? '사전을 불러오지 못했어요' : '사전을 만들지 못했어요'} description={error ?? undefined}
      actionLabel={errorType === 'load' ? '다시 불러오기' : '다시 만들기'}
      onAction={errorType === 'load' ? reload : () => setConfirmOpen(true)} />}

    {!terms.length ? !busy && status !== 'error' && <div className="workbench-empty-state gap-2">
      <AppIcon name="library" className="h-7 w-7 text-accent" />
      <p className="text-sm font-medium text-fg">영어 용어를 읽다가 뜻이 궁금할 때</p>
      <p className="max-w-sm text-sm text-fg-secondary">사전을 만들면 분석 본문과 토의의 영어 용어에 마우스를 올려 한국어 설명을 볼 수 있어요. 기존 한국어 문장은 그대로 유지해요.</p>
    </div> : <>
      {terms.every(term => term.scope === 'legacy') && <p className="text-sm text-fg-secondary">
        기존 표기 사전의 영어 항목을 보여주고 있어요. 다시 만들면 분야 기본 용어와 논문의 핵심 용어도 정리해요.
      </p>}
      <div className="flex flex-wrap items-center gap-3">
        <label className="relative min-w-0 flex-1">
          <span className="sr-only">용어 검색</span><Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-muted" />
          <input className="input w-full pl-9 pr-9 text-sm" type="search" value={query} placeholder="영어 용어 또는 한국어 뜻 검색"
            onChange={event => setQuery(event.target.value)} />
        </label>
        <span className="shrink-0 text-xs tabular-nums text-fg-secondary" aria-live="polite">{visible.length} / {terms.length}개</span>
      </div>

      {compared.length > 0 && <section aria-label="선택한 용어 비교" className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <h4 className="text-sm font-semibold text-fg">선택한 용어 비교 {compared.length}/3</h4>
          <button type="button" onClick={() => setSelected([])} className="btn-ghost px-2 py-1 text-xs">선택 해제</button>
        </div>
        {compared.length === 1 && <p className="text-xs text-fg-secondary">비교할 용어를 하나 더 선택하세요. 검색어를 바꿔도 선택은 유지돼요.</p>}
        {compared.length > 1 && <p className="text-xs text-fg-secondary">좁은 화면에서는 표를 좌우로 스크롤해 비교하세요.</p>}
        <div className="overflow-x-auto rounded-control border border-border focus-visible:outline-2 focus-visible:outline-accent" role="region" tabIndex={0} aria-label="용어 비교 표">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">선택한 용어의 한국어 뜻과 설명 비교</caption>
            <thead><tr><th scope="col" className="min-w-24 border-b border-border bg-bg p-3 font-medium text-fg-secondary">항목</th>
              {compared.map(entry => <th key={entry.term} scope="col" className="min-w-48 border-b border-border bg-bg p-3 align-top">
                <div className="flex items-start gap-2"><span className="flex-1 break-words font-semibold text-fg">{entry.term}</span>
                  <button type="button" aria-label={`${entry.term} 비교에서 제외`} onClick={() => toggle(entry.term)} className="btn-icon shrink-0 p-1"><X className="h-3.5 w-3.5" /></button>
                </div>
              </th>)}</tr></thead>
            <tbody>
              {(['한국어 뜻', '설명', '범위'] as const).map(label => <tr key={label}>
                <th scope="row" className="border-b border-border/60 p-3 align-top font-medium text-fg-secondary">{label}</th>
                {compared.map(entry => <td key={entry.term} className="border-b border-border/60 p-3 align-top leading-relaxed text-fg">
                  {label === '한국어 뜻' ? entry.korean || '설명 참고' : label === '설명' ? entry.definition : scopeLabel(entry)}
                </td>)}
              </tr>)}
              <tr><th scope="row" className="p-3 align-top font-medium text-fg-secondary">원문</th>
                {compared.map(entry => <td key={entry.term} className="p-3 align-top">{onSearchInPdf
                  ? <button type="button" onClick={() => search(entry)} className="text-accent underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-accent">{entry.page !== null ? `p.${entry.page}에서 찾기` : '원문에서 찾기'}</button>
                  : entry.page !== null ? `p.${entry.page}` : '페이지 미확인'}</td>)}
              </tr>
            </tbody>
          </table>
        </div>
      </section>}

      {visible.length ? <ul className="list-none divide-y divide-border pl-0" aria-label="용어 목록">
        {visible.map(entry => <li key={entry.term} className="py-3 first:pt-0">
          <div className="flex items-start gap-3">
            <input type="checkbox" aria-label={`${entry.term} 비교 선택`} className="mt-1 h-4 w-4 shrink-0 accent-accent"
              checked={selected.includes(entry.term)} disabled={compared.length >= 3 && !selected.includes(entry.term)} onChange={() => toggle(entry.term)} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="break-words text-sm font-semibold text-fg">{entry.term}</span>
                {entry.korean && <span className="text-sm text-fg-secondary">{entry.korean}</span>}
              </div>
              <p className="mt-1 text-sm leading-relaxed text-fg">{entry.definition}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-secondary">
                <span>{scopeLabel(entry)}</span>
                {onSearchInPdf && <button type="button" onClick={() => search(entry)} className="text-accent hover:underline focus-visible:outline-2 focus-visible:outline-accent">
                  {entry.page !== null ? `p.${entry.page}에서 찾기` : '원문에서 찾기'}
                </button>}
              </div>
            </div>
          </div>
        </li>)}
      </ul> : <p className="py-6 text-center text-sm text-fg-secondary">일치하는 용어가 없어요. 영어 이름이나 다른 한국어 표현으로 찾아보세요.</p>}
      <p className="text-xs leading-relaxed text-fg-secondary">AI가 정리한 설명이에요. 같은 약어라도 분야나 논문에 따라 뜻이 다를 수 있으니 원문과 대조하세요.</p>
    </>}
  </section>;
}
