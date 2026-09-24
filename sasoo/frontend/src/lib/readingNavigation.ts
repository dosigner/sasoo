export function focusReadingTarget(target: HTMLElement, behavior: ScrollBehavior = 'auto'): void {
  const panel = target.closest<HTMLElement>('[data-analysis-scroll]');
  if (!panel) return;
  const margin = Number.parseFloat(getComputedStyle(target).scrollMarginTop) || 0;
  panel.scrollTo({
    top: panel.scrollTop + target.getBoundingClientRect().top
      - panel.getBoundingClientRect().top - panel.clientTop - margin,
    behavior,
  });
  target.tabIndex = -1;
  target.focus({ preventScroll: true });
}
