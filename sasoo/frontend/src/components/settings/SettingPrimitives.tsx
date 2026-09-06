import { AppIcon, type AppIconName } from '@/components/icons';

// ---------------------------------------------------------------------------
// 설정·프로필 공용 레이아웃 원시 컴포넌트.
// 좁은 한 열(page-container-settings) 안에 섹션 패널과 명도 블록 행을 쌓는다.
// 두 페이지가 같은 모양을 따로 짜지 않도록 여기 한 곳에서만 정의한다.
// ---------------------------------------------------------------------------

export function SettingSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="archive-panel panel-compact">
      <h2 className="text-sm font-semibold tracking-apple-body text-fg">{title}</h2>
      {description && (
        <p className="mt-1 text-xs text-fg-muted">{description}</p>
      )}
      <div className="mt-3 flex flex-col gap-1">{children}</div>
    </section>
  );
}

export function SettingRow({
  label,
  description,
  badge,
  full = false,
  children,
}: {
  label: string;
  description?: React.ReactNode;
  badge?: React.ReactNode;
  full?: boolean;
  children: React.ReactNode;
}) {
  if (full) {
    return (
      <div className="settings-row-block">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-fg">{label}</span>
          {badge}
        </div>
        {description && (
          <p className="mt-0.5 text-xs text-fg-muted">{description}</p>
        )}
        <div className="mt-2">{children}</div>
      </div>
    );
  }
  return (
    <div className="settings-row-block flex items-center justify-between gap-4">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-fg">{label}</span>
          {badge}
        </div>
        {description && (
          <p className="mt-0.5 text-xs text-fg-muted">{description}</p>
        )}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

// "하나 고르기" 세그먼트 컨트롤. iOS식 인셋 트랙 위에 선택된 세그먼트가 pill
// (surface + shadow)로 떠오르고, 누를 때 미세하게 눌린다(reduced-motion 존중).
// 분야 숙련도, 논문 읽기 경험, 테마가 같은 컨트롤을 쓴다.
export function SegmentGroup({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: readonly { key: string; label: string; icon?: AppIconName }[];
  value: string;
  onChange: (key: string) => void;
  ariaLabel: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className="inline-flex max-w-full flex-wrap gap-1 rounded-control border border-border/50 bg-bg/60 p-1"
    >
      {options.map((opt) => {
        const active = opt.key === value;
        return (
          <button
            key={opt.key}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(opt.key)}
            className={`inline-flex items-center gap-2 rounded-control px-3.5 py-2 text-sm transition-all duration-150 ease-out motion-safe:active:scale-[0.97] ${
              active
                ? 'bg-surface font-medium text-fg shadow-xs'
                : 'text-fg-muted hover:text-fg-secondary'
            }`}
          >
            {opt.icon && <AppIcon name={opt.icon} className="h-4 w-4" />}
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
