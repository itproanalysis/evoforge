<!-- PAGE:19/50 -->

# 19. 온보딩·연결 마법사

> **목적:** 연결을 안전하게 끝내고, 지원 범위를 정직하게 알린다. · **결정:** D-003, D-019, D-039 · **계약:** —

### 단계
1. **Workspace** — 조직·프로젝트 생성, 초대.
2. **Repository** — GitHub App 선택 설치, 범위·기본 브랜치·보호 규칙 확인.
3. **AI & Participants** — 공급사·모델 allowlist와 데이터 전송 동의(키 입력 없음). 선택: Remote MCP, Folder Chat, A2A 엔드포인트.
4. **Safety & Budget** — 허용 경로, 작업·프로젝트 예산, 검증 정책, 승인 규칙, 컨텍스트 프로필(`SAFE` 기본; `BALANCED`는 M3 이후 실험 opt-in; `MAXIMUM`은 고객에게 제공하지 않음).
5. **Trial Run** — 읽기 → 도구 호출 → Runner → CI → 메시지 왕복 시험.

### 오류 코드
`PROVIDER_NOT_ALLOWED`, `PROVIDER_UNAVAILABLE`, `CREDIT_EXHAUSTED`, `BUDGET_EXCEEDED`, `MCP_TOOL_UNAVAILABLE`, `FOLDER_PERMISSION_DENIED`, `REPO_INSTALLATION_MISSING`, `CI_NOT_CONFIGURED`, `SANDBOX_UNAVAILABLE`. 각 코드는 재시도·문서·권한 수정 링크를 제공한다.

### AI Chat 참여 고지
Chat 서비스마다 원격 MCP 쓰기 지원과 세션 유지가 다르다. 지원이 없으면 참여 JSON을 붙여넣는 **수동 참여 모드**로 동작하고 `HUMAN_RELAYED`로 표시한다. 수동 참여를 자동 실행으로 홍보하지 않는다. 연결 호환성은 `join → permission probe → task receive → result submit → disconnect/reconnect` 계약 테스트로 확인하고, 지원 표에 프로토콜 버전(MCP 2026-07-28, A2A 1.0, Folder `evoforge.folder/1`)·도구 읽기/쓰기·취소·재연결·실측일을 기록한다.

### 좌석 표시
`Connected`(등록됨) / `Eligible`(이 과제에 쓸 수 있음) / `Active`(실행 중) / `Awaiting Chat` / `Unavailable` / `Idle — not needed for this task`는 서로 다른 상태다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R19-1 | 비밀 비노출 | 연결 실패 상태에서도 토큰·키가 로그·에러 화면·URL에 나타나지 않음 |
| R19-2 | 전송 고지 | 공급사별로 어떤 코드·컨텍스트가 어디로 가는지 단계마다 표시, 동의 철회 시 즉시 라우팅 제외 |
| R19-3 | 지원 매트릭스 | 공시된 모든 클라이언트에 계약 테스트 실측일이 있고 90일 넘으면 `재확인 필요` |

---
