# Sasoo 적용을 위한 2026년 10월 이후 agentic research 조사

조사일: 2026-11-03. 범위: 2026-10-01~2026-11-03의 신규 GitHub 워크플로우와 이 기간 처음 제출된 관련 arXiv 논문. 코드 실행/설치/유료 모델 평가 없음.

## 순위 해석

GitHub REST API의 누적 `stargazers_count`를 사용했다. 검색어는 `research agent`, `deep-research`, `scientific`에 생성일 범위와 `archived:false`를 붙였으며 stars 내림차순 결과를 검토했다. 논문의 공식 코드 링크도 추가 확인했다. 과학 연구/심층 조사 실행 흐름이 있는 후보를 선별하고 일반 OS, 마케팅, 금융, 족보 조사, 단순 목록/그림 생성 도구를 제외했다.

아래는 발견하고 직접 확인한 후보 내 순위다. 전 세계 전체 저장소의 완전한 순위, GitHub Trending 순위, 10월 스타 증가량이 아니다. arXiv 공개 페이지에서는 일관된 인기/다운로드 지표를 확보하지 못했으므로 논문 인기 순위를 만들지 않았다. 별도 논문 목록의 순서는 Sasoo 적용 판단이다.

관찰 시각과 메타데이터는 [snapshot JSON](2026-11-03-agentic-research-snapshot.json)에 저장했다. 스타는 변한다. 저장소 생성일은 코드/방법론의 최초 개발일을 보장하지 않는다. README 주장은 독립 검증 결과가 아니다.

## 10월 이후 신규 저장소: 후보 내 누적 스타 순

