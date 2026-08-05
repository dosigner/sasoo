// backend document_audit의 저품질 의심 컷(0.72)과 동일 기준.
// sasoo/backend/services/document_audit.py의 _figure_is_flagged/_table_is_flagged가
// `confidence < 0.72`를 감사 대상으로 잡는다 — 프런트 색점도 같은 컷을 재사용해
// "검토 권장"의 기준이 백엔드 감사 로직과 어긋나지 않게 한다.
// FigureGallery·TableGallery 카드의 신뢰도 색점이 이 상수 하나를 공유한다.
export const CONFIDENCE_REVIEW_THRESHOLD = 0.72;
