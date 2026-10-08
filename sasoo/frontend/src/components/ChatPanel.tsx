import { Children, useState, useRef, useEffect, useCallback, useMemo, type ReactNode } from 'react';
import {
  ArrowDown,
  MessageSquare,
  Send,
  Sparkles,
  Square,
  Trash2,
  X,
} from 'lucide-react';
import { type Components } from 'react-markdown';
import { Markdown } from '@/components/Markdown';
import { chatWithAgent, type ChatDoneMeta, type ChatMessage } from '@/lib/api';
import { createTokenBuffer } from '@/lib/tokenBuffer';
import { withRoJosa } from '@/lib/josa';
import { getAgentMeta } from '@/lib/agents';
import { detectCitations, type CitationType } from '@/lib/citations';
import { S } from '@/lib/strings';

// 런처가 원형으로 접힌 채 유지되는 기본 시간(첫 ready 전환 시 확장 카드를 보여주는 시간).
const LAUNCHER_INTRO_MS = 3000;

// Tokens are routed to their own bubble by id, so two turns can never bleed
// into each other the way appending to the tail of the array would.
let messageSeq = 0;
const nextMessageId = () => `msg-${(messageSeq += 1)}`;

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
  open,
  ready,
  readyMessage,
  draft,
  starters,
  onToggleOpen,
  onDraftChange,
  onCitationClick,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [totalCost, setTotalCost] = useState(0);
  const [scrolled, setScrolled] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const stickToBottomRef = useRef(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef(false);
  const [instantTransition, setInstantTransition] = useState(false);
  const messagesRef = useRef<HTMLDivElement>(null);
  // Aborts the turn currently on the wire; queued turns have not started yet.
  const abortRef = useRef<AbortController | null>(null);
  const runningRef = useRef(false);

  const agent = agentName ? getAgentMeta(agentName) : null;
  const hasMessages = messages.length > 0;
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
  const busy = messages.some((msg) => msg.status === 'pending' || msg.status === 'streaming');

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
    abortRef.current?.abort();
    abortRef.current = null;
    runningRef.current = false;
    setMessages([]);
    setTotalCost(0);
    setScrolled(false);
    setAtBottom(true);
    stickToBottomRef.current = true;
  }, [paperId]);

  useEffect(() => () => abortRef.current?.abort(), []);

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
  }, [messages, open]);

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
    () => [...messages].reverse().find((msg) => msg.role === 'user')?.content ?? '',
    [messages],
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

  // Runs one queued question to completion. Turns are serialized so each one
  // sees the previous answer in its history; the composer stays open regardless.
  const runTurn = useCallback(async (pending: ChatMessage, snapshot: ChatMessage[]) => {
    runningRef.current = true;
    const agentId = nextMessageId();
    const controller = new AbortController();
    abortRef.current = controller;

    // `pending` is deliberately excluded: the backend appends the question as
    // the final user turn, so including it here would send it to Gemini twice.
    const history = snapshot
      .slice(0, snapshot.indexOf(pending))
      .filter((msg) => msg.status === 'done' && msg.content.trim().length > 0);

    setMessages((prev) => [
      ...prev.map((msg) => (msg.id === pending.id ? { ...msg, status: 'done' as const } : msg)),
      { id: agentId, role: 'agent' as const, content: '', status: 'streaming' as const },
    ]);

    // Tokens are batched so each SSE token doesn't re-render the whole
    // message list; the buffer is drained before any status transition so a
    // bubble never turns 'done' or 'error' with text still in flight.
    const tokenBuffer = createTokenBuffer((chunk) => {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === agentId ? { ...msg, content: msg.content + chunk } : msg,
        ),
      );
    });

    try {
      await chatWithAgent(
        paperId,
        pending.content,
        history,
        (token) => tokenBuffer.push(token),
        (meta: ChatDoneMeta) => {
          tokenBuffer.end();
          setTotalCost((prev) => prev + meta.cost_usd);
          setMessages((prev) =>
            prev.map((msg) => (msg.id === agentId ? { ...msg, status: 'done' as const } : msg)),
          );
        },
        controller.signal,
      );
    } catch (err) {
      tokenBuffer.end();
      const stopped = controller.signal.aborted;
      const detail = err instanceof Error ? err.message : '답변을 받지 못했어요.';
      setMessages((prev) =>
        prev.map((msg) => {
          if (msg.id !== agentId) return msg;
          if (stopped) return { ...msg, status: 'done' as const };
          return { ...msg, status: 'error' as const, error: detail };
        }),
      );
    } finally {
      tokenBuffer.end();
      // A stream that ends without a `done` frame would otherwise stay
      // 'streaming' forever and wedge the queue.
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === agentId && msg.status === 'streaming'
            ? { ...msg, status: 'error' as const, error: '응답이 중간에 끊겼어요.' }
            : msg,
        ),
      );
      if (abortRef.current === controller) abortRef.current = null;
      runningRef.current = false;
    }
  }, [paperId]);

  // Drains the queue: picks up the next pending question whenever one is idle.
  useEffect(() => {
    if (runningRef.current) return;
    const pending = messages.find((msg) => msg.role === 'user' && msg.status === 'pending');
    if (!pending) return;
    void runTurn(pending, messages);
  }, [messages, runTurn]);

  const enqueue = useCallback((rawText: string) => {
    const text = rawText.trim();
    if (!text || !ready) return;

    onDraftChange('');
    if (inputRef.current) inputRef.current.style.height = 'auto';
    // 새 질문을 보내면 읽던 위치와 무관하게 대화 끝으로 돌아간다.
    stickToBottomRef.current = true;
    setAtBottom(true);
    setMessages((prev) => [
      ...prev,
      { id: nextMessageId(), role: 'user' as const, content: text, status: 'pending' as const },
    ]);
  }, [onDraftChange, ready]);

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

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
  }, []);

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

  const handleCardKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape' && !e.nativeEvent.isComposing) {
      e.stopPropagation();
      closeCard(true);
    }
  }, [closeCard]);

  const clearConversation = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    runningRef.current = false;
    setMessages([]);
    setTotalCost(0);
  }, []);

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
            className="chat-floating-card"
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
                <span className="truncate text-sm font-semibold text-fg">
                  {agent?.display_name_ko || '질문 도우미'}
                </span>
                {totalCost > 0 && (
                  <span className="shrink-0 text-2xs tabular-nums text-fg-muted" title="이 대화의 누적 비용">
                    ${totalCost.toFixed(4)}
                  </span>
                )}
              </div>

              <div className="flex shrink-0 items-center gap-1">
                {hasMessages && (
                  <button
                    type="button"
                    onClick={clearConversation}
                    className="btn-icon-subtle"
                    aria-label="대화 초기화"
                    title="대화 초기화"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
                <button
                  type="button"
                  onClick={(event) => closeCard(event.detail === 0)}
                  className="btn-icon-subtle"
                  aria-label="질문 도우미 닫기"
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
                  질문 도우미를 준비하고 있어요
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
                    {!hasMessages ? (
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
                        {messages.map((msg, index) => {
                          const isUser = msg.role === 'user';
                          const showActions =
                            !isUser &&
                            msg.status === 'done' &&
                            index === messages.length - 1 &&
                            !busy;

                          return (
                            <div
                              key={msg.id}
                              className={`chat-message flex ${isUser ? 'justify-end' : 'justify-start'}`}
                            >
                              <div className={`chat-bubble-wrap ${isUser ? 'items-end' : 'chat-bubble-wrap-agent items-start'}`}>
                                <div className={`chat-bubble ${isUser ? 'chat-bubble-user' : 'chat-bubble-agent'}`}>
                                  {isUser ? (
                                    <span className="whitespace-pre-wrap">{msg.content}</span>
                                  ) : msg.content ? (
                                    <Markdown className="chat-markdown" components={markdownComponents}>
                                      {msg.content}
                                    </Markdown>
                                  ) : msg.status === 'streaming' ? (
                                    <span className="chat-typing" role="status" aria-label="답변을 작성하고 있어요">
                                      <span />
                                      <span />
                                      <span />
                                    </span>
                                  ) : null}
                                  {msg.status === 'error' && (
                                    <p className="text-2xs text-danger">
                                      {msg.error || '답변을 받지 못했어요.'}
                                    </p>
                                  )}
                                </div>
                                {msg.status === 'pending' && (
                                  <span className="mt-1 px-1 text-2xs text-fg-muted">대기 중</span>
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

                <div className="px-3 pb-3 pt-1">
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
                        onClick={stopStreaming}
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
                      disabled={!draft.trim() || !ready}
                      className="chat-send-button"
                      aria-label="질문 보내기"
                    >
                      <Send className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
