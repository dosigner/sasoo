import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useFocusTrap(
  containerRef: RefObject<HTMLElement | null>,
  isActive: boolean,
  onEscape?: () => void
): void {
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isActive || !containerRef.current) {
      return;
    }

    // Save currently focused element
    previouslyFocusedRef.current = document.activeElement as HTMLElement;

    // Get all focusable elements inside the container
    const getFocusableElements = (): HTMLElement[] => {
      if (!containerRef.current) return [];
      return Array.from(
        containerRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
      );
    };

    // Focus the first focusable element
    const focusableElements = getFocusableElements();
    if (focusableElements.length > 0) {
      focusableElements[0].focus();
    }

    // Handle keyboard events
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onEscape?.();
        return;
      }

      if (event.key !== 'Tab') {
        return;
      }

      const currentFocusableElements = getFocusableElements();
      if (currentFocusableElements.length === 0) {
        return;
      }

      const activeElement = document.activeElement as HTMLElement;
      const focusedIndex = currentFocusableElements.indexOf(activeElement);

      if (event.shiftKey) {
        // Shift + Tab: move to previous element
        const previousIndex =
          focusedIndex <= 0 ? currentFocusableElements.length - 1 : focusedIndex - 1;
        currentFocusableElements[previousIndex].focus();
        event.preventDefault();
      } else {
        // Tab: move to next element
        const nextIndex =
          focusedIndex === -1 || focusedIndex >= currentFocusableElements.length - 1
            ? 0
            : focusedIndex + 1;
        currentFocusableElements[nextIndex].focus();
        event.preventDefault();
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);

      // Restore focus to previously focused element
      if (previouslyFocusedRef.current && previouslyFocusedRef.current.focus) {
        previouslyFocusedRef.current.focus();
      }
    };
  }, [isActive, onEscape]);
}
