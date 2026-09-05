/**
 * PDF에서 드래그로 고른 텍스트를 "이 부분 설명" 질문 프롬프트로 바꾸는 헬퍼.
 *
 * 여기서 만든 프롬프트는 채팅 패널의 draft에만 채워진다. 실제 전송(비용 발생)은
 * 사용자가 채팅 패널에서 보내기 버튼을 눌러야 나간다 — 이 파일은 자동 호출을 하지 않는다.
 */
import { S } from '@/lib/strings';

export const SELECTION_MAX_CHARS = 2000;

/**
 * pdf.js 텍스트 레이어는 줄(span) 경계마다 줄바꿈이 들어가므로, 선택한 텍스트의
 * 연속 공백과 줄바꿈을 한 칸 공백으로 눌러 준다. 하이픈 줄바꿈("proba- bility")은
 * 건드리지 않는다(원문 표기를 오수정할 위험이 있다).
 */
export function normalizeSelectionText(raw: string): string {
  return raw.replace(/\s+/g, ' ').trim();
}

export function isSelectionTooLong(text: string): boolean {
  return text.length > SELECTION_MAX_CHARS;
}

function levelLabel(level: string | null | undefined): string | null {
  if (!level) return null;
  const levels = S.levels as Record<string, { label: string } | undefined>;
  return levels[level]?.label ?? null;
}

/**
 * 선택한 부분을 설명해 달라는 고정 형식 프롬프트. 직관을 먼저 한 단락으로, 수식
 * 유도가 필요하면 접힌 소제목으로 쓰라고 형식을 못 박는다. 표기 사전 프롬프트
 * (`lib/readingGuide.ts`의 `buildReadingGuidePrompt`)와 같은 방식으로 눈높이 한 줄을
 * 넣지만, 그 파일은 건드리지 않는다.
 */
export function buildExplainPrompt(page: number, text: string, level?: string | null): string {
  const label = levelLabel(level);
  const lines = [
    `p.${page}의 다음 부분을 설명해 주세요. 직관을 먼저 한 단락으로, 수식 유도가 필요하면 그 아래에 '유도' 소제목으로 접어서(details 태그) 써 주세요. 표기는 논문 것을 그대로 쓰세요.`,
  ];
  if (label) {
    lines.push(`읽는 사람은 ${label}이에요. 용어와 배경 설명을 그 눈높이에 맞춰 주세요.`);
  }
  lines.push('', `> ${text}`);
  return lines.join('\n');
}
