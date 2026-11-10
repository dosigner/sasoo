# Sasoo 폼 디자인 원칙: Apple macOS 27 Forms 참고

상태: 2026-09-24 설정 화면과 워크벤치 6개 탭에 적용한 디자인 기준. 기존 토큰을 재사용하며 새 팔레트를 확정하지 않았다. [개발 Electron 검증](../../../docs/validation/2026-09-24-forms-tabs-app.md)과 함께 본다.

## 1. 관찰한 기준 화면

- [Sketch Forms Light](https://www.sketch.com/s/57153a31-3379-4737-8ac6-dbfd6525f052/f/4AE1E021-E925-4252-B06B-B177E62C1BBE), [Sketch Forms Dark](https://www.sketch.com/s/57153a31-3379-4737-8ac6-dbfd6525f052/f/195290DC-9BD4-4911-B536-EBAEE8A9E2BD): 같은 행 구조와 컨트롤을 밝고 어두운 표면에서 비교했다.
- [Sketch Materials](https://www.sketch.com/s/57153a31-3379-4737-8ac6-dbfd6525f052/f/1615B3DA-4DCA-4315-94DC-6EE1BBA09A1F): Liquid Glass를 별도 재질 예제로 제시한다. Forms 예제의 입력 창 자체는 불투명하다.
- Sketch Inspect 실측: 예제 창은 500 × 682px, 안쪽 여백 20px, 모서리 26px이다. 내부 Form은 460px 폭, 모서리 12px, 밝은 모드에서 검정 3% 필, 어두운 모드에서 흰색 3% 필이다. 기본 행은 40px 높이, 구분선은 해당 전경색 5%이다.
- Sketch Inspect 실측: 예제 창 표면은 밝은 모드 `#FFFFFF`, 어두운 모드 `#1E1E1E`이다. 창 그림자는 `0 0 1px #000/80%`와 `0 36px 100px #000/40%`를 겹친다. 이는 배경 이미지 위에 떠 있는 **예제 창**의 값이지 Sasoo 전체 카드에 적용할 그림자 값이 아니다.
- Sketch Inspect 실측: 행 제목은 SF Pro Medium 13px/16px, 보조 문구는 SF Pro Medium 11px/14px이다. macOS 샘플의 수치로 기록하고 Sasoo의 한글 폰트와 밀도에 그대로 이식하지 않는다.

## 2. 핵심 원칙

1. **읽고 입력하는 면은 안정적으로 유지한다.** 설정 폼, 논문 본문, 결과, 표와 긴 설명에는 `bg` 또는 `surface`의 불투명한 배경을 쓴다. 배경 이미지, 강한 반사, 투명도가 글자 뒤를 지나가지 않게 한다.
2. **재질은 역할을 나타낸다.** Liquid Glass는 내용 위에 떠서 탐색이나 주요 조작을 맡는 표면에만 고려한다. Sasoo에는 별개의 macOS OS vibrancy가 사이드바와 타이틀바에 이미 있으므로 같은 역할 구분을 적용한다. 필요한 경우 저장바와 팝오버도 떠 있는 조작층으로 다룬다. 폼 행마다 blur를 주지 않는다. [Apple Materials](https://developer.apple.com/design/human-interface-guidelines/materials)도 콘텐츠층과 떠 있는 조작층을 구분한다.
3. **색보다 구조가 먼저다.** 항목의 순서, 정렬, 여백, 제목과 설명의 관계로 위계를 만든다. 브랜드 퍼플은 선택, 포커스, 주 행동에 사용한다. 의미가 없는 장식에 퍼플을 반복하지 않는다.
4. **겹치는 재질을 피한다.** OS vibrancy 위에 `backdrop-filter`를 다시 걸거나 반투명 팝오버 안에 반투명 카드를 넣으면 경계가 흐려진다. 기본은 단일 재질층, 그 위의 컨트롤은 불투명한 필과 명확한 전경을 쓴다.
5. **빛 효과보다 상태의 진실성이 우선이다.** 포커스, 오류, 저장 중, 저장 실패, 비활성, 완료를 색만으로 구분하지 않는다. 진행과 실패를 실제 상태에 연결한다.

여기서 Liquid Glass는 사용자의 “liquid crystal design”을 Apple의 현재 재질 이름으로 해석한 것이다. 웹 CSS blur는 광학적 굴절과 환경 적응을 재현하지 못하므로 Sasoo에서는 **재질의 배치 원칙**을 따른다. Apple의 예제 이미지와 아이콘 자산은 가져오지 않는다.

## 3. Sasoo에 적용할 시스템

색상값은 [현행 디자인 토큰](design-tokens.md)을 따른다. 폼 작업에서 가장 자주 고르는 값은 아래와 같다.

| 용도 | 밝음 | 어두움 |
| --- | --- | --- |
| 페이지 `bg` | `#F7F7F8` | `#0A0A0B` |
| 읽는 면과 입력 `surface` | `#FFFFFF` | `#17171A` |
| 행 hover `surface-hover` | `#EFEFF1` | `#202024` |
| 본문 `fg` | `#18181B` | `#F4F4F5` |
| 선택과 포커스 `accent` | `#683DCC` | `#9E82FA` |

어두운 모드의 `accent` 위에는 흰 글자 대신 기존 `accent-solid-fg`의 어두운 글자를 쓴다. 기존 명세에서 흰 글자는 2.99:1로 기록되어 있다. 반투명 필과 blur의 대비는 토큰 값만 보고 합격 처리하지 않는다.

| 항목 | 규칙 | 현재 구현의 기준점 |
| --- | --- | --- |
| 색상 | 기존 밝음/어두움 시맨틱 토큰을 단일 소스로 사용한다. 배경 `bg`, 읽는 카드와 입력 `surface`, 행 hover와 묶음 `surface-hover`, 구분 `border`, 본문 `fg`, 설명 `fg-secondary` 또는 `fg-muted`다. 선택과 주 행동은 `accent`, 오류와 경고와 성공은 각각의 상태 토큰이다. | [design-tokens.md](design-tokens.md), `frontend/src/index.css`의 `:root`와 `.dark` |
| 레이아웃 | 설정은 폭 최대 44rem의 한 열로 읽는다. 구획 간 16px, 카드 안 여백 16px 또는 20px을 유지한다. 한 줄 행은 왼쪽에 라벨과 설명, 오른쪽에 컨트롤을 두고, 내용이 길거나 폭이 부족하면 컨트롤을 다음 줄의 전체 폭으로 내린다. 행 기준 높이는 40px 이상이다. | `page-container-settings`, `SettingSection`, `SettingRow` |
| 모서리 | 일반 입력과 버튼은 `radius-control` 6px, 카드와 팝오버는 `radius-surface` 12px, 토글과 pill은 `radius-pill`을 쓴다. Sketch의 26px 예제 창 모서리를 일반 카드에 복제하지 않는다. | [design-tokens.md](design-tokens.md)의 radius 3종 |
| 글꼴 | Pretendard Variable을 유지한다. 페이지 제목은 기존 hero 스타일, 구획 제목 13px/20px 600, 폼 라벨 13px/20px 500, 설명 12px/16px 400, 긴 본문 15px/22px 400을 기준으로 한다. 11px은 짧은 메타데이터에만 쓴다. 숫자와 단위는 함께 읽히게 하고 줄바꿈 시 관계를 유지한다. | `text-2xs`부터 `text-lg`까지의 기존 스케일 |
| 그림자 | 같은 층의 행과 카드에는 그림자를 주지 않는다. 선택된 세그먼트는 기존 `shadow-xs`, 팝오버와 모달은 기존 `shadow-lg`처럼 **떠 있는 경우**에만 높이를 준다. 창 예제의 `36px/100px` 그림자를 설정 카드로 옮기지 않는다. 어두운 모드에서는 테두리와 표면 차이도 함께 확인한다. | `SegmentGroup`, `Popover`, `Modal`, `SaveBar` |
| 아이콘 | 기존 `AppIcon`의 Lucide 계열과 `--icon-stroke: 1.7`을 유지한다. 행 안의 기본 크기는 16px, 촘촘한 보조 동작은 14px로 맞추고 라벨과의 간격은 4px 또는 8px을 쓴다. 아이콘만 있는 버튼에는 접근 가능한 이름과 충분한 클릭 영역을 준다. 정보, 펼침, 더 보기, 삭제는 같은 의미에 같은 기호를 쓴다. | `frontend/src/components/icons/AppIcon.tsx` |
| 움직임 | hover와 열림 전환은 기존 150ms 기준, 최대 200ms로 제한한다. 키보드 제출의 응답은 즉시 보이고 `prefers-reduced-motion`을 따른다. 흐릿함이나 움직임이 상태 정보를 대신하지 않는다. | [design-tokens.md](design-tokens.md)의 모션 원칙 |

### 재질 적용 순서

| 층 | Sasoo의 대상 | 처리 |
| --- | --- | --- |
| 콘텐츠 | 설정 폼, PDF, 분석 답변, 표, 레시피 | 불투명 `bg`/`surface`. 텍스트와 입력의 대비를 고정한다. |
| 묶음 | 설정 구획, 항목 행, 세그먼트 트랙 | `surface-hover`와 얇은 `border`로 관계를 표시한다. blur와 큰 그림자는 쓰지 않는다. |
| 떠 있는 조작 | 사이드바, 타이틀바, 저장바, 팝오버, 일시적 도구 | macOS에서는 이미 있는 OS vibrancy와 제한적인 알파 틴트를 활용한다. 웹 표면은 기존 blur 유틸을 한 번만 적용한다. |
| 강조 | 주 버튼, 선택값, 포커스 링, 상태 메시지 | `accent` 또는 해당 상태색과 텍스트/아이콘을 함께 쓴다. |

## 4. 폼 상태 규칙

- **기본/hover:** 밝음과 어두움 모두 라벨과 값의 우선순위가 같아야 한다. hover는 `surface-hover`처럼 국소적인 명도 변화로 나타낸다.
- **키보드 포커스:** 모든 입력과 버튼에 2px `accent` `focus-visible` 링을 준다. 오류를 동반한 파괴 동작만 `danger` 링을 쓴다.
- **선택/비활성:** 라디오와 토글의 선택은 색과 체크/손잡이 위치로 보인다. 비활성은 클릭할 수 없는 상태와 보조 문구가 일치해야 한다.
- **검증 오류:** 해당 필드 가까이에 원인과 수정 방법을 텍스트로 쓴다. `danger` 색만 쓰거나 빈 값을 성공처럼 보이게 하지 않는다.
- **저장 중/성공/실패:** 저장 중에는 조작을 막고 진행 상태를 보인다. 성공하면 기존 `SaveBar`가 사라지는 피드백을 유지한다. 실패하면 저장바와 원인 및 재시도 동작이 남는다.
- **접근성:** 투명도 축소 시 떠 있는 표면을 불투명하게 돌린다. 실제 배경 합성 후 일반 텍스트 대비 [4.5:1](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum), 의미 있는 아이콘/컨트롤 경계 [3:1](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast)을 확인한다. 밝음, 어두움, 대비 증가 환경을 따로 본다.

## 5. 적용 확인 기준

1. `Settings`에서 1400 × 900과 Electron 최소 창 크기 1024 × 680을 확인한다. 긴 한국어 라벨, 도움말, 오류 메시지, 긴 파일 경로가 컨트롤과 겹치지 않아야 한다.
2. 밝음과 어두움에서 기본, hover, 키보드 포커스, 선택, 비활성, 저장 중, 저장 실패를 실제로 조작한다. 색상값 검사는 투명 표면의 최종 합성 픽셀을 기준으로 한다.
3. macOS 사이드바, 타이틀바, 저장바와 팝오버를 함께 띄워 blur가 두 번 중첩되지 않는지 본다. 투명도 축소 및 움직임 축소 환경에서도 조작과 상태가 읽혀야 한다.
4. `Settings`가 쓰는 기존 시맨틱 토큰과 `AppIcon`을 재사용했는지 확인한다. 새 팔레트, 새 폰트, 별도 아이콘 라이브러리는 이 원칙의 적용 조건이 아니다.

참고: [Apple Materials](https://developer.apple.com/design/human-interface-guidelines/materials), [Apple Layout](https://developer.apple.com/design/human-interface-guidelines/layout), [Apple Typography](https://developer.apple.com/design/human-interface-guidelines/typography), [Apple Color](https://developer.apple.com/design/human-interface-guidelines/color). Apple UI Kit의 픽셀 값은 관찰 근거이며 Sasoo의 토큰과 UI 계약이 우선한다.
