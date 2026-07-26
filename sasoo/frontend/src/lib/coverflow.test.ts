import { describe, expect, it } from 'vitest';
import { coverFlowTransform } from './coverflow';

describe('coverFlowTransform', () => {
  it('활성 카드(offset 0)는 정면·확대·불투명', () => {
    expect(coverFlowTransform(0)).toEqual({ x: 0, rotateY: 0, z: 50, scale: 1.1, opacity: 1 });
  });

  it('왼쪽 카드(offset -1)는 +38도 회전, 뒤로 밀림', () => {
    const t = coverFlowTransform(-1);
    expect(t.rotateY).toBe(38);
    expect(t.x).toBe(-56);
    expect(t.z).toBe(-50);
    expect(t.scale).toBeCloseTo(0.92);
    expect(t.opacity).toBeCloseTo(0.75);
  });

  it('오른쪽 카드(offset 2)는 -38도 회전, 더 흐림', () => {
    const t = coverFlowTransform(2);
    expect(t.rotateY).toBe(-38);
    expect(t.opacity).toBeCloseTo(0.5);
  });

  it('3칸 이상 떨어지면 투명', () => {
    expect(coverFlowTransform(3).opacity).toBe(0);
    expect(coverFlowTransform(-4).opacity).toBe(0);
  });
});
