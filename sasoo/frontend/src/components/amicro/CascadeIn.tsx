// Adapted from Amicro (MIT) — https://github.com/Subhan-code/Amicro--Micro-transitions-
// CardCascadeStagger의 스태거 아이디어를 실콘텐츠 entrance 래퍼로 변환.
import { motion, useReducedMotion } from 'motion/react';
import type { ReactNode } from 'react';

interface CascadeInProps {
  index: number;
  children: ReactNode;
}

export default function CascadeIn({ index, children }: CascadeInProps) {
  const reduceMotion = useReducedMotion();
  if (reduceMotion) return <>{children}</>;

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 200, damping: 22, mass: 0.9, delay: index * 0.07 }}
    >
      {children}
    </motion.div>
  );
}
