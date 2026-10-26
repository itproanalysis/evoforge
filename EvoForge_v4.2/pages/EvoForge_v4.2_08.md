<!-- PAGE:08/50 -->

# 08. 서비스 블루프린트와 명령 수명주기

> **목적:** 사용자 행동이 백엔드에서 어떤 상태를 거치는지 하나의 수명주기로 고정한다. · **결정:** D-005, D-009, D-031, D-033 · **계약:** `contracts/sql/core_DRAFT.sql`(`core.commands`)

### 접점 매핑
| 사용자 접점 | 프런트엔드 | 도메인 서비스 | 비동기 작업 | 증거 |
|---|---|---|---|---|
| 공급사 허용 | Provider Picker | Allowlist Service | 공급사 상태 점검 | 동의 시각·동의자 |
| Chat 참여 신청 | Join Wizard | Registry + Approval | Capability Probe | 승인자·권한 |
| 목표 입력 | Command Center | Objective Service | 재계획 | goal version |
| 역할 협의 | Collective Graph | Topology Selector | 제안·반론 | 배정 이벤트 |
| 개선 실행 | Improvement Lab | Task + Runner | Sandbox/CI | diff·commit |
| 피드백 | Feedback Panel | Feedback Service | 분류·연결 | feedback_links |
| 성과 조회 | Evidence | Evidence Service | Benchmark | baseline/candidate |
| 병합 | Approval Panel | Merge Policy | GitHub merge | 게이트·서명·SHA |

### 명령 수명주기(단일 정의)
`RECEIVED → VALIDATING → (AWAITING_CONFIRMATION) → PLANNED → DISPATCHED → APPLYING → APPLIED | PARTIAL | BLOCKED | FAILED`, 검증 실패는 `REJECTED`.
- HTTP는 `202 Accepted + command_id + status_url`만 돌려준다. ACK에 완료를 암시하는 표현을 쓰지 않는다.
- 위험 명령(`APPROVE_MERGE`, `APPROVE_DEPLOY`, `BUDGET_INCREASE`, `ENABLE_AUTOMERGE`, `PERMISSION_CHANGE`, `ROLLBACK_HARNESS`)은 구조화된 영향 미리보기 → `AWAITING_CONFIRMATION` → 권한자 확정 없이는 `PLANNED`로 갈 수 없다(DB 트리거).
- Fast lane 명령(`STOP_ALL`, `PAUSE`, `CANCEL`, `BUDGET_DECREASE`, `REPRIORITIZE`, `REASSIGN`)은 모델 호출과 큐·자원을 공유하지 않으며, 안전 명령은 상태 버전이 어긋나도 거부하지 않는다.
- 같은 `idempotency_key`의 재전송은 같은 `command_id`를 돌려준다. 오래된 `expected_state_version`은 409.

### 트랜잭션 원칙
요청 처리 안에서 장시간 작업을 하지 않는다. 상태 전이·도메인 이벤트·Outbox를 한 트랜잭션에 기록하고 워커가 실행한다. 외부 부작용(PR 생성, 병합, 공급사 호출, 결제)은 `side_effect_intents`로 예약하고 결과 ID를 기록한다(p.27, p.40).

### 실패 경험
외부 Chat이 응답하지 않으면 "참여했지만 응답 대기"로 표시하고 작업 중인 것처럼 연출하지 않는다. 공급사 실패 시 재시도 조건·대체 모델(허용 범위 안)·추가 비용을 보여준다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R08-1 | 추적 가능성 | 주요 사용자 행동 8개가 이벤트 ID·상태·완료 증거까지 추적됨 |
| R08-2 | 명령 멱등성·충돌 | 같은 명령 20회 재전송 → 1회 실행, 오래된 버전 → 409, 권한 없음 → 실행 전 403 (C-02) |
| R08-3 | 위험 명령 확정 | 확정 없는 위험 명령의 `PLANNED` 진입 0건 (C-03) |

---
