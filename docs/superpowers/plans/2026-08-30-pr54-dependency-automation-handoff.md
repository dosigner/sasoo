# 인수인계: PR #54 의존성 자동 갱신 병합 준비

작성: 2026-08-30. 대상: 다음 세션.

## 목표

열려 있는 마지막 PR **#54**(`chore/dependency-automation`, DEC-015)를 병합 가능한 상태로 만든다. 브랜치가 2026-08-18에 멈춰 있고 그 사이 main에 #55·#57·#58·#59·#60·#61·#62가 들어가 충돌 상태(CONFLICTING)다.

**병합 자체는 하지 말 것.** 에이전트는 병합·publish 불가가 이 저장소의 가드레일이다. 준비가 끝나면 사용자가 `! gh pr merge 54 --squash`를 실행한다.

## 조사 완료된 현재 상태 (2026-08-30 확인)

| 항목 | 값 |
|---|---|
| 열린 PR | **#54 하나뿐** (#55·#59·#60·#61·#62는 병합 완료) |
| 병합 상태 | `CONFLICTING` / `mergeStateStatus: DIRTY` |
| 충돌 파일 | **`sasoo/frontend/src/index.css` 1개뿐** — 나머지 115파일은 자동 병합 |
| main 반영 여부 | **전무.** `sasoo/pnpm-workspace.yaml`, `.github/workflows/dependency-audit.yml`, `renovate.json` 셋 다 main에 없다 |
| 작업 필요성 | 유효. main의 `sasoo/package.json`에 `pnpm.overrides` 32건이 그대로 있다 |
| 현재 pnpm | 10.32.1 (아직 `pnpm.overrides`를 읽으므로 지금은 작동한다) |

충돌 계산은 `git merge-tree --write-tree --name-only origin/main origin/chore/dependency-automation`으로 확인했다(실제 병합 없이 계산만 하는 명령이라 반복해도 안전하다).

## 왜 이 PR이 여전히 필요한가

pnpm **v11부터 `package.json`의 `pnpm` 필드를 읽지 않는다.** 실측 기록으로는 pnpm 11로 설치하면 lockfile의 `overrides:` 블록이 통째로 사라지고 32건이 전부 조용히 무시된다(shell-quote가 강제값 1.10.0 대신 1.9.0으로 내려갔다). #54가 그 override를 `pnpm-workspace.yaml`로 옮기는 작업이다. 지금 pnpm 10에서는 문제가 안 드러나므로 **"아직 잘 되는데 왜 하냐"는 판단을 하지 말 것.**

## 작업 단계

### 1. 별도 worktree에서 시작

사용자 작업 트리(`/Users/dongj/dev/논문_사수_개발중`)는 다른 세션이 v1 design 작업으로 쓰고 있다. 브랜치가 수시로 바뀌므로 **거기서 브랜치를 전환하지 말 것.** `EnterWorktree`로 격리하고, `chore/dependency-automation`을 체크아웃해 최신 main을 병합한다.

### 2. `index.css` 충돌 해소

main 쪽 변경이 우선이다. #62가 "소비처 없는 CSS 155줄 정리"를 했고 #60·#61이 vibrancy와 컴포넌트 정비를 넣었다. **#54 브랜치의 옛 CSS로 그것들을 덮지 말 것.** #54가 이 파일에서 하려던 것은 tailwind 관련 최소 변경이므로, main 쪽을 기준으로 두고 #54의 의도만 얹는다.

### 3. lockfile 재생성과 override 목록 재검토 ← 실제 부담

**여기가 이 작업의 본체다.** 자동 병합된 lockfile은 문법만 맞을 뿐 유효하다는 보장이 없다.

```
cd sasoo && pnpm install     # --frozen-lockfile 없이. lockfile을 새로 만들어야 한다
```

그 다음 **override 32건이 여전히 발동하는지 확인한다.** override는 지정한 버전이 의존성 트리에 실제로 있어야 발동한다. #55가 메이저 12건(tailwind 3→4, vite 6→8, eslint 8→10, typescript 5→6 등)을 올려 트리가 크게 바뀌었으므로, 대상이 사라져 무의미해진 항목이 있을 수 있다. 이 저장소에서 이미 겪은 실패 방식이다(`brace-expansion@2.0.2`가 트리에서 사라져 규칙이 발동하지 않아 감사에 안 걸리고 있었다).

