<!-- PAGE:27/50 -->

# 27. 이벤트 버스와 전달 보장

> **목적:** 메시지는 최소 한 번 오고, 효과는 한 번만 일어나게 한다. · **결정:** D-005, D-030, D-033 · **계약:** `contracts/sql/core_DRAFT.sql`(`domain_events`, `outbox`, `inbox_dedup`, `side_effect_intents`)

### Envelope
`{event_id, tenant_id, project_id, type, schema_version, aggregate_type, aggregate_id, aggregate_version, correlation_id, causation_id, trace_id, actor{kind,id}, occurred_at, payload}`. `(tenant_id, aggregate_id, aggregate_version)`은 유일하다(낙관적 동시성).

### 전달 원칙
상태 전이·도메인 이벤트·Outbox를 한 트랜잭션에 기록한다. 큐 발행은 실패·재시도될 수 있다. 소비자는 `(tenant_id, consumer, event_id)`로 처리 이력을 남겨 **at-least-once 전달 + 멱등 효과**를 만든다. exactly-once 전송을 가정하지 않는다. 프로젝트 전역 순서에 의존하지 않고, 클라이언트는 순서 누락을 발견하면 스냅샷을 다시 받는다. 프로젝터 실패는 성공 이벤트로 바꾸지 않고 DLQ·경보로 남긴다.

### 메시지 종류
`COMMAND`(사람·정책 변경, 권한 검증 필수) · `TASK`(실행 지시) · `PROPOSAL`(AI 계획·개선안) · `ARTIFACT`(코드·리뷰·로그 참조) · `ACK` · `EVENT`. COMMAND와 AI 제안을 절대 섞지 않는다.

### Artifact-first 핸드오프
결과물은 `artifact URI + sha256 + base SHA + acceptance criteria + replay steps`로 넘긴다. 큰 로그·코드를 대화에 반복해 붙이지 않고, 큐에는 원문 대신 테넌트 범위 `ref`만 싣는다. 모든 좌석이 모든 메시지를 받는 풀메시가 아니라 주제별 구독과 타깃 전달을 쓴다. 서로 다른 API·Chat·CLI 기록은 `turn / tool_call / tool_result / artifact / decision / cost` 공통 형식(Canonical Trajectory v1)으로 정규화한다. 원본 공급사 payload는 접근 제한·보존 기간을 적용한다.

### 외부 부작용
PR 생성·병합·공급사 호출·결제는 `side_effect_intents`(`RESERVED → SENT → CONFIRMED | FAILED | UNKNOWN_EXTERNAL_OUTCOME`)로 예약한다. 타임아웃만으로 재호출하지 않고 원격 존재를 먼저 조회한다. `UNKNOWN_EXTERNAL_OUTCOME`에서 바로 재전송하는 전이는 DB가 거부한다.

### 이벤트 카탈로그
컨텍스트 이벤트는 `vocabulary.json`의 `context_events`가 정본이다. 협업 이벤트: `COLLECTIVE_TOPOLOGY_SELECTED`, `AGENT_ROLE_ASSIGNED`, `AGENT_IDLE`, `TASK_READY`, `TASK_REASSIGNED`, `BACKPRESSURE_APPLIED`, `BOTTLENECK_DETECTED`, `CANDIDATE_FILTERED`, `QUALITY_GATE_RECORDED`, `MERGE_CONFIRMED`. 연구 이벤트(M6): `CAPABILITY_GAP_DETECTED`, `RESEARCH_SOURCE_ACCEPTED`, `METHOD_EXTRACTED`, `HARNESS_VARIANT_CREATED`, `HARNESS_EVALUATION_COMPLETED`, `HARNESS_PROMOTION_REQUESTED`, `HARNESS_PROMOTED`, `HARNESS_ROLLED_BACK`, `RESEARCH_SOURCE_RETRACTED`. UI 이벤트는 이 카탈로그의 투영이다(p.44).

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R27-1 | 수렴 | 1만 건 재생·중복·순서 역전 시험에서 상태가 수렴하고 중복 PR·중복 청구 0 |
| R27-2 | 버전 충돌 | 같은 aggregate 버전 이벤트 2건 → 1건만 성공 (C-11) |
| R27-3 | 불명확 결과 | UNKNOWN에서 조회 없이 재시도 0건 (C-12) |

---
