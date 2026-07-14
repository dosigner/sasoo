type ErrnoError = Error & { code?: string };

type ErrorEmitter = {
  on(event: 'error', listener: (error: ErrnoError) => void): unknown;
};

/**
 * stdout/stderr의 EPIPE를 무해화한다.
 *
 * dev 실행(`pnpm dev`)에서 Electron 메인의 stdout/stderr는 concurrently가 소유한 파이프다.
 * 앱을 종료하면 concurrently(--kill-others)가 정리에 들어가면서 파이프의 읽는 쪽이 먼저
 * 사라지고, 그 뒤의 모든 쓰기가 EPIPE가 된다 — 백엔드 종료 로그(backend-process-stopper의
 * console.warn 6곳)든, Node가 스스로 뿜는 process warning이든.
 *
 * 가드가 없으면 그 EPIPE가 uncaughtException으로 메인 프로세스를 죽인다. 하필 그 시점은
 * app-quit-handler가 before-quit을 preventDefault()로 막아둔 구간이라, 메인이 죽으면
 * 뒤따라야 할 app.quit()이 영영 실행되지 않고 Python 백엔드와 분석 워커가 고아로 남는다.
 *
 * EPIPE만 삼키고 나머지 stdio 오류는 그대로 던진다 — 진짜 오류를 숨기지 않기 위해서다.
 */
export function installStdioEpipeGuard(
  stdout: ErrorEmitter = process.stdout,
  stderr: ErrorEmitter = process.stderr,
): void {
  for (const stream of [stdout, stderr]) {
    stream.on('error', (error: ErrnoError) => {
      if (error?.code === 'EPIPE') {
        return; // 읽는 쪽이 사라졌을 뿐이다. 쓸 곳이 없는 것은 죽을 이유가 못 된다.
      }
      throw error;
    });
  }
}
