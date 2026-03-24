import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import {
  Bot,
  MessageSquare,
  Send,
  Sparkles,
  Trash2,
  User,
  X,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import { chatWithAgent, type ChatDoneMeta, type ChatMessage } from '@/lib/api';
import { getAgentMeta } from '@/lib/agents';

const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [rehypeKatex];

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
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [totalCost, setTotalCost] = useState(0);
  const [activeActionsIndex, setActiveActionsIndex] = useState<number | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const agent = agentName ? getAgentMeta(agentName) : null;
  const agentColor = agent?.color || '#0a84ff';
  const hasMessages = messages.length > 0;

  useEffect(() => {
    setMessages([]);
    setError(null);
    setTotalCost(0);
    setActiveActionsIndex(null);
  }, [paperId]);

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

  const sendText = useCallback(async (rawText: string) => {
    const text = rawText.trim();
    if (!text || streaming || !ready) return;

    onDraftChange('');
    setError(null);
    setActiveActionsIndex(null);
    if (inputRef.current) inputRef.current.style.height = 'auto';

    const userMsg: ChatMessage = { role: 'user', content: text };
    const agentMsg: ChatMessage = { role: 'agent', content: '' };
    setMessages((prev) => [...prev, userMsg, agentMsg]);
    setStreaming(true);

    try {
      const history = [...messages, userMsg];

      await chatWithAgent(
        paperId,
        text,
        history,
        (token) => {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === 'agent') {
              updated[updated.length - 1] = {
                ...last,
                content: last.content + token,
              };
            }
            return updated;
          });
        },
        (meta: ChatDoneMeta) => {
          setTotalCost((prev) => prev + meta.cost_usd);
          setActiveActionsIndex((current) => current ?? messages.length + 1);
        },
        (errMsg) => {
          setError(errMsg);
        },
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Chat failed');
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last?.role === 'agent' && !last.content) return prev.slice(0, -1);
        return prev;
      });
    } finally {
      setStreaming(false);
    }
  }, [messages, onDraftChange, paperId, ready, streaming]);

  const handleSend = useCallback(async () => {
    await sendText(draft);
  }, [draft, sendText]);

  const handleStarter = useCallback((prompt: string) => {
    if (!ready) return;
    onDraftChange(prompt);
    inputRef.current?.focus();
  }, [onDraftChange, ready]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  }, [handleSend]);

  const clearConversation = useCallback(() => {
    if (streaming) return;
    setMessages([]);
    setError(null);
    setTotalCost(0);
    setActiveActionsIndex(null);
  }, [streaming]);

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
              style={{ backgroundColor: ready ? `${agentColor}20` : 'rgba(71, 85, 105, 0.2)' }}
            >
              <Bot className="h-5 w-5" style={ready ? { color: agentColor } : undefined} />
            </span>
            <span className="min-w-0 text-left">
              <span className="block text-sm font-semibold text-surface-100">
                질문 도우미
              </span>
              <span className="mt-0.5 flex items-center gap-2 text-2xs text-surface-400">
                <span className={`chat-launcher-badge ${ready ? 'chat-launcher-badge-ready' : 'chat-launcher-badge-pending'}`}>
                  {ready ? '준비됨' : '대기'}
                </span>
                <span className="truncate">{ready ? '논문 맥락으로 바로 질문' : '스크리닝 후 답변 준비'}</span>
              </span>
            </span>
          </button>
        )}

        {open && (
          <div className="chat-floating-card">
            <div className="chat-floating-header">
              <div className="min-w-0">
                <div className="mb-1 flex items-center gap-2">
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: ready ? agentColor : '#64748b' }}
                  />
                  <span className="truncate text-sm font-semibold text-surface-100">
                    {agent?.display_name_ko || '질문 도우미'}
                  </span>
                  <span className={`chat-launcher-badge ${ready ? 'chat-launcher-badge-ready' : 'chat-launcher-badge-pending'}`}>
                    {ready ? '준비됨' : '대기'}
                  </span>
                </div>
                <p className="text-2xs text-surface-500">
                  {ready ? '현재 논문 맥락을 유지한 채 질문을 이어갈 수 있습니다.' : readyMessage}
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
                <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full border border-surface-700/60 bg-surface-900/70">
                  <MessageSquare className="h-5 w-5 text-surface-500" />
                </div>
                <p className="text-sm font-medium text-surface-200">
                  질문 도우미 준비 중
                </p>
                <p className="mt-2 text-xs leading-relaxed text-surface-500">
                  {readyMessage}
                </p>
              </div>
            ) : (
              <>
                <div className="border-b border-surface-700/45 px-4 py-3">
                  <div className="mb-2 flex items-center gap-2 text-2xs uppercase tracking-[0.16em] text-surface-500">
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

                <div className="flex-1 overflow-y-auto px-4 py-4">
                  {!hasMessages && (
                    <div className="chat-empty-state">
                      <div className="chat-empty-icon">
                        <MessageSquare className="h-4 w-4 text-surface-500" />
                      </div>
                      <div>
                        <p className="text-xs text-surface-300">논문을 읽으면서 바로 질문해 보세요.</p>
                        <p className="mt-1 text-2xs text-surface-500">
                          핵심 기여, Figure 해석, 재현 리스크처럼 작업형 질문에 최적화되어 있습니다.
                        </p>
                      </div>
                    </div>
                  )}

                  <div className="space-y-4">
                    {messages.map((msg, index) => {
                      const isLatestAgentMessage = msg.role === 'agent' && index === messages.length - 1 && !streaming;
                      const showActions = isLatestAgentMessage && (activeActionsIndex === null || activeActionsIndex === index);

                      return (
                        <div
                          key={`${msg.role}-${index}`}
                          className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                        >
                          <div className={`chat-bubble-wrap ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                            <div className="mb-1 flex items-center gap-1.5 px-1 text-2xs text-surface-500">
                              {msg.role === 'agent' ? (
                                <>
                                  <span
                                    className="flex h-5 w-5 items-center justify-center rounded-full border border-surface-700/55"
                                    style={{ backgroundColor: `${agentColor}20` }}
                                  >
                                    <Bot className="h-3 w-3" style={{ color: agentColor }} />
                                  </span>
                                  <span>{agent?.display_name_ko || '에이전트'}</span>
                                </>
                              ) : (
                                <>
                                  <span>나</span>
                                  <span className="flex h-5 w-5 items-center justify-center rounded-full border border-surface-700/55 bg-surface-800/90">
                                    <User className="h-3 w-3 text-surface-400" />
                                  </span>
                                </>
                              )}
                            </div>
                            <div className={`chat-bubble ${msg.role === 'user' ? 'chat-bubble-user' : 'chat-bubble-agent'}`}>
                              {msg.role === 'agent' ? (
                                <>
                                  {streaming && index === messages.length - 1 ? (
                                    <span className="whitespace-pre-wrap">{msg.content}</span>
                                  ) : (
                                    <ReactMarkdown
                                      className="chat-markdown"
                                      remarkPlugins={REMARK_PLUGINS}
                                      rehypePlugins={REHYPE_PLUGINS}
                                    >
                                      {msg.content}
                                    </ReactMarkdown>
                                  )}
                                  {streaming && index === messages.length - 1 && (
                                    <span className="ml-1 inline-block h-3.5 w-1.5 animate-pulse bg-primary-400 align-middle" />
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
                                  onClick={() => void sendText('방금 답변을 핵심만 3줄로 요약해줘.')}
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

                {error && (
                  <div className="border-t border-surface-700/45 px-4 py-2 text-2xs text-red-400">
                    {error}
                  </div>
                )}

                <div className="border-t border-surface-700/45 px-4 py-3">
                  <div className="mb-2 flex items-center justify-between gap-3 text-2xs text-surface-500">
                    <span>{totalCost > 0 ? `누적 비용 $${totalCost.toFixed(4)}` : '대화 비용은 응답 후 집계됩니다.'}</span>
                    {hasMessages && (
                      <button
                        type="button"
                        onClick={clearConversation}
                        disabled={streaming}
                        className="inline-flex items-center gap-1 text-surface-500 transition-colors hover:text-surface-300 disabled:opacity-40"
                      >
                        <Trash2 className="h-3 w-3" />
                        대화 초기화
                      </button>
                    )}
                  </div>
                  <div className="chat-composer">
                    <textarea
                      ref={inputRef}
                      value={draft}
                      onChange={(e) => onDraftChange(e.target.value)}
                      onKeyDown={handleKeyDown}
                      rows={1}
                      disabled={streaming || !ready}
                      placeholder="질문을 입력하세요... (Shift+Enter 줄바꿈)"
                      className="chat-composer-input"
                    />
                    <button
                      type="button"
                      onClick={() => void handleSend()}
                      disabled={!draft.trim() || streaming || !ready}
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
