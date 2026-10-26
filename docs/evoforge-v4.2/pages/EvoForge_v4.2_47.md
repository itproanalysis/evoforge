<!-- PAGE:47/50 -->

# 47. 관측성·SLO·장애 대응

> **목적:** 서비스 SLO와 안전 불변식을 분리해 측정하고, 장애 절차를 표준화한다. · **결정:** D-010, D-020, D-042, D-047 · **계약:** `contracts/quality_gates.json`(`codec_runtime`)

### 관측
OpenTelemetry trace: `사용자 명령 → dispatch → context.* → provider.call → Runner → CI → merge`. GenAI semantic conventions는 아직 발전 중이므로 내부 Canonical Event 스키마를 정본으로 두고 버전 매핑한다. 컨텍스트 span: `context.detect`, `context.original_store`, `context.compress`, `context.assemble`, `context.retrieve`, `provider.cache_decision`.

### 서비스 SLO(제안, 실측 후 확정)
| 항목 | 목표 | 산식 |
|---|---:|---|
| API 가용성 | 월 99.9% | 정상 응답 / 유효 요청 |
| 명령 접수 | p95 < 2초 | 202 응답 시간 |
| UI 확정 이벤트 반영 | p95 < 3초 | commit → 클라이언트 적용 |
| 재연결 수렴 | p95 < 10초 | 재연결 → 스냅샷 일치 |
| STOP_ALL 적용 | p95 < 5초 | 접수 → 신규 dispatch 차단 |

### 안전 불변식(건수 0 목표, 지속 감사)
미승인 병합·배포, 다른 조직 노출, 비밀 유출, 예산·크레딧 초과 실행, 진행 중 작업 유실, 플랫폼 키 비인가 복호화. 사고 가능성이 0이라고 보장하지 않으며, 발생 시 Incident로 처리한다.

### 운영 지표와 경보
`critical_path_ms`, `queue_wait_ms{lane}`, `agent_active_ratio`, `task_rework_rate`, `composition_interference_rate`, `integrity_flag_rate{kind}`, `strong_oracle_fraction`, `visible_heldout_gap`, `speculation_accept_ratio`, `speculation_reexec_ratio`, `samples_per_task(k)`, `cascade_escalation_rate`, `advisory_suppressed_count`, `provider_429_rate{provider}`, `CI_wait_p95`, `merge_wait_p95`, `context_reuse_ratio`, `verified_fix_rate_per_hour`, `cost_per_verified_improvement`, `command_ack_p95`, `credit_burn_rate{tenant}`, `reservation_overrun_rate`, `provider_invoice_drift`. 경보: 큐 적체, Runner 대기, 공급사 429/5xx, 중복 Job, 감사 로그 결손, 키 접근 이상, 재연결 실패, 삭제 지연, 정산 불일치, 원문 복원 실패율, STALE 패킷으로 검증 시도, Vault I/O 대기, 캐시 쓰기 비용 급증. 검증 Runner 이용률 80% + 증가 추세면 상류 감속 또는 증설을 추천한다. `visible_heldout_gap` 상승, 특정 모델·하네스의 `integrity_flag_rate` 급증은 보상 해킹 경보로 올리고 해당 구성을 카나리에서 뺀다. 투기 실행 결과가 순차 재실행과 다른 사례가 1건이라도 나오면 투기를 전역 비활성화한다. codec 런타임 감시는 p.37 규칙대로 자동 비활성화한다. 초기 경보는 고정 임계로 시작하고 실측 분포로 조직별 조정한다.

### Incident 절차
`Detect → Triage → Contain(merge/deploy/공급사 어댑터 차단) → Recover → Communicate → RCA → Prevent`. 공급망 사고: `의존성 격리 → egress 제한 → 영향 아티팩트 목록 → 비밀·공급사 키 회전 → 깨끗한 이미지 재빌드 → 포렌식 증거 → 테넌트 통지`. 운영자 안전 스위치는 에이전트 협의와 독립적으로 동작한다.

### 백업·DR
DB 자동 백업, 월간 표본 복구 + 분기 전체 재구성 훈련, Object Storage 버전·수명 정책, IaC 재구축. RPO/RTO는 훈련 실측으로 M5 이전에 확정한다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R47-1 | 운영 준비 | 월간 DR 훈련, 온콜, 장애 알림, 고객 상태 페이지, 사후 보고 절차 |
| R47-2 | 지표 분리 | 대시보드에서 SLO와 안전 불변식이 별도 패널 |
| R47-3 | 정산 감시 | 공급사 청구서와 receipt 차이 > 1%면 경보(제안값) |
| R47-4 | 성능 기법 감시 | v4.1 지표(간섭률·무결성 flag·held-out 격차·투기 수락률·k·cascade 상향률)가 기법별 패널에 표본 수와 함께 표시, 투기 불일치 1건 시 자동 차단 |

---