확인 방법: 감사를 돌려 취약점이 0인지 보고, 해석된 패키지 수를 이관 전후로 대조한다(직전 기록은 root 296, frontend 422였으나 #55 이후 값이 달라졌을 것이다 — 그 자체는 문제가 아니고, override 대상이 트리에 있는지가 관건이다).

### 4. 검증

```
# 백엔드 (worktree에 venv가 없으므로 원본 트리 venv를 쓴다)
/Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python -m pytest -q

# 프론트
cd sasoo && pnpm vitest run
cd sasoo && pnpm exec tsc --noEmit -p frontend/tsconfig.json
cd sasoo && pnpm build          # electron 방출 확인 포함
```

기준선(2026-08-29): 백엔드 **826 passed / 7 skipped / 149 subtests**, vitest **147 passed**, tsc 초록.

### 5. 푸시하고 CI 확인

`git push`로 PR을 갱신하고 `gh pr checks 54`가 초록인지 본다. 그 뒤 사용자에게 넘긴다.

## 깨면 안 되는 계약

1. **override는 정확한 버전이 아니라 권고의 취약 범위로 쓴다.** `js-yaml@4.1.1: 4.3.0` 꼴로 못 박으면 새 권고가 그 버전을 포함할 때 조용히 다시 뚫린다. 이것이 Build Check가 2026-08-07부터 만성 실패했던 원인이다.
2. **override는 `pnpm-workspace.yaml`에 둔다.** `package.json`의 `pnpm` 필드가 아니다(위 "왜 필요한가" 참조).
3. **주기 감사(`dependency-audit.yml`)는 Build Check와 같은 명령을 쓴다.** 갈리면 한쪽만 초록인 상황이 생기고 아무도 신호를 안 믿는다.
4. **electron 방출은 CommonJS여야 한다.** 루트 `package.json`에 `"type"`이 **없어야** CJS로 방출된다. `"type": "module"`을 넣으면 Electron 메인이 ESM이 돼 앱이 안 뜬다. 확인: `dist-electron/main.js`가 `"use strict"`로 시작하는지.
5. **TypeScript를 7로 올리지 말 것.** typescript-eslint가 TS 7을 명시적으로 거부한다(peer `>=4.8.4 <6.1.0`). 올리면 TS 인지 린팅을 통째로 버려야 한다. 6.0.3이 현재 상한이다.
6. **Dependabot으로 갈아타지 말 것.** `pnpm.overrides`를 갱신하지 못한다(dependabot-core #13177에서 담당자가 명시적으로 기각). Renovate는 공식 문서에 `pnpm.overrides`를 depType으로 명시한다.

## 병합 후 사용자 수동 작업 2건

에이전트가 못 하는 일이므로 준비 완료 보고에 반드시 포함할 것.

1. Renovate GitHub App 설치 (저장소 소유자만 가능)
2. `gh workflow run dependency-audit.yml` 1회 실행 확인 — `workflow_dispatch`는 기본 브랜치에 파일이 있어야 동작해서 병합 전 검증이 불가능하다

## 주의: 저장소 주변 상태

- **다른 세션이 동시에 작업 중이다.** 브랜치가 `feat/v1-macos-vibrancy` ↔ `feat/v1-component-refresh`로 수시로 바뀌고 stash가 생겼다 없어진다. 사용자 작업 트리의 미커밋 변경분을 건드리지 말고, `git stash drop`을 번호로 실행하지 말 것(번호가 밀려 엉뚱한 것을 지운다 — 실제로 겪었다). 지워야 하면 `git stash list --format='%gd | %H | %gs'`로 해시를 확보해 대조하고 지운다.
- **로컬 `main` 브랜치가 origin/main보다 2커밋 앞서고 16커밋 뒤처져 있다.** 앞선 2개는 프로바이더 중립화 문서 커밋(`3f995f8`, `30272dc`)이고 같은 내용이 PR #57에 들어갔을 가능성이 높다. 로컬 main에서 작업하지 말 것. 정리 여부는 사용자에게 확인.
- `docs/superpowers/plans/`와 `RESEARCH/`, `docs/product-decisions.md`는 git 미추적 로컬 유지 관례다(DEC-007). 커밋하지 말 것.

## 참고 문서

- `docs/product-decisions.md`의 **DEC-015**(자동 갱신 도입 근거), **DEC-016**(메이저 12건 업그레이드, 이 PR이 뒤처진 원인)
- PR #54 본문
