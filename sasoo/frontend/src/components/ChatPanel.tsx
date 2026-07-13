import { Children, useState, useRef, useEffect, useCallback, useMemo, type ReactNode } from 'react';
import {
  Bot,
  MessageSquare,
  Send,
  Sparkles,
  Square,
  Trash2,
  User,
  X,
} from 'lucide-react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import { chatWithAgent, type ChatDoneMeta, type ChatMessage } from '@/lib/api';
import { createTokenBuffer } from '@/lib/tokenBuffer';
import { getAgentMeta } from '@/lib/agents';
import { detectCitations, type CitationType } from '@/lib/citations';

const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [rehypeKatex];

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
        title={`${match.raw}로 이동`}
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
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // Aborts the turn currently on the wire; queued turns have not started yet.
  const abortRef = useRef<AbortController | null>(null);
  const runningRef = useRef(false);

  const agent = agentName ? getAgentMeta(agentName) : null;
  const agentColor = agent?.color || '#5e6ad2';
  const hasMessages = messages.length > 0;
  const busy = messages.some((msg) => msg.status === 'pending' || msg.status === 'streaming');

  useEffect(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    runningRef.current = false;
    setMessages([]);
    setTotalCost(0);
    setScrolled(false);
  }, [paperId]);

  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    if (!open) return;
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
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

  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onToggleOpen();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onToggleOpen]);

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
    if (e.key === 'Enter' && !e.shiftKey) {
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
    const next = e.currentTarget.scrollTop > 0;
    setScrolled((prev) => (prev === next ? prev : next));
  }, []);

  const clearConversation = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    runningRef.current = false;
    setMessages([]);
    setTotalCost(0);
  }, []);

  return (
    <div className="pointer-events-none fixed inset-0 z-40">
      {open && (
        <button
          type="button"
          onClick={onToggleOpen}
          className="chat-floating-backdrop pointer-events-auto"
          aria-label="질문 도우미 닫기"
        />
      )}

      <div className="pointer-events-auto absolute bottom-4 right-4 flex items-end justify-end sm:bottom-5 sm:right-5">
        {!open && (
          <button
            type="button"
            onClick={onToggleOpen}
            className={`chat-launcher ${ready ? 'chat-launcher-ready' : 'chat-launcher-pending'}`}
            aria-label={ready ? '질문 도우미 열기' : readyMessage}
            title={ready ? '질문 도우미 열기' : readyMessage}
          >
            <span
              className="flex h-11 w-11 items-center justify-center rounded-full"
              style={{ backgroundColor: ready ? `${agentColor}20` : 'rgb(var(--fg-muted) / 0.2)' }}
            >
              <Bot className="h-5 w-5" style={ready ? { color: agentColor } : undefined} />
            </span>
            <span className="min-w-0 text-left">
              <span className="block text-sm font-semibold text-fg">
                질문 도우미
              </span>
              <span className="mt-0.5 flex items-center gap-2 text-2xs text-fg-muted">
                <span className={`chat-launcher-badge ${ready ? 'chat-launcher-badge-ready' : 'chat-launcher-badge-pending'}`}>
                  {ready ? '준비됨' : '대기'}
                </span>
                <span className="truncate">{ready ? '논문 맥락으로 바로 질문해요' : 'PDF 텍스트를 읽고 있어요'}</span>
              </span>
            </span>
          </button>
        )}

        {open && (
          <div className="chat-floating-card">
            <div className="chat-floating-header" data-scrolled={scrolled || undefined}>
              <div className="min-w-0">
                <div className="mb-1 flex items-center gap-2">
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: ready ? agentColor : 'rgb(var(--fg-muted))' }}
                  />
                  <span className="truncate text-sm font-semibold text-fg">
                    {agent?.display_name_ko || '질문 도우미'}
                  </span>
                  <span className={`chat-launcher-badge ${ready ? 'chat-launcher-badge-ready' : 'chat-launcher-badge-pending'}`}>
                    {ready ? '준비됨' : '대기'}
                  </span>
                </div>
                <p className="text-2xs text-fg-muted">
                  {ready ? '현재 논문 맥락을 유지한 채 질문을 이어갈 수 있어요.' : readyMessage}
                </p>
              </div>

              <button
                type="button"
                onClick={onToggleOpen}
                className="btn-icon-subtle shrink-0"
                aria-label="질문 도우미 닫기"
              >
                <X className="h-4 w-4" />
              </button>
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
                <div className="border-b border-border/45 px-4 py-3">
                  <div className="mb-2 flex items-center gap-2 text-2xs uppercase tracking-[0.16em] text-fg-muted">
                    <Sparkles className="h-3 w-3" />
                    추천 질문
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {starters.slice(0, 3).map((prompt) => (
                      <button
                        key={prompt}
                        type="button"
                        onClick={() => handleStarter(prompt)}
                        className="chat-starter-chip"
                      >
                        {prompt}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto px-4 py-4" onScroll={handleMessagesScroll}>
                  {!hasMessages && (
                    <div className="chat-empty-state">
                      <div className="chat-empty-icon">
                        <MessageSquare className="h-4 w-4 text-fg-muted" />
                      </div>
                      <div>
                        <p className="text-xs text-fg-secondary">논문을 읽으면서 바로 질문해 보세요.</p>
                        <p className="mt-1 text-2xs text-fg-muted">
                          핵심 기여, Figure 해석, 재현 리스크처럼 작업형 질문에 최적화했어요.
                        </p>
                      </div>
                    </div>
                  )}

                  <div className="space-y-4">
                    {messages.map((msg, index) => {
                      const isStreaming = msg.status === 'streaming';
                      const showActions =
                        msg.role === 'agent' &&
                        msg.status === 'done' &&
                        index === messages.length - 1 &&
                        !busy;

                      return (
                        <div
                          key={msg.id}
                          className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                        >
                          <div className={`chat-bubble-wrap ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                            <div className="mb-1 flex items-center gap-1.5 px-1 text-2xs text-fg-muted">
                              {msg.role === 'agent' ? (
                                <>
                                  <span
                                    className="flex h-5 w-5 items-center justify-center rounded-full border border-border/55"
                                    style={{ backgroundColor: `${agentColor}20` }}
                                  >
                                    <Bot className="h-3 w-3" style={{ color: agentColor }} />
                                  </span>
                                  <span>{agent?.display_name_ko || '에이전트'}</span>
                                </>
                              ) : (
                                <>
                                  {msg.status === 'pending' && <span>대기 중</span>}
                                  <span>나</span>
                                  <span className="flex h-5 w-5 items-center justify-center rounded-full border border-border/55 bg-surface/90">
                                    <User className="h-3 w-3 text-fg-muted" />
                                  </span>
                                </>
                              )}
                            </div>
                            <div className={`chat-bubble ${msg.role === 'user' ? 'chat-bubble-user' : 'chat-bubble-agent'}`}>
                              {msg.role === 'agent' ? (
                                <>
                                  {isStreaming ? (
                                    <span className="whitespace-pre-wrap">{msg.content}</span>
                                  ) : (
                                    <ReactMarkdown
                                      className="chat-markdown"
                                      remarkPlugins={REMARK_PLUGINS}
                                      rehypePlugins={REHYPE_PLUGINS}
                                      components={markdownComponents}
                                    >
                                      {msg.content}
                                    </ReactMarkdown>
                                  )}
                                  {isStreaming && (
                                    <span className="ml-1 inline-block h-3.5 w-1.5 animate-pulse bg-accent align-middle" />
                                  )}
                                  {msg.status === 'error' && (
                                    <p className="text-2xs text-danger">
                                      {msg.error || '답변을 받지 못했어요.'}
                                    </p>
                                  )}
                                </>
                              ) : (
                                <span className="whitespace-pre-wrap">{msg.content}</span>
                              )}
                            </div>

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
                  <div ref={messagesEndRef} />
                </div>

                <div className="border-t border-border/45 px-4 py-3">
                  <div className="mb-2 flex items-center justify-between gap-3 text-2xs text-fg-muted">
                    <span>{totalCost > 0 ? `누적 비용 $${totalCost.toFixed(4)}` : '답변이 끝나면 대화 비용을 확인할 수 있어요.'}</span>
                    <div className="flex items-center gap-3">
                      {busy && (
                        <button
                          type="button"
                          onClick={stopStreaming}
                          className="inline-flex items-center gap-1 text-fg-muted transition-colors hover:text-fg-secondary"
                        >
                          <Square className="h-3 w-3" />
                          답변 중지
                        </button>
                      )}
                      {hasMessages && (
                        <button
                          type="button"
                          onClick={clearConversation}
                          className="inline-flex items-center gap-1 text-fg-muted transition-colors hover:text-fg-secondary"
                        >
                          <Trash2 className="h-3 w-3" />
                          대화 초기화
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="chat-composer">
                    <textarea
                      ref={inputRef}
                      value={draft}
                      onChange={(e) => onDraftChange(e.target.value)}
                      onKeyDown={handleKeyDown}
                      rows={1}
                      disabled={!ready}
                      placeholder={
                        busy
                          ? '답변 중에도 질문을 이어서 보낼 수 있어요...'
                          : '질문을 입력하세요... (Shift+Enter 줄바꿈)'
                      }
                      className="chat-composer-input"
                    />
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
