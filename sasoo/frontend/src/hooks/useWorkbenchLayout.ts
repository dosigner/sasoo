import { useCallback, useRef, useState } from 'react';

const MIN_PANEL_WIDTH = 20;
const MAX_PANEL_WIDTH = 80;
const DEFAULT_SPLIT = 50;
const SNAP_POINTS = [25, 33, 42, 50, 58, 67, 75];
const SNAP_THRESHOLD = 2;
const KEYBOARD_STEP = 5;
const SPLIT_PRESETS = {
  '1:2': 33,
  center: 50,
  '2:1': 67,
} as const;

export type WorkbenchSplitPreset = keyof typeof SPLIT_PRESETS;

export function useWorkbenchLayout() {
  const [splitPosition, setSplitPosition] = useState(DEFAULT_SPLIT);
  const [isResizing, setIsResizing] = useState(false);
  const [pdfCollapsed, setPdfCollapsed] = useState(false);
  const [isSnapping, setIsSnapping] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const snapToNearest = useCallback((value: number): number => {
    for (const point of SNAP_POINTS) {
      if (Math.abs(value - point) <= SNAP_THRESHOLD) {
        setIsSnapping(true);
        return point;
      }
    }
    setIsSnapping(false);
    return value;
  }, []);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setIsResizing(true);
      document.body.classList.add('resizing');

      const container = containerRef.current;
      if (!container) return;

      const containerRect = container.getBoundingClientRect();

      const handleMouseMove = (moveEvent: MouseEvent) => {
        const relativeX = moveEvent.clientX - containerRect.left;
        const percentage = (relativeX / containerRect.width) * 100;
        const clamped = Math.max(
          MIN_PANEL_WIDTH,
          Math.min(MAX_PANEL_WIDTH, percentage)
        );
        setSplitPosition(snapToNearest(clamped));
      };

      const handleMouseUp = () => {
        setIsResizing(false);
        setIsSnapping(false);
        document.body.classList.remove('resizing');
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
      };

      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    },
    [snapToNearest]
  );

  const handleDoubleClick = useCallback(() => {
    setSplitPosition(DEFAULT_SPLIT);
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      let newPos = splitPosition;

      switch (e.key) {
        case 'ArrowLeft':
          e.preventDefault();
          newPos = Math.max(MIN_PANEL_WIDTH, splitPosition - KEYBOARD_STEP);
          break;
        case 'ArrowRight':
          e.preventDefault();
          newPos = Math.min(MAX_PANEL_WIDTH, splitPosition + KEYBOARD_STEP);
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

      setSplitPosition(snapToNearest(newPos));
    },
    [splitPosition, snapToNearest]
  );

  const togglePdf = useCallback(() => {
    setPdfCollapsed((value) => !value);
  }, []);

  const setSplitPreset = useCallback((preset: WorkbenchSplitPreset) => {
    setIsSnapping(false);
    setSplitPosition(SPLIT_PRESETS[preset]);
  }, []);

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
