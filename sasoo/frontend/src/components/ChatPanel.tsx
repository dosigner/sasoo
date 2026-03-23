import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import {
  Bot,
  ChevronDown,
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
  minimized: boolean;
  draft: string;
  starters: string[];
  onClose: () => void;
  onToggleMinimized: () => void;
  onDraftChange: (value: string) => void;
}

export default function ChatPanel({
  paperId,
  agentName,
  open,
  minimized,
  draft,
  starters,
  onClose,
  onToggleMinimized,
  onDraftChange,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [totalCost, setTotalCost] = useState(0);
  const [activeActionsIndex, setActiveActionsIndex] = useState<number | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const sheetRef = useRef<HTMLElement>(null);

  const agent = agentName ? getAgentMeta(agentName) : null;
  const agentColor = agent?.color || '#0a84ff';
  const hasMessages = messages.length > 0;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, open, minimized]);

  useEffect(() => {
    if (!open || minimized) return;
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open, minimized]);

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 112)}px`;
  }, [draft, open]);

  useEffect(() => {
    if (!open || minimized) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (!sheetRef.current) return;
      const target = event.target;
      if (
        target instanceof Element &&
        target.closest('[data-chat-launcher="true"]')
      ) {
        return;
      }
      if (target instanceof Node && !sheetRef.current.contains(target)) {
        onClose();
      }
    };

    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, [minimized, onClose, open]);

  const lastUserMessage = useMemo(
    () => [...messages].reverse().find((msg) => msg.role === 'user')?.content ?? '',
    [messages],
  );

  const sendText = useCallback(async (rawText: string) => {
    const text = rawText.trim();
    if (!text || streaming) return;

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
  }, [draft, messages, onDraftChange, paperId, streaming]);

  const handleSend = useCallback(async () => {
    await sendText(draft);
  }, [draft, sendText]);

  const handleStarter = useCallback((prompt: string) => {
    onDraftChange(prompt);
    inputRef.current?.focus();
  }, [onDraftChange]);

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

  if (!open || typeof document === 'undefined') {
    return null;
  }

  return createPortal(
    <div className={`chat-sheet-shell ${open ? 'chat-sheet-shell-open' : ''}`}>
      <div className={`chat-sheet-scrim ${open ? 'chat-sheet-scrim-open' : ''}`} aria-hidden="true" />
      <div className={`chat-sheet-backdrop ${open ? 'chat-sheet-backdrop-open' : ''}`} aria-hidden="true" />
      <aside
        ref={sheetRef}
        className={`chat-sheet ${open ? 'chat-sheet-open' : ''} ${minimized ? 'chat-sheet-minimized' : ''}`}
      >
        <div className="chat-sheet-header">
          <div className="min-w-0">
            <div className="mb-1 flex items-center gap-2">
              <span
                className="h-2 w-2 rounded-full shrink-0"
                style={{ backgroundColor: agentColor }}
              />
              <span className="truncate text-sm font-semibold text-surface-100">
                {agent?.display_name_ko || '에이전트 질의'}
              </span>
            </div>
            <p className="truncate text-2xs text-surface-500">
              현재 논문 맥락을 유지한 채 오른쪽에서 빠르게 질문할 수 있습니다.
            </p>
          </div>
          <div className="flex items-center gap-1.5">
            <button type="button" onClick={onToggleMinimized} className="btn-icon-subtle" aria-label="최소화">
              <ChevronDown className={`h-4 w-4 transition-transform ${minimized ? '-rotate-90' : ''}`} />
            </button>
            <button type="button" onClick={onClose} className="btn-icon-subtle" aria-label="닫기">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {!minimized && (
          <>
            <div className="border-b border-surface-700/45 px-4 py-3">
              <div className="mb-2 flex items-center gap-2 text-2xs uppercase tracking-[0.16em] text-surface-500">
                <Sparkles className="h-3 w-3" />
                Suggested prompts
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
                      핵심 기여, figure 해석, 재현 리스크처럼 작업형 질문에 최적화되어 있습니다.
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
              <div className="mb-2 flex items-center justify-between text-2xs text-surface-500">
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
                  disabled={streaming}
                  placeholder="질문을 입력하세요... (Shift+Enter 줄바꿈)"
                  className="chat-composer-input"
                />
                <button
                  type="button"
                  onClick={() => void handleSend()}
                  disabled={!draft.trim() || streaming}
                  className="chat-send-button"
                  aria-label="질문 보내기"
                >
                  <Send className="h-4 w-4" />
                </button>
              </div>
            </div>
          </>
        )}
      </aside>
    </div>,
    document.body,
  );
}
