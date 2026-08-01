import { S } from '@/lib/strings';

export type Provider = 'openai' | 'gemini';

interface Props {
  value: Provider;
  onChange: (next: Provider) => void;
  hasOpenAIKey: boolean;
  hasGeminiKey: boolean;
}

/**
 * 공급사 선택 카드.
 *
 * select 대신 카드를 쓰는 이유는 이 결정이 페이지에서 가장 중요하기 때문이다.
 * 나머지 설정은 전부 부수적이라 시각적 비중을 여기 한 곳에만 준다.
 *
 * 모델명을 카드에 노출한다 — 사용자가 "OpenAI"만 보고는 무엇이 도는지 모른다.
 * 이름이 적혀 있으면 그 이름으로 벤치마크와 가격을 직접 확인할 수 있다.
 *
 * 키 상태 판정은 저장된 값 기준이다(hasOpenAIKey/hasGeminiKey를 baseline에서
 * 받는다). 타이핑 중인 값으로 판정하면 카드가 깜빡인다.
 */
export function ProviderCards({ value, onChange, hasOpenAIKey, hasGeminiKey }: Props) {
  const options = [
    {
      id: 'openai' as const,
      name: S.settings.aiProviderOpenAI,
      model: S.settings.aiProviderOpenAIModel,
      hasKey: hasOpenAIKey,
    },
    {
      id: 'gemini' as const,
      name: S.settings.aiProviderGemini,
      model: S.settings.aiProviderGeminiModel,
      hasKey: hasGeminiKey,
    },
  ];

  const selectable = options.filter((o) => o.hasKey);

  // 좌우 화살표로 선택 가능한 카드 사이를 순환한다(radiogroup 관례).
  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    if (selectable.length < 2) return;
    event.preventDefault();
    const at = selectable.findIndex((o) => o.id === value);
    const step = event.key === 'ArrowRight' ? 1 : -1;
    const next = selectable[(at + step + selectable.length) % selectable.length];
    onChange(next.id);
  };

  return (
    <div
      role="radiogroup"
      aria-label={S.settings.aiProvider}
      className="grid gap-3 sm:grid-cols-2"
      onKeyDown={handleKeyDown}
    >
      {options.map((opt) => {
        const selected = value === opt.id;
        const statusId = `provider-status-${opt.id}`;
        const className = !opt.hasKey
          ? 'provider-card provider-card-disabled'
          : selected
            ? 'provider-card provider-card-active'
            : 'provider-card provider-card-inactive';

        return (
          <button
            key={opt.id}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-disabled={!opt.hasKey}
            aria-describedby={statusId}
            disabled={!opt.hasKey}
            // 선택된 카드만 탭 순서에 남긴다 — 그룹 안 이동은 화살표로 한다.
            tabIndex={selected || (!selectable.some((o) => o.id === value) && opt.hasKey) ? 0 : -1}
            className={className}
            onClick={() => opt.hasKey && onChange(opt.id)}
          >
            <span className="text-sm font-semibold text-fg">{opt.name}</span>
            <span className="text-xs text-fg-secondary">{opt.model}</span>
            <span id={statusId} className="mt-2 text-xs text-fg-muted">
              {opt.hasKey ? S.settings.aiProviderKeyReady : S.settings.aiProviderKeyMissing}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export default ProviderCards;
