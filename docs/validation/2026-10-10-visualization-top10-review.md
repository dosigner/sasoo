# Sasoo 1.2.0 visualization review: priority top 10

검토일: 2026-10-10. 대상: 공개 v1.2.0 커밋 3076abfe56ff7cd06444c64eebd85e6b180491aa. 별도 릴리스 작업 트리 HEAD 6a257d5와의 코드 차이가 없음을 확인했다. 기준 버전: v1.1.0. 기능 요구는 이 대화의 이미지 5개 / Mermaid 3개 / HTML 1개 상한과 추가 항목 중요도 60점 조건, 핵심 이미지 Sunburst 최대 1개, 비용 미확인 상태 보존이다.

P1은 데이터 보호, 결과 무결성 또는 핵심 생성 복구에 영향을 주는 우선 수정 항목이다. P2는 제한, 계산 신뢰도와 비용 표시의 오류다. 실제 빈도나 악용 사례를 측정한 것은 아니다. 소스, 실제 함수의 모의 실행, React/jsdom hook 실행, 별도 Chromium으로 검토했다. DB 쓰기와 유료 API 호출은 mock으로 대체했다. Chrome의 가상 외부 요청은 로컬 route로 가로채 실제 외부 전송을 하지 않았다.

## 1. P1: Exported HTML can navigate to an external URL

신규 HTML 내보내기 문제. `sasoo/frontend/src/lib/vizExport.ts:60`의 바깥 문서는 CSP가 없다. 안쪽 HTML의 connect-src/frame-src 제한과 sandbox allow-scripts는 자기 iframe의 location.href 탐색을 차단하지 않는다. 합성 데이터가 담긴 가상 HTTPS 주소로 이동하는 코드를 실행했을 때 export 구조에서 요청 1회, 앱 index.html 부모 CSP 구조에서 0회를 기록했다. 논문이나 입력값이 URL로 전송될 수 있는 경로이며 실제 유출을 관측한 것은 아니다. 외부 프레임 탐색을 막는 부모 CSP를 내보내기에도 적용하고 srcdoc 계산 동작을 함께 테스트해야 한다.

## 2. P1: Regeneration can write an old artifact into a new analysis run

기존 저장 구조가 HTML에도 적용된다. `sasoo/backend/api/analysis_routes.py:728`에서 읽은 행의 정체성을 보존하지 않고, 생성 후 `:805`에서 호출하는 updater가 `:636`에서 최신 행을 다시 읽는다. 실제 updater 모의 실행에서 새 행 202의 id=1 항목에 옛 실행의 HTML이 저장됐다. 재생성 대기 중 재분석이 끝나는 조건에서 발생한다. 원래 행 id/input_hash를 저장 조건까지 전달하고 실행 변경 시 덮어쓰기를 거부해야 한다. 전체 HTTP 동시 실행은 하지 않았다.

## 3. P1: Planner failure JSON becomes a successful empty plan

기존 오류 감지 공백. `sasoo/backend/services/analysis_execution.py:2712`는 JSON 파싱 성공만 검사한다. 상위 호출의 _parse_error 응답은 유효한 JSON이어서 정규화 결과 []로 통과한다. 실제 _plan_visualizations 모의 실행에서 불완전 응답 오류를 넣어도 예외 없이 []가 반환됐다. 후속 생성은 빈 결과를 완료로 저장할 수 있다. 파싱 전 오류 봉투와 응답 완료 상태를 검사해야 한다.

## 4. P1: Failed image/HTML items are reused as a completed cache

기존 완료 캐시 정책이 새 HTML에도 적용된다. `sasoo/backend/services/analysis_execution.py:3297`는 complete만 보고 항목 status를 확인하지 않는다. 실제 _run_visualizations 모의 실행에서 실패 이미지/HTML 두 개를 complete=true로 반환하자, 더미 키가 있어도 계획/이미지/HTML 생성 0회, 반환 상태 error/error, 진행률 100이었다. 일시 오류에서 회복하거나 키를 추가해도 같은 캐시 조건의 재분석은 실패를 재사용한다. 완료 여부와 항목 성공 여부를 분리하고 실패 항목을 재시도해야 한다.

## 5. P2: Missing illustrations bypasses the new count and score gates

