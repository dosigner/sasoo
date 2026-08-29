export type Theme = 'dark' | 'light';

const THEME_KEY = 'sasoo-theme';

/** macOS 여부 — 타이틀바 여백과 창 버튼 배치가 여기서 갈린다. */
export const isMac = navigator.platform.toLowerCase().includes('mac');

/** 저장된 테마. 값이 없거나 알 수 없는 값이면 null. */
export function readStoredTheme(): Theme | null {
  const raw = localStorage.getItem(THEME_KEY);
  return raw === 'dark' || raw === 'light' ? raw : null;
}

/**
 * 테마를 문서 루트, localStorage, OS(nativeTheme)에 한 번에 반영한다.
 * macOS vibrancy 재질은 OS 명암을 따르므로 셋이 갈라지면 사이드바만
 * 이전 테마로 남는다. 웹 환경에는 setNativeTheme이 없으므로 무시된다.
 */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.classList.toggle('dark', theme === 'dark');
  root.classList.toggle('light', theme === 'light');
  localStorage.setItem(THEME_KEY, theme);
  window.electronAPI?.setNativeTheme?.(theme).catch(() => {});
}

/** 문서 루트에 플랫폼 클래스를 부착한다(CSS 재질 분기용). */
export function applyPlatformClass(): void {
  const platform = isMac
    ? 'darwin'
    : navigator.platform.toLowerCase().includes('win')
      ? 'win32'
      : 'linux';
  document.documentElement.classList.add(`platform-${platform}`);
}
