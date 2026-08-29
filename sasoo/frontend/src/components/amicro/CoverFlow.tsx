// Adapted from Amicro (MIT) — https://github.com/Subhan-code/Amicro--Micro-transitions-
// CardCoverFlow를 sasoo 토큰·제어형 activeIndex로 재작성.
import { motion, useReducedMotion } from 'motion/react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { coverFlowTransform } from '@/lib/coverflow';

export interface CoverFlowItem {
  src: string;
  title: string;
}

interface CoverFlowProps {
  items: CoverFlowItem[];
  activeIndex: number;
  onActiveChange: (index: number) => void;
  // 활성 카드를 다시 클릭했을 때 (라이트박스 열기 등)
  onOpen?: (index: number) => void;
}

export default function CoverFlow({ items, activeIndex, onActiveChange, onOpen }: CoverFlowProps) {
  const reduceMotion = useReducedMotion();

  const toPrev = () => onActiveChange(Math.max(0, activeIndex - 1));
  const toNext = () => onActiveChange(Math.min(items.length - 1, activeIndex + 1));

  return (
    <div
      className="flex w-full select-none flex-col items-center justify-center overflow-hidden rounded-xl border border-border bg-surface py-6"
      style={{ perspective: '1000px' }}
    >
      <div className="relative flex h-[190px] w-full items-center justify-center transform-3d">
        {items.map((item, i) => {
          const t = coverFlowTransform(i - activeIndex);
          const isActive = i === activeIndex;
          return (
            <motion.div
              key={`${item.src}-${i}`}
              className="absolute aspect-4/3 w-[180px] cursor-pointer"
              initial={false}
              animate={{ x: t.x * 2.2, rotateY: t.rotateY, z: t.z, scale: t.scale, opacity: t.opacity }}
              transition={reduceMotion ? { duration: 0 } : { type: 'spring', stiffness: 200, damping: 25 }}
              style={{ zIndex: 100 - Math.abs(i - activeIndex) }}
              onClick={() => (isActive ? onOpen?.(i) : onActiveChange(i))}
            >
              <img
                src={item.src}
                alt={item.title}
                className="h-full w-full rounded-lg border border-border bg-surface-hover object-contain shadow-lg"
                draggable={false}
              />
              <motion.div
                className="absolute -bottom-6 left-[-30px] right-[-30px] overflow-hidden text-ellipsis whitespace-nowrap text-center text-2xs font-medium text-fg-muted"
                animate={{ opacity: isActive ? 1 : 0, y: isActive ? 0 : -5 }}
                transition={reduceMotion ? { duration: 0 } : undefined}
              >
                {item.title}
              </motion.div>
            </motion.div>
          );
        })}
      </div>

      <div className="z-20 mt-7 flex w-fit items-center justify-center gap-2 rounded-full border border-border bg-surface-hover/60 px-1.5 py-0.5 shadow-xs backdrop-blur-md">
        <button
          type="button"
          onClick={toPrev}
          disabled={activeIndex === 0}
          className="rounded-full p-1 text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg disabled:opacity-40"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <div className="flex items-center justify-center gap-1">
          {items.map((_, i) => (
            <button
              key={i}
              type="button"
              onClick={() => onActiveChange(i)}
              aria-label={`${i + 1}`}
              className={`h-1 cursor-pointer rounded-full transition-all duration-300 ${
                activeIndex === i ? 'w-4 bg-accent' : 'w-1 bg-fg-muted/40 hover:bg-fg-muted/70'
              }`}
            />
          ))}
        </div>
        <button
          type="button"
          onClick={toNext}
          disabled={activeIndex === items.length - 1}
          className="rounded-full p-1 text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg disabled:opacity-40"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