| 순위 | 저장소 | 생성일 UTC | 스타 | 확인한 방법과 Sasoo 적용 판단 |
| --- | --- | --- | ---: | --- |
| 1 | [AI-Scientist-v3](https://github.com/SakanaAI/AI-Scientist-v3) | 10-11 | 607 | 단계별 연구/실험/검증/보고. 단계 산출물과 종료 상태만 우선 참고한다. |
| 2 | [ResearchBoost-Agent](https://github.com/DAGroup-PKU/ResearchBoost-Agent) | 10-18 | 208 | 고정 평가 기준으로 profile/edit/measure/check를 반복. Sasoo 평가 조건 동결에 참고한다. |
| 3 | [Agent-Cockpit](https://github.com/chutingyean/Agent-Cockpit) | 10-26 | 207 | 주장, 실행, 코드 hash의 근거 연결과 stale 전파. 원문/결과/검증 버전 연결에 적합하다. |
| 4 | [OneSearch-VL](https://github.com/appletea233/OneSearch-VL) | 10-08 | 193 | 시각 근거 그래프와 evidence-aware 학습. 그림의 패널/영역/페이지 근거만 참고하고 학습 시스템 도입은 보류한다. |
| 5 | [Research-Assistant-Agent](https://github.com/zzp1221/Research-Assistant-Agent) | 10-23 | 115 | 산출물 manifest, 주장별 근거, partial/needs_review 등 결과 상태. 완료 계약과 내보내기 추적에 참고한다. |
| 6 | [BetterSearch](https://github.com/ry0narushima/bettersearch) | 10-18 | 40 | 조사/검토와 제한된 후속 라운드, 출처 상태 표시. 검증 루프 상한에 참고한다. |
| 7 | [deep-research-langgraph](https://github.com/weir36/deep-research-langgraph) | 11-02 | 35 | SQLite checkpoint, 의존 병렬화, 요청 예산. 프레임워크 이식 없이 경쟁 조건/재시작 테스트를 참고한다. |
| 8 | [GnosisLab](https://github.com/cloudcell/gnosislab) | 10-02 | 21 | 가설→실험→관찰→근거→주장→결론의 구조화. 사용자 실험 기록의 상태 분리에 참고한다. |
| 9 | [MatOS](https://github.com/DingyangLyu/MatOS) | 10-25 | 12 | 상태 있는 과학 실행 그래프, 체크, 실행 기록과 자산 버전. 재개/부분 실행 원칙에 적합하다. |
| 10 | [PANINI-DR](https://github.com/roychowdhuryresearch/panini-dr) | 10-16 | 4 | 하위 질문과 근거를 검증한 뒤 상태에 채택. 단일 논문의 근거 점검 흐름에 적합하다. |

메타데이터는 `gh api repos/{owner}/{repo}`로 조회했다. 구현 방식은 공식 README와 아래 논문에서 확인했다. 라이선스 파일을 포함한 상세 코드 감사, 실행 재현, 공급사 비용 비교는 하지 않았다.

## 10월 이후 arXiv 방법론: Sasoo 적용 우선순위

1. [PANINI-DR](https://arxiv.org/abs/2610.15208), 최초 10-10, v2 10-16. 질문/의존 관계/근거를 상태로 기록하고 제안된 답을 채택 전 점검한다. Sasoo에서는 레시피 수치 대조, 불충분한 근거의 명시, 후속 종합에서의 근거 상태 전달로 옮긴다. 검토 모델의 동의는 과학적 증명이 아니다.
2. [The Agentic Scientist](https://arxiv.org/abs/2610.18933), 최초 10-13. 연구를 단계로 나누고 rubric 기반 점검을 수행한다. Sasoo는 기존 분석 단계와 설명 계약을 유지하면서 산출물 존재/완료 상태를 확인하는 데 활용한다.
3. [MatOS](https://arxiv.org/abs/2610.34203), 최초 10-25. 명시적인 과학 실행 그래프와 상태/산출물을 저장한다. Sasoo는 입력 signature, 단계 결과 연결, 부분 실패와 재시작 정합성만 도입한다. 자율 그래프 수정과 스킬 자동 진화는 제외한다.
4. [OpenSaC](https://arxiv.org/abs/2610.25779), 최초 10-19. 검색/읽기/정리를 코드로 조합하고 관찰 증거를 유지한다. 연결 저장소 [OpenSaC](https://github.com/liuqi6777/OpenSaC)는 4스타, 08-18 생성이라 신규 저장소 순위에는 포함하지 않았다. Sasoo에서는 고정된 Python 서비스의 독립 조회 묶음만 참고한다.
5. [Épi](https://arxiv.org/abs/2610.24944), 최초 10-18. 세션을 넘는 상태, 계층 메모리, 버전 보존과 독립 검토를 제안한다. 연결 [Epi-results](https://github.com/BakeLab/Epi-results)는 12스타, 09-07 생성이며 결과 아카이브다. 전체 실행 엔진 공개로 오인하지 않는다. Sasoo는 저장된 결과 보존과 복원 원칙만 참고한다.
6. [Optimist Deep Research](https://arxiv.org/abs/2610.23299), 최초 10-16. 구조화된 주장/위치/근거 저장과 다음 조사 행동을 제안하는 critic을 사용한다. [공식 저장소](https://github.com/gihanpanapitiya/optimist_research)는 0스타다. Sasoo에서는 한 논문 내 누락 조건/충돌을 사용자 확인 목록으로 제시한다. 문헌 전체 검색 확장은 보류한다.
7. [Humanize Olympiad Agents](https://arxiv.org/abs/2610.13632), 최초 10-09. 독립 reviewer, wiki와 formal verifier를 결합한다. [공식 코드](https://github.com/humanfia/hoa)는 19스타, 07-20 생성이라 신규 저장소 순위에서 제외했다. 수학의 formal verification 성공을 일반 논문 해설의 의미 정확성과 동일시하지 않는다.
8. [Principles and Techniques for Agentic Research in Experimental Physics](https://arxiv.org/abs/2610.17193), 최초 10-12. 사람 중심 연구와 명확한 목표의 반복 캠페인을 다룬다. 광학/실험 재현이라는 기존 제품 방향에 참고하되 하드웨어 검증이나 자동 실험을 이번에 추가하지 않는다.

## 적용 결론

현재 선택은 근거 연결, 오래된 결과 표시, 단계별 완료 계약, 읽기/실행 상태 분리, 요청 전 예산 확보다. 여러 에이전트나 새 프레임워크의 수를 성공 지표로 삼지 않는다. 기존 고정 분석 항목과 깊이를 유지하며 독립 작업에만 제한 병렬화를 적용한다.

사용자가 제외한 논문 간 비교와 그 API/스키마는 구현하지 않는다. 논문들을 자동 수집해 합성하는 워크플로우도 이번 계획의 필수 단계로 두지 않는다. 상세 파일/작업/검증 계획은 [적용 계획서](../superpowers/plans/2026-11-03-sasoo-research-workflow-application.md)에 있다.

## 재현 방법과 한계

```bash
gh api -X GET search/repositories -f q='research agent created:2026-10-01..2026-11-03 archived:false' -f sort=stars -f per_page=20
gh api -X GET search/repositories -f q='deep-research created:2026-10-01..2026-11-03 archived:false' -f sort=stars -f per_page=15
gh api -X GET search/repositories -f q='scientific created:2026-10-01..2026-11-03 archived:false' -f sort=stars -f per_page=20
gh api repos/SakanaAI/AI-Scientist-v3
```

검색어 불일치, 검색 상위 건수 제한, 비공개 상태 또는 공개 직후 색인 지연으로 빠진 후보가 있을 수 있다.따라서 표는 재현 가능한 후보군의 관찰값이며 완전한 인기 지표가 아니다. 공개 초록/README와 확인한 방법론 부분을 읽었고 모든 논문 전문의 독립 심사를 수행한 것은 아니다. 논문별 벤치마크는 서로 다른 과제이므로 합산하지 않았다. 스타/논문 공개일/실행 품질/Sasoo 적합도는 각각 별개다.
