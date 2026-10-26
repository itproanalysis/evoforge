<!-- PAGE:21/50 -->

# 21. 참가 방식과 에이전트 상태 모델

> **목적:** 네 가지 참가 방식의 실제 능력과, 하나로 통일한 상태 모델을 정한다. · **결정:** D-003, D-004, D-019 · **계약:** `contracts/sql/core_DRAFT.sql`(`core.agents`)

### 참가 방식
| 유형(`agent_kind`) | 연결 | 호출 주체 | 지속 실행 | 실제 제약 |
|---|---|---|---|---|
| `provider_api` | 플랫폼 키 + 프로젝트 allowlist | 시스템이 API 호출 | 가능 | 공급사 한도·가격·데이터 정책 |
| `mcp_chat` | 사용자가 승인한 EvoForge MCP 도구 | Chat이 도구 호출 | 세션·클라이언트 기능에 좌우 | 백그라운드 자동 호출 보장 없음 |
| `folder_chat` | 접근 가능한 폴더에 JSON | 브리지가 감시 | 브리지·클라이언트에 좌우 | 폴더 권한 없으면 수동 업로드 |
| `a2a` | Agent Card + 신뢰 인증 | 표준 A2A 요청 | 원격 정책에 따름 | 역방향 호출·성능·보안 확인 필요 |

### 상태 모델(4차원, 정본)
| 차원 | 값 | 질문 |
|---|---|---|
| join | `REQUESTED → PENDING_APPROVAL → AUTHORIZED → REVOKED` | 누가 접근할 수 있는가 |
| connection | `UNKNOWN / PROBING / READY / DEGRADED / OFFLINE` | 지금 호출 가능한가 |
| execution | `IDLE / ASSIGNED / RUNNING / WAITING_FOR_CLIENT / BLOCKED / FINISHED` | 실제로 일하고 있는가 |
| credential | `VALID / EXPIRING / EXPIRED / REVOKED` | 권한이 유효한가 |
작업 배정 조건은 `join=AUTHORIZED ∧ connection∈{READY,DEGRADED} ∧ credential∈{VALID,EXPIRING}`이다(`core.agent_can_work`). `REVOKED`는 실행 중 작업을 끝내고 토큰·Lease를 동시에 폐기한다.

### Capability Probe
`join`, `read_task`, `send_message`, `submit_patch`, `review`, `tool_execute`, `heartbeat`, `stream`, `persistent_worker`, `retrieve_evidence`, `cancel`을 작은 실과제로 따로 시험한다. 자기선언(`capabilities`)은 별도 값으로만 저장하고 권한 근거로 쓰지 않는다. 폴더의 `JOIN_REQUEST`는 접근 신청일 뿐 신원·지속 실행의 증거가 아니다. 사람이 붙여넣은 참여는 `HUMAN_RELAYED`. 연구 권한(`research.read/propose/evaluate`, `harness.promote/rollback`)은 서버가 부여하는 scope이며 선언으로 생기지 않는다.

### 비상주 Chat 규칙
Chat 좌석에 작업을 줄 때는 ACK·heartbeat·deadline을 확인하고, 실패하면 **고객이 허용한 공급사의 API 좌석**으로 재배정한다. 원문 복원 도구가 없는 Chat에는 필요한 원문을 허용 분량까지 포함한 작업 명세를 주거나, 리뷰 작업이면 API 좌석으로 재배정한다. Chat은 최종 승인자가 될 수 없다(p.35).

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R21-1 | 상태 분리 | UI·API·DB가 4차원 상태를 같은 값으로 표시, 단일 문자열 상태 컬럼 0 |
| R21-2 | 배정 조건 | 미승인·폐기·오프라인 좌석에 작업 배정 0건 (C-15) |
| R21-3 | 약관 준수 | 비공식 클라이언트 조작·자동 로그인·ToS 우회 기능 없음(보안 리뷰 체크리스트) |

---
