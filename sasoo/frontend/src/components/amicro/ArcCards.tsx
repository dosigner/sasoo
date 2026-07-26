// Adapted from Amicro (MIT) — https://github.com/Subhan-code/Amicro--Micro-transitions-
// CardArc5를 sasoo 토큰·장식용 소형 버전으로 재작성. hover 시 5장이 부채꼴로 펼쳐진다.
import { motion, useReducedMotion } from 'motion/react';

interface ArcCardsProps {
  hovered: boolean;
  className?: string;
}

const ANGLE = 30;
const GAP = 44;
const Y_OFFSET = 8;
const CENTER = 2;

export default function ArcCards({ hovered, className = '' }: ArcCardsProps) {
  const reduceMotion = useReducedMotion();
  const active = hovered && !reduceMotion;

  return (
    <div className={`pointer-events-none relative flex h-[4.5rem] w-[3.4rem] items-center justify-center ${className}`}>
      {[0, 1, 2, 3, 4].map((i) => {
        const dist = i - CENTER;
        let y = 0;
        if (active) {
          if (Math.abs(dist) === 2) y = Y_OFFSET;
          else if (Math.abs(dist) === 1) y = -0.2 * Y_OFFSET;
          else y = -Y_OFFSET;
        }
        return (
          <motion.div
            key={i}
            animate={{
              rotate: active ? dist * (ANGLE / CENTER) : 0,
              x: active ? dist * (GAP / CENTER) : 0,
              y,
              scale: active && dist === 0 ? 1.05 : 1,
            }}
            transition={{ type: 'spring', stiffness: 180, damping: 20, mass: 0.8 }}
            style={{ zIndex: 3 - Math.abs(dist), originX: 0.5, originY: 1 }}
            className="absolute inset-0 rounded-lg border border-border bg-surface-hover shadow-[0_4px_10px_-2px_rgba(0,0,0,0.15)]"
          />
        );
      })}
    </div>
  );
}
