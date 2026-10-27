# EvoForge 도메인 이벤트 버스·실시간 UI SSE 게이트웨이 및 관측성/거버넌스 런타임

2026-10-27. 정본 명세(`docs/evoforge-v4.2/pages/EvoForge_v4.2_27.md`, `44.md`, `45.md`~`50.md` 및 `Acceptance_Test_Matrix.md`)를 수정하지 않고, 미구현 상태였던 도메인 이벤트 버스/Outbox/1만 건 재생 수렴·실시간 SSE 투영/폭주 필터링 및 관측성 SLO/안전 불변식·청구서/PG 웹훅 대사·인시던트 격리·삭제 연쇄·출시 증거 패키지 검증 런타임을 구현·검증했다.

## 1. 구현 범위

### 1.1 도메인 이벤트 버스·Outbox/Inbox·1만 건 수렴·SSE 게이트웨이 (`services/api/evoforge/event_bus_and_sse.py`)
- **`CanonicalEventEnvelope` & `DomainEventBus` (`R27-1`, `R27-2`, `C-11`, `D-005`)**:
  - 14필드 정본 Envelope(`event_id`, `tenant_id`, `project_id`, `type`, `schema_version`, `aggregate_type`, `aggregate_id`, `aggregate_version`, `correlation_id`, `causation_id`, `trace_id`, `actor{kind,id}`, `occurred_at`, `payload`) 검증.
  - `(tenant_id, aggregate_id, aggregate_version)` 낙관적 동시성 강제(`R27-2`, `C-11`): 동일 버전 충돌 시 1건만 성공하고 나머지는 `OptimisticConcurrencyError("AGGREGATE_VERSION_CONFLICT")`로 거부.
  - `COMMAND`(사람·정책 변경)와 `PROPOSAL`(AI 제안) 엄격 분리: AI/모델 주체가 `COMMAND`를 발행하면 `COMMAND_PROPOSAL_MIX_FORBIDDEN`으로 차단.
  - 트랜잭션 Outbox 기록 및 `(tenant_id, consumer, event_id)` Inbox 중복 제거(at-least-once 전달 + 멱등 효과), 프로젝터 실패 시 거짓 성공 전환 없이 DLQ(`alert_raised=True`) 적재.
  - **1만 건 재생·중복·순서 역전 수렴 엔진 (`R27-1`, `replay_and_converge`)**: 다중 Aggregate에 걸친 중복·역순 이벤트 스트림 10,000건을 인과 버전 순으로 정렬·소비하여 최종 상태를 수렴시키고 중복 PR 생성 0건·중복 과금 청구 0건을 보장.
- **`ArtifactFirstHandoff` & `CanonicalTrajectoryNormalizer` (`EvoForge_v4.2_27.md`, `CR-31`)**:
  - 순차적·추측 가능한 ref(`ref_0001` 등)와 대용량 인라인 페이로드 전송을 차단하고 `ef_ref_*` 무작위 grant ref 기반 아티팩트 핸드오프 강제.
  - API·Chat·CLI 이종 실행 기록을 `Canonical Trajectory v1` 6종 스텝(`turn`, `tool_call`, `tool_result`, `artifact`, `decision`, `cost`)으로 정규화.
- **`MissionControlSSEGateway` (`EvoForge_v4.2_44.md`, `R44-1`, `R44-2`, `R44-3`, `D-009`)**:
  - `get_snapshot`에서 `projection_version`과 `event_cursor`를 동일 일관성 경계에서 반환하고, 명령 카드 상태를 `RECEIVED -> PENDING`, `APPLIED -> DONE`으로 분리 투영(`D-009`).
  - 커서 누락·보존 창 만료·패치 실패 감지 시 조용히 건너뛰지 않고 `resync_required=True`로 스냅샷 재동기화를 강제하여 다중 브라우저·모바일 클라이언트의 상태 수렴 보장(`R44-1`).
  - 발행 전(pre-publish) 테넌트 및 RBAC 권한 필터 적용(`R44-3`: 타 테넌트·무권한 스트림 노출 0건).
  - 초당 1,000건 폭주(`overload_mode=True`) 시 `progress` 이벤트만 샘플링하고 `approval`·`error`·`conclusion`(`MERGE_CONFIRMED`, `APPROVAL_RECORDED`, `ERROR_RAISED` 등) 이벤트는 **누락 0건** 보장(`R44-2`).

