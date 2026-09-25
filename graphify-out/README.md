# Sasoo code graph

[Interactive graph](graph.html) / [Extraction report](GRAPH_REPORT.md) / [Raw graph](graph.json)

앱 소스 294개와 문서 16개에서 추출한 코드 탐색 자료입니다. 생성 이미지/도식, 로고, 번들 Java 문서는 [scope.json](scope.json)의 규칙으로 제외했습니다. 테스트와 개발 도구가 포함돼 있으므로 연결 수가 많은 노드를 곧바로 프로덕션 핵심 경로로 해석하지 않습니다.

- 노드 4,997개, 연결 11,023개, 커뮤니티 255개.
- 코드 구조는 AST로, 문서의 의미 관계는 호스트 에이전트로 추출했습니다. 별도 모델 API 호출은 없었습니다. 호스트 토큰/비용은 도구가 제공하지 않아 [cost.json](cost.json)에 미확인으로 기록했습니다.
- 원시 추출 경고: 연결 대상 누락 678건, 자기 연결 26건, 무방향 그래프의 같은 endpoint 병합 318건. 이를 숨기거나 완전한 호출 그래프로 표시하지 않습니다.
- [community-metrics.json](community-metrics.json)에 커뮤니티 응집도 원시 값을 보존했습니다.
- [benchmark.txt](benchmark.txt)의 13.7배 수치는 Graphify의 휴리스틱 토큰 추정입니다. 실제 API 청구액이나 응답 시간 개선을 측정한 결과가 아닙니다.

HTML을 내려받아 브라우저에서 열면 노드 검색과 커뮤니티별 탐색을 사용할 수 있습니다. 시각화 라이브러리는 고정 버전 CDN에서 불러오므로 최초 실행에는 인터넷 연결이 필요합니다. 1440×900 Chrome에서 canvas 표시, 가로 넘침 없음, JavaScript 오류 없음이 확인됐습니다.

## Diagram cross-check

Graphify의 `run_full_analysis()` 노드(`backend/services/analysis_execution.py:L3296`)는 다음 호출을 연결합니다.

| 단계 | 코드 위치 |
| --- | --- |
| 스크리닝 | `_run_screening`, L3356 |
| 인용 분석 | `_run_citation`, L3459 |
| 시각 자료 분석 | `_run_visual`, L3476 |
| 레시피 추출 | `_run_recipe`, L3510 |
| 심층 분석 | `_run_deep_dive`, L3556 |

이 순서를 소스와 다시 대조해 README의 Archify 분석 파이프라인에 반영했습니다. 문맥 준비의 간접 호출은 Graphify에서 INFERRED로 분류되므로 직접 호출과 구분합니다. 그래프의 관계는 런타임 실행이나 과학적 정확성의 증거가 아닙니다.

This graph covers 294 source files and 16 documents. It includes tests and development tools, so connectivity is not a measure of production criticality. Generated media and bundled Java material were excluded. Extraction gaps and undirected edge collapse are recorded above and in the report.

Structural extraction used an AST; semantic extraction used the host agent without an external model API. Actual host token usage and cost were unavailable. The benchmark is a heuristic estimate, not a measured billing or latency improvement. Download the HTML to explore it; the pinned visualization library requires internet access on initial load.


Graphify의 배포 고지는 [GRAPHIFY-NOTICE.txt](GRAPHIFY-NOTICE.txt), 라이선스는 [Apache 2.0](GRAPHIFY-LICENSE.txt)과 [이전 MIT 기여분](GRAPHIFY-LICENSE-MIT.txt)에 보존했습니다. Sasoo 전체의 라이선스 선언을 대신하지 않습니다.
