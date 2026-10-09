import { Children, useState, useRef, useEffect, useCallback, useMemo, type ReactNode } from 'react';
import {
  ArrowDown,
  ChevronDown,
  ChevronRight,
  MessageSquare,
  MoreHorizontal,
  RotateCcw,
  Send,
  Sparkles,
  Square,
  Trash2,
  X,
} from 'lucide-react';
import { type Components } from 'react-markdown';
import { Markdown } from '@/components/Markdown';
import type { DiscussionResetReason } from '@/lib/api';
import {
  hasActiveContext,
  hiddenBeforeReset,
  lastResetIndex,
  useDiscussion,
} from '@/hooks/useDiscussion';
import { withRoJosa } from '@/lib/josa';
import { getAgentMeta } from '@/lib/agents';
import { detectCitations, type CitationType } from '@/lib/citations';
import { S } from '@/lib/strings';

// 런처가 원형으로 접힌 채 유지되는 기본 시간(첫 ready 전환 시 확장 카드를 보여주는 시간).
const LAUNCHER_INTRO_MS = 3000;

const RESET_TITLE: Record<DiscussionResetReason, string> = {
  manual: '새 맥락을 시작했어요',
  reanalysis: '재분석이 끝나 새로 시작했어요',
  budget: '맥락 예산을 넘어 새로 시작했어요',
};

// 21600 → "21.6K", 260000 → "260K".
const formatTokens = (n: number) => (n < 1000 ? `${n}` : `${(n / 1000).toFixed(n >= 100_000 ? 0 : 1)}K`);

