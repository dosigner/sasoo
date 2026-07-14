type QuitEvent = {
  preventDefault(): void;
};

type QuitApp = {
  on(event: 'before-quit', listener: (event: QuitEvent) => void): unknown;
  quit(): void;
};

type StoppableBackend = {
  stop(): Promise<void>;
};

export function registerGracefulBackendQuit(
  app: QuitApp,
  getBackend: () => StoppableBackend | null,
): void {
  let quitAllowed = false;
  let backendStop: Promise<void> | null = null;

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
      });
  });
}
