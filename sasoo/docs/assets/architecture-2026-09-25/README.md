# Sasoo diagrams / 도식

Archify 2.17로 만든 README용 시각 자료입니다. SVG는 README에 표시하고, HTML은 내려받아 브라우저에서 열어 검색/확대/연결 탐색에 사용합니다. PNG도 함께 제공합니다. GitHub의 HTML 파일 보기 자체는 대화형 뷰어를 실행하지 않습니다.

| 도식 | 한국어 | English |
| --- | --- | --- |
| 논문 읽기 workflow | [SVG](reading-workflow.ko.svg), [HTML](reading-workflow.ko.html) | [SVG](reading-workflow.en.svg), [HTML](reading-workflow.en.html) |
| 기술 구성 | [SVG](system-architecture.ko.svg), [HTML](system-architecture.ko.html) | [SVG](system-architecture.en.svg), [HTML](system-architecture.en.html) |
| 주요 분석 단계 | [SVG](analysis-pipeline.ko.svg), [HTML](analysis-pipeline.ko.html) | [SVG](analysis-pipeline.en.svg), [HTML](analysis-pipeline.en.html) |

한국어 설명은 한국어로 작성했지만, 고정 Viewer UI와 HTML 언어 속성은 Archify의 지원 범위에 따라 영어입니다. 영문 도식도 같은 연결 관계를 설명합니다.

## 근거와 범위

- Electron과 프런트엔드 구성: [main.ts](../../../electron/main.ts), [package.json](../../../frontend/package.json).
- 로컬 API와 논문 분석: [analysis_routes.py](../../../backend/api/analysis_routes.py), [analysis_execution.py](../../../backend/services/analysis_execution.py).
- PDF 문맥과 추출: [odl_parser.py](../../../backend/services/odl_parser.py).
- 로컬 저장: [database.py](../../../backend/models/database.py).
- 외부 공급사 배정: [model_registry.py](../../../backend/services/model_registry.py).

선은 구성 요소 사이의 주요 관계를 요약합니다. 생략한 응답 경로, 오류 분기, 캐시 조회와 내부 호출이 있으므로 완전한 호출 그래프나 런타임 실행 증거로 해석하지 않습니다. 분석 단계 사이의 무표기 화살표는 실행 순서를 나타내며, 개별 단계의 성공을 보장하지 않습니다.

Graphify로 앱 소스 294개와 문서 16개를 분석해 4,997개 노드, 11,023개 연결, 255개 커뮤니티를 추출했습니다. 생성 이미지/도식과 번들 Java 문서는 제외했습니다. `run_full_analysis()`의 호출 관계를 코드 위치와 대조해 주요 분석 순서를 확인했습니다. [코드 관계 지도](../../../../graphify-out/graph.html)와 [추출 보고서](../../../../graphify-out/GRAPH_REPORT.md)를 함께 제공합니다. 원시 추출에는 연결 대상 누락 678건, 자기 연결 26건, 무방향 그래프 병합 318건의 경고가 있어 완전한 호출 그래프로 해석하지 않습니다.

## 검증

[validation.json](validation.json)에 각 원본 명세, HTML, SVG, PNG의 SHA-256과 검증 범위를 기록했습니다.

- 한영 6개 HTML: Archify showcase 검증 9/9, composition 오류/경고 0건.
- 각 HTML: 1440×900, 1600×1000, 1920×1080, 2048×1320 실제 Chrome 검사에서 문서 가로/세로 넘침 없음.
- 양 끝 크기의 밝은/어두운 테마 캡처를 확보하고, 도식별 실제 렌더를 시각 검토했습니다. `browser_evidence`와 `visual_review`는 별도 판정입니다.
- SVG/PNG는 확정된 HTML의 Export 기능으로 생성했습니다. 생성 후 HTML을 직접 수정하지 않았습니다. SVG는 CSS의 행 끝 공백만 정리했으며 원본/정리본 해시를 기록했습니다.

These are documentation diagrams built with Archify. Download an HTML file and open it in a browser for search, zoom, and connection exploration. GitHub's HTML source view does not run the viewer. SVGs are embedded in the READMEs; PNGs are also provided.

Both authored languages use English viewer controls. Source files above ground the main relationships; omitted return paths, error branches, caches, and internal calls mean these diagrams are not complete call graphs or runtime evidence. Unlabeled pipeline arrows express stage order, not guaranteed success.

Graphify analyzed 294 source files and 16 documents, yielding 4,997 nodes, 11,023 edges, and 255 communities. Generated visuals and bundled Java material were excluded. The main analysis sequence was checked against the extracted calls and source locations of `run_full_analysis()`. Raw extraction has 678 dangling-endpoint edges, 26 self-loops, and 318 same-endpoint collapses in the undirected graph; it is a navigation aid rather than a complete call graph. Deterministic validation, automated browser evidence, perceptual review, and exported images are recorded separately in the manifest.


Archify 뷰어 코드의 라이선스는 [ARCHIFY-LICENSE.txt](ARCHIFY-LICENSE.txt)에 포함했습니다. 이 파일은 Sasoo 프로젝트 전체의 라이선스를 새로 정하는 문서가 아닙니다.

The generated viewer uses Archify code under the included MIT license notice. This notice does not establish a license for the entire Sasoo project.
