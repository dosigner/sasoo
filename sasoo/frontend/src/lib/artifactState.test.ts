import { describe, it, expect } from 'vitest';

import { resolveArtifactPlaceholder } from './artifactState';

describe('resolveArtifactPlaceholder', () => {
  it('상태를 모를 때(undefined) "없다"고 단정하지 않는다', () => {
    // 회귀 방지: prop 기본값이 'ready'였을 때, /figures 응답이 도착하기 전이나
    // 요청 실패로 visual_state가 undefined인 순간 목록이 비어 있으면
    // "이 논문에서 뽑은 그림이 아직 없어요"가 떴다. 추출은 멀쩡히 진행 중이었다.
    expect(resolveArtifactPlaceholder(undefined, false)).toBe('preparing');
    expect(resolveArtifactPlaceholder(undefined, true)).toBe('preparing');
  });

  it('추출이 진행 중이면 준비 중으로 본다', () => {
    expect(resolveArtifactPlaceholder('running', false)).toBe('preparing');
  });

  it('백엔드가 명시적으로 ready라고 답했을 때만 빈 상태다', () => {
    expect(resolveArtifactPlaceholder('ready', false)).toBe('empty');
  });

  it('오류 메시지가 있는 error는 오류로 표시한다', () => {
    expect(resolveArtifactPlaceholder('error', true)).toBe('error');
  });

  it('메시지 없는 error는 기존 동작(빈 상태)을 유지한다', () => {
    // 백엔드(artifact_status)는 visual_error가 있을 때만 'error'를 주므로
    // 도달하지 않는 경로다. 기존 동작을 그대로 보존해 변경 범위를 좁힌다.
    expect(resolveArtifactPlaceholder('error', false)).toBe('empty');
  });

  it('부분 추출은 경고로 표시한다', () => {
    expect(resolveArtifactPlaceholder('partial', false)).toBe('partial');
    expect(resolveArtifactPlaceholder('partial', true)).toBe('partial');
  });
});
