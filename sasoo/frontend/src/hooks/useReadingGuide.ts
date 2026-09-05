import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { chatWithAgent } from '@/lib/api';
import { createTokenBuffer } from '@/lib/tokenBuffer';
import { getGuide, setGuide, type GuideRecord } from '@/lib/guideCache';
import { buildReadingGuidePrompt, parseReadingGuide, type ReadingGuide } from '@/lib/readingGuide';
import { S } from '@/lib/strings';

export type ReadingGuideStatus = 'loading' | 'empty' | 'generating' | 'ready' | 'error';

export interface ReadingGuideMeta {
  createdAt: number;
  level: string | null;
  costUsd: number | null;
}

export interface UseReadingGuideResult {
  status: ReadingGuideStatus;
  markdown: string;
  guide: ReadingGuide | null;
  meta: ReadingGuideMeta | null;
  streamText: string;
  error: string | null;
  /** 캐시된 안내가 지금 설명 수준과 다른 수준으로 만들어졌는지. */
  levelMismatch: boolean;
  generate: () => Promise<void>;
  cancel: () => void;
}

/**
 * 논문 하나의 읽기 안내를 캐시에서 읽고, 없으면 요청 시 한 번 생성한다.
 * 생성은 질문 도우미 API 1회 호출(비용 발생)이라 호출부의 확인을 거친 뒤에만 부른다.
 */
export function useReadingGuide(
  paperId: string | null,
  level: string | null | undefined,
): UseReadingGuideResult {
  const [status, setStatus] = useState<ReadingGuideStatus>('loading');
  const [markdown, setMarkdown] = useState('');
  const [meta, setMeta] = useState<ReadingGuideMeta | null>(null);
  const [streamText, setStreamText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // 논문이 바뀌면 진행 중인 생성을 끊고 그 논문의 캐시를 다시 읽는다.
  useEffect(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setMarkdown('');
    setMeta(null);
    setStreamText('');
    setError(null);

    if (!paperId) {
      setStatus('empty');
      return;
    }

    let cancelled = false;
    setStatus('loading');
    void getGuide(paperId)
      .catch(() => null)
      .then((record) => {
        if (cancelled) return;
        if (!record) {
          setStatus('empty');
          return;
        }
        setMarkdown(record.markdown);
        setMeta({ createdAt: record.createdAt, level: record.level, costUsd: record.costUsd });
        setStatus('ready');
      });

    return () => {
      cancelled = true;
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, [paperId]);

  const generate = useCallback(async () => {
    if (!paperId) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const hadGuide = Boolean(markdown);
    setStatus('generating');
    setStreamText('');
    setError(null);

    let text = '';
    const buffer = createTokenBuffer((chunk) => {
      setStreamText((prev) => prev + chunk);
    });

    try {
      await chatWithAgent(
        paperId,
        buildReadingGuidePrompt(level),
        [],
        (token) => {
          text += token;
          buffer.push(token);
        },
        (done) => {
          buffer.end();
          const record: GuideRecord = {
            markdown: text,
            createdAt: Date.now(),
            level: level ?? null,
            costUsd: done.cost_usd ?? null,
          };
          void setGuide(paperId, record).catch(() => {});
          setMarkdown(record.markdown);
          setMeta({
            createdAt: record.createdAt,
            level: record.level,
            costUsd: record.costUsd,
          });
          setStreamText('');
          setStatus('ready');
        },
        controller.signal,
      );
    } catch (err) {
      buffer.end();
      if (controller.signal.aborted) {
        setStreamText('');
        setStatus(hadGuide ? 'ready' : 'empty');
        return;
      }
      setError(err instanceof Error ? err.message : S.readingGuide.errorTitle);
      setStatus('error');
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, [level, markdown, paperId]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const guide = useMemo(() => (markdown ? parseReadingGuide(markdown) : null), [markdown]);
  const levelMismatch = Boolean(meta) && (meta?.level ?? null) !== (level ?? null);

  return {
    status,
    markdown,
    guide,
    meta,
    streamText,
    error,
    levelMismatch,
    generate,
    cancel,
  };
}
