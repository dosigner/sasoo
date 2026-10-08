import { Loader2 } from 'lucide-react';
import { useBlocker } from 'react-router';
import { Modal } from '@/components/ui';

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
  const blocker = useBlocker(changeCount > 0);
  if (changeCount === 0) return null;

  return (
    <>
    <Modal open={blocker.state === 'blocked'} onClose={() => blocker.reset?.()} title="저장하지 않고 이동할까요?">
      <h3 className="text-lg font-semibold text-fg">저장하지 않고 이동할까요?</h3>
      <p className="mt-2 text-sm text-fg-secondary">이 화면에서 수정한 내용은 아직 저장되지 않았어요.</p>
      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <button type="button" className="btn-primary" onClick={() => blocker.reset?.()}>계속 편집</button>
        <button type="button" className="btn-secondary" onClick={() => blocker.proceed?.()} disabled={saving}>저장하지 않고 이동</button>
      </div>
    </Modal>
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
        <button type="button" className="btn bg-accent accent-solid-fg hover:bg-accent-hover" onClick={onSave} disabled={saving}>
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {saving ? S.settings.saving : S.settings.save}
        </button>
      </div>
    </div>
    </>
  );
}

export default SaveBar;
