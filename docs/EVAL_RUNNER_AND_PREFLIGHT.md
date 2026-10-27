# M0 위생 평가 러너·Broker/CLI 사전 바인딩/예약 가드 및 다중 코덱/섀도 감사/품질·승격 런타임

갱신: 2026-10-27. 본 문서는 `DEVELOPMENT_STATUS.md`(98–99행, 126–133행), `Acceptance_Test_Matrix.md`(`CR-03~05`, `CR-09`, `CR-27`, `CR-29`, `CR-33`, `CR-36~38`, `CR-41`, `CR-51~58`, `CR-62~64`, `CR-67`, `CR-74`, `CR-77`, `CR-79`), 및 `SERVICE_STATUS.md` P1–P2의 미구현 요구사항을 구현·검증한 결과를 기록한다.

## 1. 구현 모듈 및 계약 매핑

### 1.1 [`services/api/evoforge/eval_runner_and_preflight.py`](../services/api/evoforge/eval_runner_and_preflight.py)
- **M0 위생 평가 러너 통합 (`HygieneEvalRunner`, `CR-74`, D-050)**:
  - `build_sandbox_repo` 기반 새 저장소 빌드 및 실행 전후 7개 항목 위생 감사(`no_remote`, `single_base_ref`, `head_is_base`, `no_alternates`, `empty_reflog`, `future_commits_absent`, `all_commits_ancestors_of_base`).
  - 단순 clone+checkout 대비 깨끗한 샌드박스의 격리 검증 및 미래 커밋의 비밀 토큰 누출 차단(`verify_naive_clone_vs_hygiene_sandbox`).
  - 후보 diff 적용, visible/heldout 스위트 격리 실행(봉인 `sealed.ini`), `GH_INTEGRITY` 및 `G2_REQUIRED` 판정, 위생 위반 시 조기 중단 및 필수 5개 필드(`name`, `version`, `turn_cap`, `model`, `harness_version`) 스캐폴드 점수 행(`score_record`)을 발행.
- **Broker 사전 패킷·레지스트리 가드 (`PreflightCallBroker.validate_packet_and_registry`, `CR-29`, `CR-33`)**:
  - `context-packet.v2.schema.json` 및 `validate_package.semantic` (S1..S11) 규칙 선행 검증.
  - 캐시 비활성화 불가 공급자(`can_disable=false`, 예: OpenAI pre-5.6)에서 `A0_RAW_NOCACHE` / `cache_mode="NONE"` 요청 시 `CACHE_DISABLE_UNSUPPORTED` 거부 (`CR-29`, S6).
  - 레지스트리 검증 후 14일 초과(`age > max_age_days`) 경과한 만료 항목을 `REGISTRY_ENTRY_STALE`로 사전 차단 (`CR-33`, S6).
- **호출 전 원자적 비용 예약·동의·리스 펜싱 및 영수증 정산 가드 (`PreflightCallBroker`, `CR-37`, `CR-38`, `CR-41`)**:
  - 공급자 전송 전 테넌트 신용 잔액 및 프로젝트 예산 한도를 원자적으로 확인하고 부족 시 `CREDIT_EXHAUSTED` / `BUDGET_EXCEEDED` 거부.
  - 미허용 공급자(`PROVIDER_NOT_ALLOWED`) 및 테넌트 데이터 동의 미획득 공급자(`PROVIDER_CONSENT_MISSING`) 전송 차단.
  - 에이전트 작업 리스 비활성(`LEASE_INACTIVE`), 만료(`LEASE_EXPIRED`), 에이전트/에포크 불일치(`STALE_LEASE`) 검사 및 네트워크 전송 직전 리스 상태 재확인.
  - 패킷 SHA-256 및 예약 키가 불변 바인딩된 `PreboundCallBinding` 생성.
  - 영수증 검증 시 비플랫폼 키(`BYOK_RECEIPT_FORBIDDEN`, `billing_owner != 'platform'`, `CR-41`), 예약 키 불일치(`RESERVATION_KEY_MISMATCH`, `CR-37`), 가격표 버전 불일치(`PRICE_TABLE_MISMATCH`), 호출 식별자 불일치(`RECEIPT_BINDING_MISMATCH`) 차단 후 `ReconcilerLedger`와 원자적 정산.