새 혼합 규칙의 호환 경로 예외. `sasoo/backend/services/analysis_execution.py:2503`에서 illustrations 존재 여부만으로 분기한다. 필드가 누락된 모델 응답은 옛 method 3 / result 2 규칙으로 처리된다. 실제 계획 처리 함수에 중요도 0인 Mermaid 목록을 주어 5개 수락을 재현했다. 정상 혼합 과다 입력은 5/3/1, Sunburst 1로 잘렸다. 새 생성 응답은 새 스키마를 필수 검증하고 생성 직전에 공통 상한/중요도 검사를 해야 한다.

## 6. P2: Same-paper reanalysis is hidden by a stale local override

기존 프런트엔드 상태 문제. `sasoo/frontend/src/components/VisualizationGallery.tsx:98`의 override는 항목 id만 사용하고 새 분석 계획에서 초기화되지 않는다. `sasoo/frontend/src/components/synthesis/SynthesisView.tsx:66`는 override를 무조건 우선한다. 실제 hook을 React/jsdom에서 실행해 old plan -> regenerate -> new backend plan 순서를 주면 표시 제목은 regenerated old plan이었다. 새 그림/HTML/모델/비용이 옛 항목으로 가려지고 ZIP 대상에도 영향을 줄 수 있다. 계획의 실행 정체성으로 상태를 분리해야 한다. 논문 전환은 부모가 종합 화면을 해제하므로 이 보고서의 발생 조건은 같은 논문의 재분석이다.

## 7. P2: HTML is completed without execution or numerical checks

신규 HTML 경로. `sasoo/backend/services/analysis_execution.py:2898`는 script와 조작 태그 존재 여부 등만 검사한다. 실제 _generate_single_html 모의 호출에 JavaScript 문법 오류와 y=2*x의 검산 실패 HTML을 넣어도 둘 다 반환됐고, 파이프라인 :3374는 completed로 표시한다. iframe 오류 문구는 서버 상태를 고치지 않으며 console.assert 실패는 error 이벤트와 다르다. 별도 실행 환경에서 문법/실행 오류와 주어진 수치 검산을 확인하고 검사 범위를 표시해야 한다. 임의 논문의 과학적 정확성을 자동 보장할 수 있다는 뜻은 아니다.

## 8. P2: Paid Mermaid and image-description calls are omitted from accounting

기존 비용 누락 구조. `sasoo/backend/services/analysis_execution.py:2799`의 Mermaid 생성과 `sasoo/backend/services/viz/figure_gen.py:123`의 이미지 설명 생성은 응답 텍스트만 반환하고 사용량/비용을 버린다. 이미지 결과 비용은 렌더 호출만 포함하고 phase 합계 :2919는 항목 비용만 합친다. 비용 API는 analysis_results 합계를 사용한다. 각 요청의 사용량과 비용을 별도 기록하고 집계해야 한다. 실제 공급사 청구서 대조는 하지 않았다.

## 9. P2: Regeneration keeps stale known costs and aggregate completeness

기존 이미지 갱신 문제와 새 HTML 재생성 경로. `sasoo/backend/api/analysis_routes.py:789`는 새 이미지 비용이 None이면 필드 갱신에서 제외해 옛 비용을 유지한다. 실제 updater 모의 실행에서는 HTML 항목 비용이 null로 바뀌어도 행 cost_usd=.04, cost_incomplete=false가 유지됐다. updater :655는 JSON만 변경한다. 미확인 비용을 명시적으로 덮어쓰고 재생성 요청 비용을 별도 누적하며 합계/미확인 상태를 함께 갱신해야 한다.

## 10. P2: Unknown costs appear as zero without an incomplete indicator

기존 비용 표시가 새 시각화의 null 비용 계약을 반영하지 않는다. `sasoo/backend/api/settings.py:522`와 :619 등은 cost_usd=None을 0.0으로 합친다. 응답/프런트엔드에 cost_incomplete 표시 계약이 없다. 실제 get_cost_summary 모의 실행에 미확인 시각화 비용 한 행을 넣자 논문 비용과 총비용이 모두 0.00이고 미확인 표시도 없었다. 알려진 비용 합계와 미확인 요청 수를 함께 반환하고 화면에서 불완전한 합계임을 표시해야 한다.

## Evidence limits

공개 릴리스나 제품 코드는 변경하지 않았다. 검토 보고서만 추가했다. 실제 모델 응답의 실패 빈도, 공급사 청구서, 전체 Electron에서의 동시 재분석/재생성은 확인하지 않았다. 내보낸 HTML의 탐색 가능성과 실패 상태/비용 계약은 독립 브라우저 또는 실제 함수 모의 실행으로 확인했다.
