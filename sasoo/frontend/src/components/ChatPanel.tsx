import { useState, useRef, useEffect, useCallback } from 'react';
import {
  MessageSquare,
  Send,
  Loader2,
  AlertCircle,
  User,
  Bot,
  Trash2,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import { chatWithAgent, type ChatMessage, type ChatDoneMeta } from '@/lib/api';
import { getAgentMeta } from '@/lib/agents';

const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [rehypeKatex];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ChatPanelProps {
  paperId: string;
  agentName?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ChatPanel({ paperId, agentName }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [totalCost, setTotalCost] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const agent = agentName ? getAgentMeta(agentName) : null;
  const agentColor = agent?.color || '#6366f1';

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Auto-resize textarea
  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 80) + 'px';
  }, []);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    setInput('');
    setError(null);
    if (inputRef.current) inputRef.current.style.height = 'auto';

    // Add user message
    const userMsg: ChatMessage = { role: 'user', content: text };
    // Add empty agent message placeholder for streaming
    const agentMsg: ChatMessage = { role: 'agent', content: '' };
    setMessages((prev) => [...prev, userMsg, agentMsg]);
    setStreaming(true);

    try {
      const history = [...messages, userMsg];

      await chatWithAgent(
        paperId,
        text,
        history,
        // onToken
        (token) => {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === 'agent') {
              updated[updated.length - 1] = {
                ...last,
                content: last.content + token,
              };
            }
            return updated;
          });
        },
        // onDone
        (meta: ChatDoneMeta) => {
          setTotalCost((prev) => prev + meta.cost_usd);
        },
        // onError
        (errMsg) => {
          setError(errMsg);
        },
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Chat failed');
      // Remove empty agent message on error
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last.role === 'agent' && !last.content) {
          return prev.slice(0, -1);
        }
        return prev;
      });
    } finally {
      setStreaming(false);
    }
  }, [input, streaming, messages, paperId]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleClear = () => {
    if (streaming) return;
    setMessages([]);
    setTotalCost(0);
    setError(null);
  };

  return (
    <div className="flex flex-col">
      {/* Messages area */}
      <div className="space-y-2.5 py-2 min-h-[120px] max-h-[400px] overflow-y-auto">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <MessageSquare className="w-8 h-8 text-surface-500 mb-2" />
            <p className="text-xs text-surface-400">
              논문에 대해 궁금한 점을 물어보세요.
            </p>
            <p className="text-xs text-surface-500 mt-1">
              분석 결과를 바탕으로{' '}
              <span style={{ color: agentColor }}>
                {agent?.display_name_ko || '에이전트'}
              </span>
              가 답변합니다.
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex gap-2 ${
              msg.role === 'user' ? 'justify-end' : 'justify-start'
            }`}
          >
            {msg.role === 'agent' && (
              <div
                className="w-6 h-6 rounded-full flex items-center justify-center shrink-0 mt-0.5"
                style={{ backgroundColor: `${agentColor}30` }}
              >
                <Bot className="w-3.5 h-3.5" style={{ color: agentColor }} />
              </div>
            )}
            <div
              className={`max-w-[85%] px-3 py-2 rounded-xl text-xs leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-primary-500/20 text-surface-100 rounded-br-sm whitespace-pre-wrap'
                  : 'bg-surface-700/50 text-surface-200 rounded-bl-sm chat-markdown'
              }`}
            >
              {msg.role === 'agent' ? (
                <>
                  {streaming && i === messages.length - 1 ? (
                    <span className="whitespace-pre-wrap">{msg.content}</span>
                  ) : (
                    <ReactMarkdown
                      remarkPlugins={REMARK_PLUGINS}
                      rehypePlugins={REHYPE_PLUGINS}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  )}
                  {streaming && i === messages.length - 1 && (
                    <span className="inline-block w-1.5 h-3.5 bg-primary-400 animate-pulse ml-0.5 align-middle" />
                  )}
                  {!msg.content && !streaming && (
                    <span className="text-surface-500 italic">응답 없음</span>
                  )}
                </>
              ) : (
                msg.content
              )}
            </div>
            {msg.role === 'user' && (
              <div className="w-6 h-6 rounded-full bg-surface-600 flex items-center justify-center shrink-0 mt-0.5">
                <User className="w-3.5 h-3.5 text-surface-300" />
              </div>
            )}
          </div>
        ))}

        <div ref={messagesEndRef} />
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-1.5 text-xs text-red-400 px-1 py-1">
          <AlertCircle className="w-3.5 h-3.5 shrink-0" />
          {error}
        </div>
      )}

      {/* Footer: cost + clear */}
      {messages.length > 0 && (
        <div className="flex items-center justify-between px-1 py-1">
          {totalCost > 0 ? (
            <span className="text-2xs text-surface-500">
              누적 비용: ${totalCost.toFixed(4)}
            </span>
          ) : (
            <span />
          )}
          <button
            onClick={handleClear}
            disabled={streaming}
            className="text-2xs text-surface-500 hover:text-surface-300 flex items-center gap-1 disabled:opacity-40"
          >
            <Trash2 className="w-3 h-3" />
            대화 초기화
          </button>
        </div>
      )}

      {/* Input area */}
      <div className="flex items-end gap-2 pt-2 border-t border-surface-700/50">
        <textarea
          ref={inputRef}
          value={input}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          placeholder="질문을 입력하세요... (Shift+Enter로 줄바꿈)"
          rows={1}
          className="flex-1 resize-none bg-surface-700/50 border border-surface-600 rounded-lg px-3 py-2 text-xs text-surface-100 placeholder:text-surface-500 focus:outline-none focus:border-primary-500/50 max-h-[80px]"
          disabled={streaming}
        />
        <button
          onClick={handleSend}
          disabled={!input.trim() || streaming}
          className="shrink-0 w-8 h-8 rounded-lg bg-primary-500/20 text-primary-400 flex items-center justify-center hover:bg-primary-500/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {streaming ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Send className="w-3.5 h-3.5" />
          )}
        </button>
      </div>
    </div>
  );
}