### 1.2 관측성·SLO/안전 불변식 분리·청구서/PG 웹훅 대사·거버넌스 (`services/api/evoforge/observability_and_governance.py`)
- **`CanonicalTelemetryTracer` & `SLOVsSafetyMonitor` (`EvoForge_v4.2_47.md`, `R47-2`, `R47-4`)**:
  - 정본 컨텍스트 span 6종(`context.detect`, `context.original_store`, `context.compress`, `context.assemble`, `context.retrieve`, `provider.cache_decision`) 및 워크플로 span 검증.
  - 대시보드 패널 분리(`R47-2`): 서비스 SLO 5종 패널(`api_availability >= 99.9%`, `command_ack_p95 < 2000ms`, `ui_commit_reflect_p95 < 3000ms`, `reconnect_converge_p95 < 10000ms`, `stop_all_apply_p95 < 5000ms`)과 안전 불변식 6종 패널(목표 0건: 미승인 병합/배포, 타 조직 노출, 비밀 유출, 예산/크레딧 초과 실행, 작업 유실, 플랫폼 키 비인가 복호화)을 독립 평가.
  - v4.1 성능 기법 감시(`R47-4`): 표본 수(`n`)와 함께 간섭률·무결성 flag·held-out 격차·투기 수락률·`k`·cascade 상향률을 추적하며, **투기 불일치 1건 발생 즉시 투기를 전역 비활성화**, 보상 해킹 급증 시 해당 `(model, harness_version)` 구성을 카나리에서 자동 제외, 검증 Runner 이용률 80% 이상 증가 추세 시 상류 감속/증설 권고.
- **`BillingInvoiceAndWebhookReconciler` (`EvoForge_v4.2_47.md`, `48.md`, `R47-3`, `R48-1`~`R48-3`)**:
  - 공급사 일일 청구서 vs 정본 `provider_billed` 영수증 대사: 차이율 `> 1%` 시 경보 발생 및 원인 분류(`MISSING_RECEIPT`, `UNBILLED_RECEIPT`, `AMOUNT_MISMATCH`, `PRICE_TABLE_DRIFT`).
  - 결제 PG 웹훅 중복·역순(`payment.partial_refunded`가 `payment.succeeded`보다 먼저 도착)·부분 환불 처리 시 중복 청구/환불 0건 및 원장 합계 일치 보장(`R48-1`).
- **`IncidentAndLifecycleGovernance` (`CR-17`, `CR-22`, `CR-24`, `CR-69`, `R46-2`, `R49-1`, `R49-5`, `R50-1`)**:
  - Incident 상태 머신(`DETECT -> TRIAGE -> CONTAIN -> RECOVER -> COMMUNICATE -> RCA -> PREVENT`), 에이전트 협의와 독립된 운영자 안전 스위치(`CONTAIN` 시 병합/배포/공급사 어댑터 즉시 차단), 공급망 사고 7단계 런북 실행.
  - `CR-22`: 목표 버전 변경 시 활성 패킷 즉시 `STALE` 전환·승인 차단·되살리기 영구 금지.
  - `CR-24` & `CR-69`: 신규 코덱 기능 플래그 OFF 시 `RAW(POLICY_RAW_ONLY)` 폴백, `S11` 캐시 배치 위반(`L3` breakpoint 또는 캐시 prefix 내 `tool_output`/`untrusted`) 즉시 차단.
  - `CR-17` & `R46-2`: `shred_blob_and_cascade` 실행 시 `legal_hold`면 차단하고, 일반 삭제 시 DEK 파기·tombstone(`SHREDDED`)·ref/패킷 `REVOKED`·검색 인덱스/임베딩/플레이북 교훈 잔존 0건 및 백업 만료 일정 반환.
  - `R49-1`, `R49-5`, `R50-1`: 마일스톤·GA 출시 증거 패키지 검증기(`default_model == "muse-spark-1.3"`, 5모듈 하네스 매니페스트 `T/C/S/M/W`, 오라클 사람 라벨 holdout ≥ 200건, 샌드박스 위생 감사 통과율 100%, 설계 목표치 vs 실측치 분리, 체크리스트 증거 링크 필수).

## 2. 재현 및 검증 명령

```powershell
python -m pytest services/api/tests/test_event_bus_and_sse_cr.py services/api/tests/test_observability_and_governance_cr.py -v
python -I docs/evoforge-v4.2/tools/validate_package.py
```
