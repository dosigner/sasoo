type QuitEvent = {
  preventDefault(): void;
};

type QuitApp = {
  on(event: 'before-quit', listener: (event: QuitEvent) => void): unknown;
  quit(): void;
};

type StoppableBackend = {
  stop(): Promise<void>;
  forceStop?(): Promise<void>;
};

const MAX_AUTOMATIC_QUIT_RETRIES = 3;

export function registerGracefulBackendQuit(
  app: QuitApp,
  getBackend: () => StoppableBackend | null,
): void {
  let quitAllowed = false;
  let backendStop: Promise<void> | null = null;
  let quitRetryTimer: ReturnType<typeof setTimeout> | null = null;
  let shutdownFailures = 0;

  app.on('before-quit', (event) => {
    if (quitAllowed) {
      return;
    }

    const backend = getBackend();
    if (!backend) {
      return;
    }

    event.preventDefault();
    if (backendStop) {
      return;
    }
    if (quitRetryTimer) {
      clearTimeout(quitRetryTimer);
      quitRetryTimer = null;
    }

    backendStop = backend.stop()
      .then(() => {
        quitAllowed = true;
        app.quit();
      })
      .catch((error: unknown) => {
        if (error instanceof Error) {
          console.error('[Main] Backend shutdown failed during app quit', error.message);
        } else {
          console.error('[Main] Backend shutdown failed during app quit with an unknown error');
        }
        backendStop = null;
        shutdownFailures += 1;
        if (shutdownFailures >= MAX_AUTOMATIC_QUIT_RETRIES) {
          console.error('[Main] Forcing final backend shutdown before app quit');
          backendStop = Promise.resolve(backend.forceStop?.())
            .catch((forceError: unknown) => {
              if (forceError instanceof Error) {
                console.error('[Main] Final backend force-stop failed during app quit', forceError.message);
              } else {
                console.error('[Main] Final backend force-stop failed during app quit with an unknown error');
              }
            })
            .then(() => {
              quitAllowed = true;
              app.quit();
            });
          return;
        }
        quitRetryTimer = setTimeout(() => {
          quitRetryTimer = null;
          app.quit();
        }, 1000);
      });
  });
}
