// CoverFlow 카드의 3D 배치 계산. offset = 카드 인덱스 - 활성 인덱스.
// Adapted from Amicro (MIT) — https://github.com/Subhan-code/Amicro--Micro-transitions-
export interface CoverFlowTransform {
  x: number;
  rotateY: number;
  z: number;
  scale: number;
  opacity: number;
}

const CARD_GAP_PX = 56;

export function coverFlowTransform(offset: number): CoverFlowTransform {
  const abs = Math.abs(offset);
  if (offset === 0) {
    return { x: 0, rotateY: 0, z: 50, scale: 1.1, opacity: 1 };
  }
  return {
    x: offset * CARD_GAP_PX,
    rotateY: offset < 0 ? 38 : -38,
    z: -abs * 50,
    scale: 1 - abs * 0.08,
    opacity: abs > 2 ? 0 : 1 - abs * 0.25,
  };
}
