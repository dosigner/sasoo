import type { VisualState } from './api';

/**
 * 그림·표 목록이 비어 있을 때 무엇을 보여줄지 결정한다.
 *
 * 이 함수가 따로 있는 이유는 하나다: **모르는 상태를 "없다"로 단정하지 않기 위해서**.
 *
 * FigureGallery/TableGallery는 부모에게서 `visualState={figures?.visual_state}`를 받는다.
 * `/figures` 응답이 도착하기 전이나 요청이 실패하면 이 값은 undefined다. 예전에는 prop
 * 기본값이 'ready'였고, 그러면 목록이 빈 것과 겹쳐 "이 논문에서 뽑은 그림이 아직 없어요"가
 * 떴다 — 아티팩트 추출이 멀쩡히 진행 중인데도 사용자에겐 추출 실패로 보였다.
 *
 * 우선순위는 preparing > error > partial > empty이며, 'empty'는 백엔드가 명시적으로
 * ready라고 답했을 때만 나온다.
 */
export type ArtifactPlaceholder = 'preparing' | 'error' | 'partial' | 'empty';

export function resolveArtifactPlaceholder(
  visualState: VisualState | undefined,
  hasErrorMessage: boolean,
): ArtifactPlaceholder {
  // undefined = 아직 응답을 못 받았거나 요청이 실패한 상태. 준비 중으로 취급한다.
  // 이 한 줄이 이번 수정의 전부이며, 나머지 분기는 기존 동작을 그대로 옮긴 것이다.
  if (visualState === undefined || visualState === 'running') return 'preparing';
  // 백엔드는 visual_error가 있을 때만 'error'를 준다(artifact_status). 메시지 없는
  // 'error'는 도달하지 않는 경로이므로 기존 동작(빈 상태)을 그대로 유지한다.
  if (visualState === 'error' && hasErrorMessage) return 'error';
  if (visualState === 'partial') return 'partial';
  return 'empty';
}
