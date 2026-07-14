import { useCallback, useEffect, useRef, useState } from 'react';
import { animateSpring } from '../lib/spring';

const MIN_PANEL_WIDTH = 20;
const MAX_PANEL_WIDTH = 80;
const DEFAULT_SPLIT = 50;
const SNAP_POINTS = [25, 33, 42, 50, 58, 67, 75];
const SNAP_THRESHOLD = 2;
const KEYBOARD_STEP = 5;
const VELOCITY_WINDOW_MS = 100;
const SPRING_RESPONSE = 0.3;
const SPRING_DAMPING_RATIO = 1.0;
const SPLIT_PRESETS = {
  '1:2': 33,
  center: 50,
  '2:1': 67,
} as const;

export type WorkbenchSplitPreset = keyof typeof SPLIT_PRESETS;

/** Returns the nearest snap point within SNAP_THRESHOLD, or null if none is close enough. */
function getNearestSnapPoint(value: number): number | null {
  for (const point of SNAP_POINTS) {
    if (Math.abs(value - point) <= SNAP_THRESHOLD) {
      return point;
    }
  }
  return null;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

export function useWorkbenchLayout() {
  const [splitPosition, setSplitPosition] = useState(DEFAULT_SPLIT);
  const [isResizing, setIsResizing] = useState(false);
  const [pdfCollapsed, setPdfCollapsed] = useState(false);
  const [isSnapping, setIsSnapping] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Mirrors `splitPosition` synchronously so drag/spring/keyboard handlers can read
  // the current "presentation value" without waiting on a React re-render.
  const splitPositionRef = useRef(DEFAULT_SPLIT);
  // Cancel function for whichever release/preset spring is currently animating, if any.
  const cancelSpringRef = useRef<(() => void) | null>(null);
  // Rolling ~100ms window of {time, value} samples used to compute release velocity.
  const velocityHistoryRef = useRef<{ time: number; value: number }[]>([]);

  const updateSplitPosition = useCallback((value: number) => {
    splitPositionRef.current = value;
    setSplitPosition(value);
  }, []);

  const cancelActiveSpring = useCallback(() => {
    if (cancelSpringRef.current) {
      cancelSpringRef.current();
      cancelSpringRef.current = null;
    }
  }, []);

  // Ensure a running spring doesn't keep animating after unmount.
  useEffect(() => {
    return () => {
      cancelActiveSpring();
    };
  }, [cancelActiveSpring]);

  const springTo = useCallback(
    (target: number, velocity: number) => {
      cancelActiveSpring();

      if (prefersReducedMotion()) {
        updateSplitPosition(target);
        return;
      }

      cancelSpringRef.current = animateSpring({
        from: splitPositionRef.current,
        to: target,
        velocity,
        response: SPRING_RESPONSE,
        dampingRatio: SPRING_DAMPING_RATIO,
        onUpdate: updateSplitPosition,
        onSettle: () => {
          cancelSpringRef.current = null;
          setIsSnapping(false);
        },
      });
    },
    [cancelActiveSpring, updateSplitPosition]
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      // Interrupt any in-flight release/preset spring and continue from the
      // current presentation value rather than jumping.
      cancelActiveSpring();
      setIsResizing(true);
      setIsSnapping(false);
      document.body.classList.add('resizing');

      const container = containerRef.current;
      if (!container) return;

      const containerRect = container.getBoundingClientRect();
      velocityHistoryRef.current = [
        { time: performance.now(), value: splitPositionRef.current },
      ];

      const handleMouseMove = (moveEvent: MouseEvent) => {
        const relativeX = moveEvent.clientX - containerRect.left;
        const percentage = (relativeX / containerRect.width) * 100;
        const clamped = Math.max(
          MIN_PANEL_WIDTH,
          Math.min(MAX_PANEL_WIDTH, percentage)
        );

        // "Touch and content move together" — 1:1 tracking while dragging, no
        // mid-drag snap jumps. Snap candidates only get a visual highlight.
        updateSplitPosition(clamped);
        setIsSnapping(getNearestSnapPoint(clamped) !== null);

        const now = performance.now();
        const history = velocityHistoryRef.current;
        history.push({ time: now, value: clamped });
        while (history.length > 1 && now - history[0].time > VELOCITY_WINDOW_MS) {
          history.shift();
        }
      };

      const handleMouseUp = () => {
        setIsResizing(false);
        document.body.classList.remove('resizing');
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);

        const current = splitPositionRef.current;
        const target = getNearestSnapPoint(current);

        if (target === null) {
          // Not close enough to a snap point — stay exactly where released.
          setIsSnapping(false);
          return;
        }

        const history = velocityHistoryRef.current;
        let releaseVelocity = 0;
        if (history.length >= 2) {
          const newest = history[history.length - 1];
          const oldest = history[0];
          const dt = (newest.time - oldest.time) / 1000;
          if (dt > 0) {
            releaseVelocity = (newest.value - oldest.value) / dt;
          }
        }

        if (prefersReducedMotion()) {
          updateSplitPosition(target);
          setIsSnapping(false);
          return;
        }

        setIsSnapping(true);
        cancelSpringRef.current = animateSpring({
          from: current,
          to: target,
          velocity: releaseVelocity,
          response: SPRING_RESPONSE,
          dampingRatio: SPRING_DAMPING_RATIO,
          onUpdate: updateSplitPosition,
          onSettle: () => {
            cancelSpringRef.current = null;
            setIsSnapping(false);
          },
        });
      };

      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    },
    [cancelActiveSpring, updateSplitPosition]
  );

  const handleDoubleClick = useCallback(() => {
    springTo(DEFAULT_SPLIT, 0);
  }, [springTo]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      // Keyboard actions move immediately — no spring animation.
      cancelActiveSpring();
      let newPos = splitPositionRef.current;

      switch (e.key) {
        case 'ArrowLeft':
          e.preventDefault();
          newPos = Math.max(MIN_PANEL_WIDTH, splitPositionRef.current - KEYBOARD_STEP);
          break;
        case 'ArrowRight':
          e.preventDefault();
          newPos = Math.min(MAX_PANEL_WIDTH, splitPositionRef.current + KEYBOARD_STEP);
          break;
        case 'Home':
          e.preventDefault();
          newPos = MIN_PANEL_WIDTH;
          break;
        case 'End':
          e.preventDefault();
          newPos = MAX_PANEL_WIDTH;
          break;
        default:
          return;
      }

      const snapped = getNearestSnapPoint(newPos);
      setIsSnapping(snapped !== null);
      updateSplitPosition(snapped ?? newPos);
    },
    [cancelActiveSpring, updateSplitPosition]
  );

  const togglePdf = useCallback(() => {
    setPdfCollapsed((value) => !value);
  }, []);

  const setSplitPreset = useCallback(
    (preset: WorkbenchSplitPreset) => {
      setIsSnapping(false);
      springTo(SPLIT_PRESETS[preset], 0);
    },
    [springTo]
  );

  const activePreset = (Object.entries(SPLIT_PRESETS) as Array<[WorkbenchSplitPreset, number]>)
    .find(([, value]) => splitPosition === value)?.[0] ?? null;

  return {
    containerRef,
    splitPosition,
    activePreset,
    isResizing,
    pdfCollapsed,
    isSnapping,
    handleMouseDown,
    handleDoubleClick,
    handleKeyDown,
    togglePdf,
    setSplitPreset,
  };
}
