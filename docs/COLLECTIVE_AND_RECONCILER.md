# 0원/추정→실청구 정산 대사 정책 및 5-좌석 적응형 Collective·압축 경계·하네스 최적화 런타임

갱신: 2026-10-27. 본 문서는 `DEVELOPMENT_STATUS.md`(87, 99행), `RECEIPT_PERSISTENCE.md`(53, 58, 86–88행),
`Acceptance_Test_Matrix.md`(`CR-13`, `CR-39`, `CR-40`, `CR-47`, `CR-59`, `CR-60`, `CR-61`, `CR-65`, `CR-70`, `CR-71`, `CR-72`, `CR-73`, `CR-75`, `CR-76`),
및 `SERVICE_STATUS.md` P2에 남아 있던 미구현 런타임·대사 정책을 구현·검증한 결과를 기록한다.

## 1. 구현 모듈 및 계약 매핑

### 1.1 [`services/api/evoforge/reconciler_policy.py`](../services/api/evoforge/reconciler_policy.py)
- **정본을 우회하지 않는 0원(`0` micro-USD) 정산 정책 (`ReconcilerLedger.settle_receipt`)**:
  - `core.cost_reservations`는 `actual_micros >= 0`을 허용하므로 `status = 'COMMITTED', actual_micros = 0`으로 전이하여 열린 예약(`reserved_micros`) hold를 즉시 해제한다.
  - `core.usage_ledger`의 `ledger_sign` 제약(`model_usage`는 `customer_micros < 0`, `adjustment`는 부호 무제한·`reverses_entry_id IS NULL`일 때 `0` 허용)을 그대로 준수해, 가짜 청구(`-1`)·가짜 환불(`+1`) 없이 `entry_kind = 'adjustment', customer_micros = 0, receipt_id = <receipt_id>, idempotency_key = 'settle:' || call_id` 감사 행을 append-only로 기록한다.
- **추정 영수증(`source="estimated"`) KPI 제외(`CR-13`) 및 실청구(`source="provider_billed"`) 단일 역분개 대사(`CR-40`)**:
  - `filter_kpi_eligible_receipts` / `aggregate_verified_kpi`: `source="estimated"` 영수증과 대체(`superseded_by_receipt_id`)된 영수증을 공식 비용·토큰·캐시 절감 KPI 집계에서 100% 제외한다.
  - `reconcile_estimated_to_billed`: 기존 `estimated` 영수증 문서와 원장 행을 수정·삭제하지 않고 보존한 채, `core.enforce_reversal` 규칙(`entry_kind = 'adjustment'`, `reverses_entry_id = <est_entry_id>`, `customer_micros = -orig.customer_micros`, 1회만 역분개 허용)으로 역분개한 뒤 최종 `provider_billed` 금액을 원장과 예약 `actual_micros`/`overrun`에 반영한다.
- **부작용 intent 전이 가드(`CR-47`) 및 UNKNOWN 예약 자동 대사 잡(`UnknownReservationReconciler`, `CR-39`)**:
  - `UNKNOWN_EXTERNAL_OUTCOME -> SENT` 직접 재시도를 `IllegalSideEffectTransition`으로 차단한다.
  - `UnknownReservationReconciler.reconcile_micros_batch` 및 `reconcile_in_memory_unknowns`: 공급사 영수증 조회 결과에 따라 청구 확인(`BILLED`, `actual > reserved` 시 `overrun=True` 기록), 미접수 해제(`NOT_ACCEPTED` → `FAILED`/`RELEASED`/`REFUNDED` 후 재시도 가능), 조회 미확정(`STILL_UNKNOWN` → 예약 유지)을 일괄 처리한다.

### 1.2 [`services/api/evoforge/collective_runtime.py`](../services/api/evoforge/collective_runtime.py)
- **가역 에포크 접기(ReFold) 및 압축 경계 직후 3-턴 Continuation 수집·평가기 (`CompactionBoundaryRuntime`, `CR-75`)**:
  - 명시적 에포크 경계(`at_epoch_boundary=True`)에서만 이전 에포크(`epoch < current_epoch`)의 비필수 `L3_TASK_DELTA` 항목을 Vault `ref`·`sha256`·`byte_length`·1줄 요약이 포함된 `REF_ONLY` 스텁으로 접는다(`L0~L2` 및 `requires_original=True` 불변 보존).
  - 동일 스냅샷에서 비압축 기준선과 압축 후보의 시드별 `N=3` 턴 continuation 결과(성공 여부, 반복 탐색 횟수, 막힌 행동 횟수)를 수집해 `reference_impl/compaction_eval.py::decide` 4조건 및 최소 30세션(`min_sessions=30`) 검사를 수행한다.
- **M6 하네스 최적화 런타임 루프 (`HarnessOptimizerRuntime`, `CR-76`)**:
  - `harness-patch.v1.schema.json` 검증(`evaluated_on: ["test"]` 표현 불가, 경로 이탈 차단), `GEPA` 기준선 강제, Trust Kernel 보호 경로(`policy/**`, `verifiers/**`, `billing/**`, `eval_data/**`, `gates/**`) 차단, 세대별 편집 예산 선형 감쇠(`120 -> 20`줄), 미니배치 개선 패치만 EvoDAG 후보 승격, `OPEN -> FROZEN -> CLOSED` 상태기계 및 동결 후 `D_test` 단 1회 평가를 실행한다.
- **5-좌석 적응형 Collective 및 12개 정본 MCP 도구 표면 (`AdaptiveCollectiveCoordinator`, `CR-59`, `CR-60`, `CR-61`, `CR-65`, `CR-70`, `CR-71`, `CR-72`, `CR-73`)**:
  - `vocabulary.json`의 5개 좌석(`Navigator`, `Builder Alpha`, `Builder Beta`, `Critic`, `Integrator`)과 12개 `mcp_tools` 전체를 제공한다.
  - 자격/승인 상태 검사(`CR-59`), 단일 클레임 승자·만료 리스 재획득·`lease_epoch` 펜싱(`STALE_WRITE`, `CR-60`), 응집도 기반 파티셔닝(`CR-70`), 파동 합성 게이트(`GC_COMPOSITION`) 및 AST 심볼 변경 공지(`CR-61`, `CR-71`), 실행 증거 우선 후보 선택 및 적응형 k(`CR-72`), 읽기 전용 투기 실행·등위 회귀(PAV) 모델 cascade·단계 게이트 경험 기억(`CR-73`), PPI 인간 수용률 비열등성(`CR-65`)을 통합한다.

## 2. 검증 명령 및 범위

```powershell
python -I docs/evoforge-v4.2/tools/validate_package.py
python -m pytest services/api/tests/test_reconciler_policy_cr.py services/api/tests/test_collective_runtime_cr.py -q -p no:cacheprovider
python -m pytest services/api -q -p no:cacheprovider
```

- 정본(`docs/evoforge-v4.2/`), `main.py`, 웹 UI, DB 마이그레이션은 수정하지 않았다.
- 실제 외부 공급사 청구 API 웹훅 수신 및 운영 Cloud SQL 크론 스케줄러 연결은 별도 운영 통합 범위다.
