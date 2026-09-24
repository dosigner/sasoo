import { Children, isValidElement, useEffect, useRef, useState, type ComponentPropsWithoutRef } from 'react';
import { S } from '@/lib/strings';

const COPY_LABELS = {
  idle: S.readingCode.copy,
  copying: S.readingCode.copy,
  copied: S.readingCode.copied,
  error: S.readingCode.copyFailed,
} as const;

export function ReadingCodeBlock({ children, ...props }: ComponentPropsWithoutRef<'pre'>) {
  const preRef = useRef<HTMLPreElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [copyState, setCopyState] = useState<keyof typeof COPY_LABELS>('idle');
  const code = Children.toArray(children).find(isValidElement<{ className?: string }>);
  const language = code?.props.className?.match(/(?:^|\s)(?:language|lang)-(\S+)/)?.[1] ?? S.readingCode.code;

  useEffect(() => () => {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
  }, []);

  async function copyCode() {
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    const source = preRef.current?.querySelector('code')?.textContent ?? '';
    setCopyState('copying');
    try {
      await navigator.clipboard.writeText(source);
      if (!preRef.current) return;
      setCopyState('copied');
      timerRef.current = setTimeout(() => setCopyState('idle'), 1500);
    } catch {
      if (preRef.current) setCopyState('error');
    }
  }

  return (
    <div className="reading-code-block">
      <div className="reading-code-toolbar">
        <span className="reading-code-language">{language}</span>
        <button
          type="button"
          className="reading-code-copy"
          aria-label={COPY_LABELS.idle}
          aria-busy={copyState === 'copying'}
          disabled={copyState === 'copying'}
          onClick={copyCode}
        >
          {COPY_LABELS[copyState]}
        </button>
        <span className="sr-only" role="status">
          {copyState === 'copied' || copyState === 'error' ? COPY_LABELS[copyState] : ''}
        </span>
      </div>
      <pre {...props} ref={preRef} tabIndex={0} role="region" aria-label={language}>
        {children}
      </pre>
    </div>
  );
}