- **개발자 Muse Builder CLI 예산 가드 (`DevBuilderCLIGuard`, `DEVELOPMENT_STATUS.md` 98행)**:
  - 플랫폼 예산 및 신용 통제 하에 CLI 태스크를 실행한다. 신뢰된 CLI 어댑터가 공급사 요청 ID, 네 종류의 토큰 사용량, 공급사 비용과 고객 청구액을 명시적인 음수가 아닌 정수로 모두 반환한 경우에만 영수증을 만든다. `actual_micros` 인자는 청구 근거가 아니며, 제공될 경우 반환된 고객 청구액과 일치해야 한다. 실제 0원도 명시적으로 전달되어야 한다.
  - 사용량이나 청구액이 없거나 잘못되면 영수증을 만들지 않고 호출을 `UNKNOWN_EXTERNAL_OUTCOME`으로 남겨 예약을 유지한다. 공급사 비용과 고객 청구액은 서로 다른 값일 수 있으며 각각 기록한다.
  - CLI 어댑터는 `billing_source=provider_billed`, `billing_verified=true`와 비어 있지 않은 원본 JSON 사용량을 명시해야 한다. 원본은 재구성하지 않고 보존하며, 잘못된 JSON이나 너무 긴 공급사 요청 ID도 예약을 유지한다. 이 표기는 어댑터의 주장으로, 실제 공급사에 대한 독립적인 인증은 별도 연결이 필요하다.
  - 이 가드는 반환된 값의 공급사 출처를 독립적으로 증명하지 않는다. 운영 연결 전에는 실제 어댑터의 출처 검증과 PostgreSQL 예약·영수증 경로 연결이 필요하다. 현 검증은 인메모리 원장과 합성 CLI 결과만 사용한다.

### 1.2 [`services/api/evoforge/codec_and_quality_runtime.py`](../services/api/evoforge/codec_and_quality_runtime.py)
- **다중 코덱 파이프라인 (`MultiCodecPipeline`, `CR-03`, `CR-04`, `CR-05`, `CR-09`, `CR-27`, `CR-36`)**:
  - `EvidenceVault` 사전 적재 및 read-back 검증 영수증(`VaultReceipt`) 획득, Vault 장애 시 `RAW(VAULT_UNAVAILABLE)` 안전 폴백 (`CR-16`).
  - NUL 바이트 포함 바이너리 페이로드 감지 시 즉시 `RAW(UNSUPPORTED_TYPE)` 거부 (`CR-04`).
  - `test.junit`: `junit_codec` 기반 T1..T5 불변량 검사, 토큰 이득(U2) 검증, 성공 시 `STRUCTURAL` 발행, 구문 오류 시 `RAW(PARSE_FAILED)` 폴백.
  - `json.api`: `json_codec` 기반 J1..J5 불변량 및 필수 포인터 검증, 성공 시 `STRUCTURAL` 발행.
  - `log.text`: L1..L5 충실도 게이트 평가 및 최소 토큰 이득 검증.
- **코덱 섀도 감사 모니터 (`CodecShadowAuditMonitor`, `CR-09`, `CR-57`)**:
  - `(source_kind, codec@version, provider)` 프로필별 감사 횟수, 결함 누락, 치명적 누락, 폴백 횟수를 계측.
  - Wilson 신뢰구간 하한 초과 또는 치명적 누락 발생 시 즉시 프로필을 `DISABLE` 상태로 전이하고 파이프라인에서 무손실 `RAW(PROFILE_DISABLED)`로 강제 전환.
- **제자리 재작성 비용 회계기 (`RewriteCostAccountant`, `CR-27`)**:
  - 세션 중간 제자리 히스토리 재작성으로 인한 캐시 접두사 무효화 비용을 계산하고 영수증 주석(`receipt_annotation`)에 추가 캐시 쓰기 토큰 및 ITE 할증액을 기록.
- **품질·승격·무결성 및 리뷰 신호 런타임 (`QualityAndIntegrityRuntime`, `CR-51~58`, `CR-62~64`, `CR-67`, `CR-77`, `CR-79`)**:
  - Tier A / Tier B 표본 크기 계약(`pairs_required_at_p_discordant_0.10`) 공식 일치성 검증 (`CR-51`).
  - 클러스터 부트스트랩 비열등성 평가 (`CR-52~55`) 및 Tier A/B 승격 판정(결함 회귀, 정책 위반, 비용) (`CR-56`).
  - 10배 속도 향상 사다리 주장 평가 (`CR-58`).
  - AST 오라클 분류기 정확도 검증(개발 말뭉치 exact ≥ 0.90, 홀드아웃 binary agreement ≥ 0.85, 거짓 강력 비율 ≤ 0.05) (`CR-77`).
  - 오라클 강도, 홀드아웃 완전성, 보상 해킹(갭 비율, 룩업 테이블, 테스트 변조)을 통합한 `GH_INTEGRITY` 평가 (`CR-62~64`, `CR-79`).
  - 실행 가능한 증거 없는 블로킹 지적을 권고로 강등하고 5건으로 상한 처리하는 리뷰 트리아지 (`CR-67`).

## 2. 검증 결과 및 근거

- **단위·수용 테스트 통과**:
  - `test_eval_runner_and_preflight_cr.py`: 5 passed
  - `test_codec_and_quality_runtime_cr.py`: 5 passed
  - 합계: 10 passed in 9.15s
- **정본 패키지 무결성 검증**:
  - `python -I docs/evoforge-v4.2/tools/validate_package.py`: PASSED (0 failure, C1..C9 전체 통과)
- **비변경 보존**:
  - 정본(`docs/evoforge-v4.2/`), `main.py`, 웹 UI, DB 마이그레이션은 일절 수정하지 않았다.
