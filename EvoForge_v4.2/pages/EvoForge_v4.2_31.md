<!-- PAGE:31/50 -->

# 31. 워크플로 엔진과 상태 머신

> **목적:** Run·Task·Candidate를 분리된 상태 머신으로 내구성 있게 실행한다. · **결정:** D-005, D-033, D-042, D-043 · **계약:** `contracts/sql/core_DRAFT.sql`(`core.enforce_state_machines`)

### 단계
`DISCOVER → SPECIFY → NEGOTIATE → ASSIGN → EXECUTE → REVIEW → VERIFY → DECIDE → MERGE/REJECT → LEARN`.

### 세 개의 상태 머신(정본, DB 트리거가 전이를 검사)
- **Run:** `CREATED → QUEUED → RUNNING ↔ WAITING → PAUSING → PAUSED → QUEUED(재개는 새 attempt)`, 취소는 `→ CANCELLING → CANCELLED`, 종료 `SUCCEEDED | FAILED`.
- **Task:** `READY → CLAIMED → RUNNING → REVIEW_REQUIRED → VERIFIED | REJECTED`, 보조 `WAITING_AGENT`, `BLOCKED`, `FAILED`, 비종료 상태에서 `CANCELLED`. 리뷰가 변경을 요청하면 `REVIEW_REQUIRED → RUNNING`.
- **Candidate:** `PROPOSED → PATCH_READY → BUILD_CHECKED → REVIEWED → QUALITY_CHECKED → PR_CREATED → MERGED | REJECTED`. head가 바뀌면 `PATCH_READY`로 돌아가 재검증한다. `PR_CREATED`는 `MERGED`를 뜻하지 않고, `MERGED` 진입은 `core.authorize_merge`를 통과해야 한다. `QUALITY_CHECKED`는 `GH_INTEGRITY` PASS(와 wave 후보 2개 이상이면 `GC_COMPOSITION` PASS)를 포함한다.
세 상태를 한 문자열 컬럼에 섞지 않는다. 취소·재시도는 완료된 외부 부작용을 없던 일로 만들지 못하며, 보상(예: PR 닫기)은 별도 이벤트로 한다.

### 구현 전략
PostgreSQL 작업 테이블 + Outbox + TypeScript 워커로 시작한다. 애플리케이션은 `WorkflowPort` 뒤에서 엔진에 의존하므로, 장기 실행·복잡한 재시도가 늘어 운영 통제가 어려워지면 Temporal(Signal/Update/Query)로 옮길지 실측 후 결정한다. SQLite는 로컬 개발·브리지 캐시·테스트 전용이다.

### 큐 분리와 Admission
논리 큐: `control`, `planning`, `provider`, `development`, `review`, `validation`, `composition`, `benchmark`, `merge`, `research`. `composition` 큐는 wave의 마지막 후보가 `QUALITY_CHECKED` 직전에 도달하면 결합 실행을 한 번 잡는다. 각 작업에 예산 예약, `deadline`, `retry_budget`, `priority`, `task_epoch`, `cancel_token`, `fallback_policy`를 붙인다. 불변식: 공급사 호출은 예약 성공 후, 검증 시작은 Runner 예약 후, `MERGED`는 최신 브랜치 정책 통과 후. 검증 backlog가 임계(검증 Runner 이용률 80% + 증가 추세, 제안값)를 넘으면 상류 후보 생성을 먼저 줄인다.

### 재시도와 체크포인트
429/503 → 지수 백오프. 테스트 실패 → 새 Candidate. 권한·정책 실패 → 자동 재시도 금지. 공급사 타임아웃 → `UNKNOWN_EXTERNAL_OUTCOME` 후 조회. 재시도는 새 attempt ID로 원인과 연결한다. 상태 전이마다 `checkpoint_version`, `base_sha`, artifact ref, 확정 비용, 활성 Lease를 저장한다. 사용자 명령은 접수 당시 버전을 검사한다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R31-1 | 크래시 내구성 | 각 단계에서 워커를 강제 종료해도 복구 후 중복 PR·중복 청구·정책 우회 없이 종결 |
| R31-2 | 전이 검증 | 허용되지 않은 Run/Task/Candidate 전이 0건 (C-06, C-08) |
| R31-3 | Backpressure | CI 포화 시험에서 후보 생성률이 먼저 줄고 필수 검증은 생략되지 않음 |

---
