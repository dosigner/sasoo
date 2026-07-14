import { EventEmitter } from 'events';
import { describe, expect, it } from 'vitest';

import { installStdioEpipeGuard } from './stdio-epipe-guard';

function errorWithCode(message: string, code: string): Error {
  return Object.assign(new Error(message), { code });
}

describe('stdio EPIPE guard', () => {
  it('swallows EPIPE so a closed stdout pipe cannot kill the main process', () => {
    // Given: dev 실행에서 stdout/stderr는 concurrently가 소유한 파이프다. 앱을 종료하면
    // 그 읽는 쪽이 먼저 사라지고, 이후의 어떤 쓰기(백엔드 종료 로그, Node의 process
    // warning)도 EPIPE가 된다. 가드가 없으면 메인이 죽고 before-quit이 preventDefault로
    // 막아둔 app.quit()이 영영 실행되지 않아 백엔드가 고아로 남는다.
    const stdout = new EventEmitter();
    const stderr = new EventEmitter();
    installStdioEpipeGuard(stdout, stderr);

    // When / Then
    expect(() => stdout.emit('error', errorWithCode('write EPIPE', 'EPIPE'))).not.toThrow();
    expect(() => stderr.emit('error', errorWithCode('write EPIPE', 'EPIPE'))).not.toThrow();
  });

  it('rethrows non-EPIPE stdio errors instead of hiding them', () => {
    // Given: 디스크가 찼다든지 하는 진짜 stdio 오류까지 삼키면 안 된다.
    const stdout = new EventEmitter();
    installStdioEpipeGuard(stdout, new EventEmitter());

    // When / Then
    expect(() => stdout.emit('error', errorWithCode('no space left', 'ENOSPC'))).toThrow('no space left');
  });
});