// SQLite CURRENT_TIMESTAMP는 시간대 표기 없는 UTC다.
function formatResetTime(createdAt?: string): string {
  if (!createdAt) return '';
  const date = new Date(`${createdAt.replace(' ', 'T')}Z`);
  if (Number.isNaN(date.getTime())) return '';
  const sameDay = date.toDateString() === new Date().toDateString();
  return date.toLocaleString('ko-KR', sameDay
    ? { hour: '2-digit', minute: '2-digit' }
    : { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export interface CitationTarget {
  type: CitationType;
  n: number;
}

type CitationHandler = (target: CitationTarget) => void;

// Split a raw text run into plain segments + clickable citation chips.
// Only string children are tokenized, so text inside <code>/<a> (rendered by
// their own default components) is never turned into a chip.
function tokenizeCitations(text: string, onCitation: CitationHandler): ReactNode {
  const matches = detectCitations(text);
  if (matches.length === 0) return text;

  const nodes: ReactNode[] = [];
  let cursor = 0;
  matches.forEach((match, i) => {
    if (match.start > cursor) nodes.push(text.slice(cursor, match.start));
    nodes.push(
      <button
        key={`cite-${i}-${match.start}`}
        type="button"
        className="citation-chip"
        onClick={() => onCitation({ type: match.type, n: match.n })}
        title={`${withRoJosa(match.raw)} 이동`}
      >
        {match.raw}
      </button>,
    );
    cursor = match.end;
  });
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function processCitationChildren(children: ReactNode, onCitation: CitationHandler): ReactNode {
  return Children.map(children, (child) =>
    typeof child === 'string' ? tokenizeCitations(child, onCitation) : child,
  );
}

type OrbState = 'pending' | 'ready' | 'busy';

// 사수의 브랜드 표식. 색 그라디언트가 천천히 돌고, 답변 중에는 빨라진다. 의미는 감싼
// 버튼의 aria-label이 전달하므로 장식으로 숨긴다.
function DiscussionOrb({ state, className = '' }: { state: OrbState; className?: string }) {
  return (
    <span aria-hidden="true" data-state={state} className={`discussion-orb shrink-0 ${className}`}>
      <span />
    </span>
  );
}

interface ChatPanelProps {
  paperId: string;
  agentName?: string;
  /** 카드 부제. 없으면 담당 에이전트의 domain_display를 쓴다. */
  fieldLabel?: string;
  open: boolean;
  ready: boolean;
  readyMessage: string;
  draft: string;
  starters: string[];
  onToggleOpen: () => void;
  onDraftChange: (value: string) => void;
  onCitationClick?: CitationHandler;
}

export default function ChatPanel({
  paperId,
  agentName,
  fieldLabel,
  open,
  ready,
  readyMessage,
  draft,
  starters,
  onToggleOpen,
  onDraftChange,
  onCitationClick,
}: ChatPanelProps) {
  const { items, context, loadState, error, busy, refresh, send, stop, reset, remove } =
    useDiscussion(paperId, open);
  const [showOld, setShowOld] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const confirmCancelRef = useRef<HTMLButtonElement>(null);
  const [scrolled, setScrolled] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const stickToBottomRef = useRef(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef(false);
  const [instantTransition, setInstantTransition] = useState(false);
  const messagesRef = useRef<HTMLDivElement>(null);

  const agent = agentName ? getAgentMeta(agentName) : null;
  const hasMessages = items.length > 0;
  const totalCost = items.reduce((sum, item) => sum + (item.costUsd ?? 0), 0);
  const resetAt = lastResetIndex(items);
  const hiddenCount = hiddenBeforeReset(items);
  const canReset = !busy && hasActiveContext(items);
  // 접혀 있으면 마지막 맥락 초기화(안내 상자)부터 보인다.
  const visibleFrom = showOld || resetAt < 0 ? 0 : resetAt;
  // 닫힘 애니메이션 동안 카드를 유지한다. 런처는 카드가 완전히 빠진 뒤에 나타나야
  // 같은 flex 줄에 둘이 잠깐 나란히 섰다가 튀는 일이 없다.
  const [cardMounted, setCardMounted] = useState(open);
  useEffect(() => {
    if (!open) return;
    setCardMounted(true);
    // 다시 열면 새 카드에서 대화 끝을 보여준다.
    stickToBottomRef.current = true;
    setAtBottom(true);
  }, [open]);
  const cardVisible = open || cardMounted;
  useEffect(() => {
    if (!cardVisible && restoreFocusRef.current) {
      launcherRef.current?.focus();
      restoreFocusRef.current = false;
    }
  }, [cardVisible]);

  // 런처는 평소 원형 아이콘 버튼으로 접혀 있다가, ready가 false→true로 바뀌는
  // 순간에만 한 번 확장 카드를 보여주고 자동으로 다시 접힌다. 이미 ready 상태로
  // 마운트되면(재방문·탭 이동) prevReadyRef의 초기값이 곧 ready와 같아 건너뛴다.
  const [showLauncherIntro, setShowLauncherIntro] = useState(false);
  const prevReadyRef = useRef(ready);
  useEffect(() => {
    const wasReady = prevReadyRef.current;
    prevReadyRef.current = ready;
    if (wasReady || !ready) return;
    setShowLauncherIntro(true);
    const timer = window.setTimeout(() => setShowLauncherIntro(false), LAUNCHER_INTRO_MS);
    return () => window.clearTimeout(timer);
  }, [ready]);

  useEffect(() => {
    setShowOld(false);
    setContextOpen(false);
    setMenuOpen(false);
    setConfirmDelete(false);
    setScrolled(false);
    setAtBottom(true);
    stickToBottomRef.current = true;
  }, [paperId]);

  useEffect(() => {
    if (confirmDelete) confirmCancelRef.current?.focus();
  }, [confirmDelete]);

  // 스트리밍 중에는 토큰 플러시마다(약 25회/초) 이 효과가 돈다. scrollIntoView는
  // 호출할 때마다 부드러운 스크롤을 새로 시작해 끝나지 않고, 조상 스크롤 컨테이너까지
  // 건드린다. 메시지 목록의 scrollTop만 직접 옮겨 채팅 영역 안에서만 끝낸다.
  // 사용자가 위로 올려 읽는 중이면 따라 내려가지 않는다. 값은 스크롤 이벤트에서만
  // 갱신하므로, 토큰으로 scrollHeight가 늘어난 직후에도 직전 위치 기준으로 판단한다.
  useEffect(() => {
    if (!open || !stickToBottomRef.current) return;
    const el = messagesRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [items, open]);

  useEffect(() => {
    if (!open || !ready) return;
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open, ready]);

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 112)}px`;
  }, [draft, open]);

  const lastUserMessage = useMemo(
    () => [...items].reverse().find((item) => item.kind === 'user')?.content ?? '',
    [items],
  );

  // react-markdown component overrides that turn "p. 5" / "Fig. 3" / "표 2"
  // style references into clickable citation chips. Only text-bearing block and
  // inline containers are overridden; <a>/<code> keep their defaults so their
  // inner text is never linkified.
  const markdownComponents = useMemo<Components | undefined>(() => {
    if (!onCitationClick) return undefined;
    const wrap =
      (Tag: 'p' | 'li' | 'td' | 'th' | 'strong' | 'em' | 'blockquote' | 'h1' | 'h2' | 'h3' | 'h4') =>
      ({ node: _node, children, ...props }: { node?: unknown; children?: ReactNode }) => (
        <Tag {...props}>{processCitationChildren(children, onCitationClick)}</Tag>
      );
    return {
      p: wrap('p'),
      li: wrap('li'),
      td: wrap('td'),
      th: wrap('th'),
      strong: wrap('strong'),
      em: wrap('em'),
      blockquote: wrap('blockquote'),
      h1: wrap('h1'),
      h2: wrap('h2'),
      h3: wrap('h3'),
      h4: wrap('h4'),
    };
  }, [onCitationClick]);

  const canSend = ready && loadState !== 'loading';
  const enqueue = useCallback((rawText: string) => {
    const text = rawText.trim();
    if (!text || !canSend) return;

    onDraftChange('');
    if (inputRef.current) inputRef.current.style.height = 'auto';
    // 새 질문을 보내면 읽던 위치와 무관하게 대화 끝으로 돌아간다.
    stickToBottomRef.current = true;
    setAtBottom(true);
    setContextOpen(false);
    send(text);
  }, [canSend, onDraftChange, send]);

  const handleSend = useCallback(() => {
    enqueue(draft);
  }, [draft, enqueue]);

  const handleStarter = useCallback((prompt: string) => {
    if (!ready) return;
    onDraftChange(prompt);
    inputRef.current?.focus();
  }, [onDraftChange, ready]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 한글 IME 조합을 확정하는 Enter도 keydown으로 들어온다. 이때 보내면 마지막
    // 글자가 덜 조합된 채 전송되거나 입력창에 남는다.
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend]);


  // Scroll edge effect: the header's border/shadow only appears once content
  // has actually scrolled behind it, not as a permanent hairline.
  const handleMessagesScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    const next = el.scrollTop > 0;
    setScrolled((prev) => (prev === next ? prev : next));
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
    stickToBottomRef.current = bottom;
    setAtBottom((prev) => (prev === bottom ? prev : bottom));
  }, []);

  const scrollToBottom = useCallback(() => {
    const el = messagesRef.current;
    if (!el) return;
    stickToBottomRef.current = true;
    setAtBottom(true);
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, []);

  // Escape는 포커스가 카드 안에 있을 때만 닫는다. window 전역 리스너는 PDF 검색창이나
  // 모달의 Escape까지 가로챘다.
  const closeCard = useCallback((instant: boolean) => {
    if (!open) return;
    restoreFocusRef.current = true;
    setInstantTransition(instant);
    if (instant) setCardMounted(false);
    onToggleOpen();
  }, [open, onToggleOpen]);

  // Escape는 열린 겹(확인 대화상자, 메뉴, 맥락 팝오버)부터 하나씩 닫고, 없으면 카드를 닫는다.
  const handleCardKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Escape' || e.nativeEvent.isComposing) return;
    e.stopPropagation();
    if (confirmDelete) setConfirmDelete(false);
    else if (menuOpen) setMenuOpen(false);
    else if (contextOpen) setContextOpen(false);
    else closeCard(true);
  }, [closeCard, confirmDelete, contextOpen, menuOpen]);

  const toggleContext = useCallback(() => {
    // 출처별 추정값은 마지막 답 기준이라 열 때 새로 읽는다.
    if (!contextOpen) void refresh();
    setContextOpen(!contextOpen);
  }, [contextOpen, refresh]);

  const startNewContext = useCallback(() => {
    setContextOpen(false);
    stickToBottomRef.current = true;
    void reset();
  }, [reset]);

  const confirmRemove = useCallback(() => {
    setConfirmDelete(false);
    setShowOld(false);
    void remove();
  }, [remove]);

  return (
    <div className="pointer-events-none fixed inset-0 z-40">
      <div className="pointer-events-auto absolute bottom-4 right-4 flex items-end justify-end sm:bottom-5 sm:right-5">
        {!cardVisible && (
          <button
            ref={launcherRef}
            type="button"
            onClick={(event) => {
              setInstantTransition(event.detail === 0);
              onToggleOpen();
            }}
            data-expanded={showLauncherIntro || undefined}
            className={`chat-launcher ${ready ? 'chat-launcher-ready' : 'chat-launcher-pending'}`}
            aria-label={
              ready
                ? `${S.chat.launcherOpen}, ${S.chat.statusReady}, ${S.chat.readyHint}`
                : `${S.chat.statusPending}. ${readyMessage}`
            }
            title={ready ? S.chat.launcherOpen : S.chat.pendingHint}
          >
            {/* 런처는 테두리 1px을 포함해 44px이라 안쪽은 42px이다. 오브를 44px로 두면
                1px씩 밀리고 가장자리가 overflow-hidden에 잘린다. */}
            <DiscussionOrb state={ready ? 'ready' : 'pending'} className="h-[42px] w-[42px]" />
            {/* 원형 휴지 상태에서는 overflow-hidden에 가려 보이지 않다가, 첫 ready
                전환 순간에만 data-expanded로 잠깐 드러난다. 접근성 정보는 위 aria-label이
                항상 담당하므로 이 텍스트는 스크린 리더에서 숨긴다. */}
            <span aria-hidden="true" className="min-w-0 text-left">
              <span className="block text-sm font-semibold text-fg">
                {S.workbench.assistant}
              </span>
              <span className="mt-0.5 flex items-center gap-2 text-2xs text-fg-muted">
                <span className="chip-tint chip-tint-success">{S.chat.statusReady}</span>
                <span className="truncate">{S.chat.readyHint}</span>
              </span>
            </span>
          </button>
        )}

        {/* data-expanded: 대화가 시작되면 카드 높이를 최대치로 고정한다(index.css).
            카드가 bottom 고정이라 그러지 않으면 토큰마다 위로 자란다.
            data-state=closed: 닫힘 애니메이션이 끝날 때까지 마운트를 유지한다. */}
        {cardVisible && (
          <div
            className="chat-floating-card relative"
            data-expanded={hasMessages || undefined}
            data-state={open ? 'open' : 'closed'}
            data-instant={instantTransition || undefined}
            onKeyDown={handleCardKeyDown}
            onAnimationEnd={(e) => {
              if (e.target === e.currentTarget && !open) setCardMounted(false);
            }}
          >
            <div className="chat-floating-header" data-scrolled={scrolled || undefined}>
              <div className="flex min-w-0 items-center gap-2">
                <DiscussionOrb
                  state={!ready ? 'pending' : busy ? 'busy' : 'ready'}
                  className="discussion-orb-sm h-4 w-4"
                />
                <span className="shrink-0 text-sm font-semibold text-fg">사수</span>
                {(fieldLabel || agent?.domain_display) && (
                  <span className="truncate text-2xs text-fg-muted">{fieldLabel || agent?.domain_display}</span>
                )}
                {totalCost > 0 && (
                  <span className="shrink-0 text-2xs tabular-nums text-fg-muted" title="이 토의의 누적 비용">
                    ${totalCost.toFixed(4)}
                  </span>
                )}
              </div>

              <div className="flex shrink-0 items-center gap-1">
                {hasMessages && (
                  <div
                    className="relative"
                    onBlur={(e) => {
                      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setMenuOpen(false);
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => setMenuOpen(!menuOpen)}
                      className="btn-icon-subtle"
                      aria-label="토의 메뉴"
                      aria-haspopup="menu"
                      aria-expanded={menuOpen}
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </button>
                    {menuOpen && (
                      <div role="menu" className="absolute right-0 top-9 z-10 w-40 rounded-surface border border-border bg-surface p-1.5 shadow-lg">
                        <button
                          type="button"
                          role="menuitem"
                          disabled={busy}
                          title={busy ? '답변이 끝난 뒤에 삭제할 수 있어요' : undefined}
                          onClick={() => {
                            setMenuOpen(false);
                            setConfirmDelete(true);
                          }}
                          className="flex w-full items-center gap-2 rounded-control px-2.5 py-2 text-xs text-danger hover:bg-surface-hover disabled:opacity-50"
                        >
                          <Trash2 className="h-3.5 w-3.5" /> 토의 삭제
                        </button>
                      </div>
                    )}
                  </div>
                )}
                <button
                  type="button"
                  onClick={(event) => closeCard(event.detail === 0)}
                  className="btn-icon-subtle"
                  aria-label="토의 닫기"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            {!ready ? (
              <div className="flex flex-1 flex-col items-center justify-center px-5 py-8 text-center">
                <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full border border-border/60 bg-bg/70">
                  <MessageSquare className="h-5 w-5 text-fg-muted" />
                </div>
                <p className="text-sm font-medium text-fg">
                  사수가 논문을 읽고 있어요
                </p>
                <p className="mt-2 text-xs leading-relaxed text-fg-muted">
                  {readyMessage}
                </p>
              </div>
            ) : (
              <>
                <div className="relative flex min-h-0 flex-1 flex-col">
                  <div
                    ref={messagesRef}
                    className="flex-1 overflow-y-auto px-4 pb-4 pt-1"
                    onScroll={handleMessagesScroll}
                  >
                    {!hasMessages && loadState === 'loading' ? null : !hasMessages ? (
                      // 추천 질문은 대화를 시작하기 전에만 보인다. 누르면 입력창만 채우고,
                      // 전송(비용 발생)은 사용자가 직접 한다.
                      <div className="chat-empty-state">
                        <p className="text-xs text-fg-secondary">
                          논문을 읽으면서 바로 질문해 보세요.
                        </p>
                        {starters.length > 0 && (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {starters.slice(0, 3).map((prompt) => (
                              <button
                                key={prompt}
                                type="button"
                                onClick={() => handleStarter(prompt)}
                                className="chat-starter-chip"
                              >
                                <Sparkles className="h-3 w-3 shrink-0 text-fg-muted" />
                                {prompt}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {hiddenCount > 0 && (
                          <button
                            type="button"
                            onClick={() => setShowOld(!showOld)}
                            aria-expanded={showOld}
                            className="flex w-full items-center gap-1.5 rounded-control border border-dashed border-border/70 px-3 py-2 text-left text-2xs text-fg-muted hover:bg-surface-hover"
                          >
                            {showOld ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                            이전 맥락의 대화 {hiddenCount}개 {showOld ? '접기' : '보기'}
                          </button>
                        )}
                        {items.slice(visibleFrom).map((item, offset) => {
                          const index = visibleFrom + offset;
                          if (item.kind === 'reset') {
                            return (
                              <div key={item.id} role="note" className="rounded-control border border-accent/20 bg-accent/5 px-3 py-2 text-2xs">
                                <div className="flex items-baseline justify-between gap-2">
                                  <p className="font-semibold text-fg-secondary">
                                    {RESET_TITLE[item.resetReason ?? 'manual']}
                                  </p>
                                  <span className="shrink-0 tabular-nums text-fg-muted">{formatResetTime(item.createdAt)}</span>
                                </div>
                                <p className="mt-0.5 text-fg-muted">이 위의 대화는 사수가 보지 않아요.</p>
                              </div>
                            );
                          }
                          const isUser = item.kind === 'user';
                          // 마지막 맥락 초기화 앞의 대화는 사수에게 가지 않는다.
                          const dim = index < resetAt;
                          const interrupted = item.status === 'interrupted';
                          const showBubble = Boolean(item.content) || item.status === 'streaming' || Boolean(item.error);
                          const showActions =
                            !isUser &&
                            item.status === 'complete' &&
                            index === items.length - 1 &&
                            !busy;

                          return (
                            <div
                              key={item.id}
                              className={`chat-message flex ${isUser ? 'justify-end' : 'justify-start'}`}
                            >
                              {/* chat-message의 fadeIn(fill both)이 opacity를 붙잡으므로 흐림은 안쪽에 건다. */}
                              <div className={`chat-bubble-wrap ${isUser ? 'items-end' : 'chat-bubble-wrap-agent items-start'} ${dim ? 'opacity-40' : ''}`}>
                                {showBubble && (
                                  <div className={`chat-bubble ${isUser ? 'chat-bubble-user' : 'chat-bubble-agent'}`}>
                                    {isUser ? (
                                      <span className="whitespace-pre-wrap">{item.content}</span>
                                    ) : item.content ? (
                                      <Markdown className="chat-markdown" components={markdownComponents}>
                                        {item.content}
                                      </Markdown>
                                    ) : item.status === 'streaming' ? (
                                      <span className="chat-typing" role="status" aria-label="답변을 작성하고 있어요">
                                        <span />
                                        <span />
                                        <span />
                                      </span>
                                    ) : null}
                                    {item.error && (
                                      <p className="text-2xs text-danger">{item.error}</p>
                                    )}
                                  </div>
                                )}
                                {item.status === 'pending' && (
                                  <span className="mt-1 px-1 text-2xs text-fg-muted">대기 중</span>
                                )}
                                {interrupted && (
                                  <span className="mt-1 px-1 text-2xs text-fg-muted" title="중단된 답은 사수에게 다시 보내지 않아요">
                                    중단됨
                                  </span>
                                )}

                                {showActions && (
                                  <div className="chat-follow-actions">
                                    <button
                                      type="button"
                                      onClick={() => enqueue('방금 답변을 핵심만 3줄로 요약해줘.')}
                                      className="chat-follow-chip"
                                    >
                                      요약해서 보기
                                    </button>
                                    {lastUserMessage && (
                                      <button
                                        type="button"
                                        onClick={() => {
                                          onDraftChange(lastUserMessage);
                                          inputRef.current?.focus();
                                        }}
                                        className="chat-follow-chip"
                                      >
                                        다시 물어보기
                                      </button>
                                    )}
                                  </div>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                  {!atBottom && hasMessages && (
                    <button type="button" onClick={scrollToBottom} className="chat-jump-bottom">
                      <ArrowDown className="h-3 w-3" />
                      {busy ? '새 답변 보기' : '맨 아래로'}
                    </button>
                  )}
                </div>

                <div className="relative px-3 pb-3 pt-1">
                  {error && (
                    <p className="mb-2 flex items-center gap-2 px-1 text-2xs text-danger" role="alert">
                      <span className="min-w-0 flex-1 truncate">{error}</span>
                      {loadState === 'error' && (
                        <button type="button" onClick={() => void refresh()} className="shrink-0 text-fg-muted hover:text-fg">
                          다시 시도
                        </button>
                      )}
                    </p>
                  )}
                  {hasMessages && (
                    <div className="mb-2 flex items-center gap-2 px-1 text-2xs text-fg-muted">
                      {context?.context_tokens != null ? (
                        <div
                          className="min-w-0 flex-1"
                          onBlur={(e) => {
                            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setContextOpen(false);
                          }}
                        >
                          <button
                            type="button"
                            onClick={toggleContext}
                            aria-expanded={contextOpen}
                            className="flex w-full min-w-0 items-center gap-2 hover:text-fg-secondary"
                            title="사수가 보는 맥락"
                          >
                            <span className="h-1 w-16 shrink-0 overflow-hidden rounded-full bg-border">
                              <span
                                className="block h-1 rounded-full bg-accent"
                                style={{ width: `${Math.min(100, Math.max(3, (context.context_tokens / context.budget) * 100))}%` }}
                              />
                            </span>
                            <span className="truncate tabular-nums">
                              맥락 {formatTokens(context.context_tokens)} / {formatTokens(context.budget)} 토큰
                            </span>
                          </button>
                          {contextOpen && (
                            <div className="absolute bottom-full left-3 right-3 z-10 mb-1 space-y-1.5 rounded-surface border border-border bg-surface p-3 text-2xs shadow-lg">
                              <p className="mb-1 font-semibold text-fg-secondary">사수가 보는 맥락 (토큰, 추정)</p>
                              {context.sources.map((source) => (
                                <div key={source.key} className="flex items-center gap-2">
                                  <span className="text-fg-secondary">{source.label}</span>
                                  {source.truncated && <span className="text-fg-muted">앞 3,000자만</span>}
                                  <span className="ml-auto tabular-nums text-fg-muted">
                                    {source.estimated_tokens != null ? `약 ${formatTokens(source.estimated_tokens)}` : ''}
                                  </span>
                                </div>
                              ))}
                              <p className="border-t border-border/50 pt-1.5 text-fg-muted">
                                직전 답의 실제 입력은 {formatTokens(context.context_tokens)} 토큰이에요. 이전 맥락의 대화와 중단된 답은 보내지 않아요.
                              </p>
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="flex-1" />
                      )}
                      <button
                        type="button"
                        onClick={startNewContext}
                        disabled={!canReset}
                        className="inline-flex shrink-0 items-center gap-1 hover:text-fg disabled:opacity-50 disabled:hover:text-fg-muted"
                        title="기록은 남기고, 이후 대화만 사수에게 보내요"
                      >
                        <RotateCcw className="h-3 w-3" /> 새 맥락
                      </button>
                    </div>
                  )}
                  <div className="chat-composer">
                    <textarea
                      ref={inputRef}
                      value={draft}
                      onChange={(e) => onDraftChange(e.target.value)}
                      onKeyDown={handleKeyDown}
                      rows={1}
                      disabled={!ready}
                      aria-label="질문 입력"
                      placeholder={busy ? '답변 중에도 이어서 질문할 수 있어요' : '질문을 입력하세요 (Shift+Enter 줄바꿈)'}
                      className="chat-composer-input"
                    />
                    {busy && (
                      <button
                        type="button"
                        onClick={stop}
                        className="chat-stop-button"
                        aria-label="답변 중지"
                        title="답변 중지"
                      >
                        <Square className="h-3 w-3 fill-current" />
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={handleSend}
                      disabled={!draft.trim() || !canSend}
                      className="chat-send-button"
                      aria-label="질문 보내기"
                    >
                      <Send className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </>
            )}

            {confirmDelete && (
              <div className="absolute inset-0 z-20 flex items-center justify-center bg-bg/70 p-6 backdrop-blur-sm">
                <div
                  role="alertdialog"
                  aria-modal="true"
                  aria-labelledby="discussion-delete-title"
                  aria-describedby="discussion-delete-desc"
                  className="w-full rounded-surface border border-border bg-surface p-4 text-xs shadow-xl"
                >
                  <p id="discussion-delete-title" className="text-sm font-semibold text-fg">토의를 삭제할까요?</p>
                  <p id="discussion-delete-desc" className="mt-1.5 text-fg-muted">
                    이 논문의 토의 기록이 모두 지워지고 되돌릴 수 없어요. 주제만 바꾸려면 새 맥락을 쓰세요.
                  </p>
                  <div className="mt-4 flex justify-end gap-2">
                    <button ref={confirmCancelRef} type="button" onClick={() => setConfirmDelete(false)} className="btn px-3 py-1.5 text-xs">
                      취소
                    </button>
                    <button type="button" onClick={confirmRemove} className="btn border-danger/30 bg-danger/10 px-3 py-1.5 text-xs text-danger">
                      삭제
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
