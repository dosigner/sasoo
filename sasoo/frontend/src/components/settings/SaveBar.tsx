import { Loader2 } from 'lucide-react';

import { S } from '@/lib/strings';

interface Props {
  changeCount: number;
  saving: boolean;
  error?: string | null;
  onSave: () => void;
  onDiscard: () => void;
}

/**
 * 변경이 있을 때만 나타나는 저장바.
 *
 * 저장 버튼이 헤더에 있으면 페이지가 길어질 때(설정은 대략 1,400px) 아래쪽
 * 항목을 편집하는 동안 화면 밖으로 사라진다. sticky로 따라오게 한다.
 *
 * 저장 성공의 피드백은 "바가 사라지는 것" 자체다 — 토스트를 겹치지 않는다.
 * 실패하면 바가 남고 그 안에 사유를 적는다. 재시도할 위치와 오류를 읽는
 * 위치가 같아야 한다.
 */
export function SaveBar({ changeCount, saving, error, onSave, onDiscard }: Props) {
  if (changeCount === 0) return null;

  return (
    <div className="settings-savebar" role="region" aria-label={S.settings.saveBarLabel}>
      <span
        className={`text-xs ${error ? 'text-danger' : 'text-fg-muted'}`}
        aria-live="polite"
      >
        {error ?? S.settings.changeCount(changeCount)}
      </span>
      <div className="flex shrink-0 gap-2">
        <button type="button" className="btn btn-ghost" onClick={onDiscard} disabled={saving}>
          {S.settings.discard}
        </button>
        <button type="button" className="btn btn-primary" onClick={onSave} disabled={saving}>
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {saving ? S.settings.saving : S.settings.save}
        </button>
      </div>
    </div>
  );
}

export default SaveBar;
