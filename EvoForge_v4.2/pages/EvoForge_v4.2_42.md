<!-- PAGE:42/50 -->

# 42. 데이터 모델

> **목적:** 테넌트 격리와 불변식이 DB에서 강제되는 스키마를 정한다. · **결정:** D-030, D-040 · **계약:** `contracts/sql/core_DRAFT.sql`, `contracts/sql/context_plane_DRAFT.sql`

### 명명과 원칙
- 테넌트 컬럼은 **`tenant_id`** 하나로 통일한다(UI 용어는 "조직"). 모든 ID는 UUID, 금액은 정수 micro-USD.
- 모든 고객 데이터 테이블은 `tenant_id`를 갖고 `(tenant_id, …)` **복합 PK·FK**로 다른 조직 레코드를 참조할 수 없게 한다. RLS는 테넌트 **그리고** 프로젝트(`app.tenant_id`, `app.project_ids`) 기준이며 `FORCE ROW LEVEL SECURITY`.
- 앱 역할에는 DELETE 권한이 없고, UPDATE는 컬럼 단위로만 준다. 감사·게이트·리뷰·승인·이벤트·원장은 append-only 트리거로 보호한다. 삭제는 tombstone + DEK 파기.
- API는 `tenant_id`를 클라이언트 입력에서 믿지 않고 인증 컨텍스트로 정한다.

### Core 스키마(`core`)
| 영역 | 테이블 | 핵심 제약 |
|---|---|---|
| 테넌시 | `tenants`, `projects`, `provider_allowlist` | 자동화·연구·컨텍스트 모드 CHECK, 공급사 동의 시각 |
| 에이전트 | `agents` | 4차원 상태 CHECK, REVOKED 정합성 |
| 명령 | `commands` | `UNIQUE(tenant, project, idempotency_key)`, 상태 전이 트리거, 위험 명령 확정 |
| 실행 | `runs`, `tasks`, `candidates`(`wave_id`) | 상태 머신 트리거, Lease epoch, `MERGED` 진입 시 `authorize_merge`(wave 후보 ≥ 2면 `GC_COMPOSITION` 요구) |
| 품질 | `gate_results`(`GH_INTEGRITY`, `GC_COMPOSITION` 포함), `reviews`(`context_independent`, `spec_tests_sealed_at`, `diff_first_read_at`, `evidence_kind`, `evidence_ref`), `reviewer_qualifications`, `approvals` | append-only, 자기 리뷰 금지, 차단 리뷰 증거 필수, 명세 선행 순서 CHECK, 재인증 승인 |
| 이벤트 | `domain_events`, `outbox`, `inbox_dedup`, `side_effect_intents` | `(tenant, aggregate, version)` 유일, UNKNOWN 재시도 금지 |
| 과금 | `budgets`, `cost_reservations`, `usage_ledger` | 예약 선행, 하드캡, 부호 규칙, 역분개 1회 |
함수: `accept_command`, `claim_task`, `assert_fencing`, `authorize_merge`, `reserve_cost`, `settle_reservation`, `credit_balance`, `agent_can_work`.

### Context 스키마(`ctx`, `ctx_sec`)
`evidence_blobs`(PENDING/ACTIVE/SHREDDED, 블롭별 DEK, legal hold), `context_packets`(좌석·기능 역할·fencing·cache_mode·멱등 키·상태), `evidence_refs`(무작위 grant), `context_items`(항목별 fidelity), `evidence_access_log`(append-only, FK 없음), `ctx_sec.security_events`, `provider_usage_receipts`, `codec_profile_state`. 함수: `review_coverage`, `assert_review_gate`, `mark_task_packets_stale`, `shred_blob`.

### 연구 스키마(M6, 미작성)
`research_sources`, `capability_gaps`, `research_methods`, `research_cycles`, `harness_module_variants`, `harness_versions`, `harness_evaluations`, `harness_promotions`, `experiment_predictions`, `experiment_observations`. M5 이후 같은 원칙(복합 FK·RLS·append-only)으로 작성한다. 공개 논문 메타데이터 캐시만 테넌트 간 공유할 수 있다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R42-1 | 스키마 테스트 | `run_sql_tests.sh` 96개 검사(context 39 + core 57) CI 필수 |
| R42-2 | 혼입 방지 | 두 조직의 동일 ID 혼입·RLS 우회·잘못된 참조 시나리오 자동 테스트 통과 (C-01, T01–T03) |
| R42-3 | 원본 최소 저장 | 원본 코드는 DB에 저장하지 않고 Git SHA + 암호화 아티팩트 ref |

---
