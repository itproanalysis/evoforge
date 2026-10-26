<!-- PAGE:22/50 -->

# 22. Provider Broker와 플랫폼 키

> **목적:** EvoForge가 보유한 공급사 키로 안전하게, 공정하게, 싸게 모델을 호출한다. · **결정:** D-017, D-019, D-026, D-029, D-034, D-048 · **계약:** `contracts/registry/provider_capabilities.seed.json`, `contracts/schemas/provider-usage-receipt.v1.schema.json`

### 키 보관(플랫폼 키)
- 공급사 계정·키는 EvoForge 소유다. KMS 기반 비밀 저장소에 envelope 암호화로 보관하고, 복호화 권한은 **Broker 서비스 신원 하나**에만 준다. 사람·Runner·Codec Worker·Chat UI는 키를 읽을 수 없다.
- 환경(dev/staging/prod)마다 다른 키, 정기 회전(제안 90일)과 사고 시 즉시 회전. 회전 중 활성 Run은 안전하게 재시작된다.
- 공급사가 프로젝트·워크스페이스 단위 분리를 지원하면 **테넌트(또는 테넌트 그룹)별 하위 키**를 써서 사용량 귀속과 사고 반경을 줄인다. 지원하지 않는 공급사는 공유 키 + 아래 격리 규칙으로 운영한다. 실제 지원 여부는 M0에서 공급사별로 확인한다.

### Broker
- 어댑터: OpenAI, Anthropic, Google, Meta, OpenAI-compatible. **공식 SDK + 고정 의존성 + 자체 TypeScript Broker.** LiteLLM은 2026-10-21 v1.107.0 배포물 침해 사고 이후 기본 의존성에서 제외한다. 제3자 게이트웨이는 격리·출처 증명·보안 승인 후에만 선택 어댑터로 검토한다.
- 표준 결과: `provider_call_id`, `provider_request_id`, `model_revision`, 시각, 입력/캐시 쓰기/캐시 읽기/출력 토큰, `reported_cost`, `estimated_cost`, `status`, `retriable`, `data_policy_id` → `provider-usage-receipt.v1`.
- 호출 순서: allowlist 확인 → `core.reserve_cost`(보수적 최대 비용) → `side_effect_intents`에 `provider.call` 예약 → 호출 → receipt 기록 → `core.settle_reservation`. 결과가 불명확한 호출은 공급사 조회 후에만 다시 시도한다.
- 실패 전략: 429/5xx 분류, `Retry-After` + 지수 백오프 + jitter, 공급사별 circuit breaker. 대체 모델은 **같은 프로젝트 allowlist 안에서만**. 민감 자료를 새 공급사로 보내려면 사전 동의가 필요하다.

### 공정성(공유 한도)
공급사 조직 한도(RPM/TPM)는 모든 테넌트가 공유한다. 공급사×모델 단위 전역 토큰 버킷 아래에 **테넌트별 가중 공정 큐**(가중치 = 플랜)를 두고, 테넌트별 TPM 상한을 플랜에서 도출한다. 한 테넌트의 폭주가 다른 테넌트의 대기시간 p95를 정해진 한도 이상 늘리지 못하게 한다.

### 캐시와 격리
- Prompt 레이아웃: `L0_PLATFORM`(테넌트 cache namespace 솔트 + 시스템·도구 스키마) → `L1_TENANT_CONTRACT` → `L2_ROLE_SCOPE` → `L3_TASK_DELTA`. 안정 Prefix는 앞, 변하는 부분은 뒤. 휘발성 메타데이터는 렌더링하지 않는다(`evoforge-canonical/v1`).
- **캐시 배치 규칙 S11(D-048).** 명시 캐시 breakpoint는 L0–L2 세그먼트에만 둔다. 도구 결과(`verified_tool_output`)와 비신뢰 콘텐츠(`untrusted_content`)는 마지막 breakpoint **뒤**에만 둔다. 동적 결과가 캐시 블록 안에 들어가면 매 호출 캐시 쓰기가 발생하고 적중이 깨진다(2601.06007). validator가 패킷마다 검사한다.
- 플랫폼 키에서는 **테넌트별 32바이트 무작위 솔트를 L0 맨 앞에 넣는 것이 필수**다(D-026). 테넌트 간 Prefix가 절대 같아지지 않아 캐시 타이밍 사이드채널과 귀속 오류를 막는다. OpenAI `prompt_cache_key`는 회계 보조로만 쓴다.
- 공급사별 캐시 규약(자동 여부, 끌 수 있는지, 브레이크포인트, 최소 길이, 쓰기/읽기 배수, usage 필드)은 Registry가 정본이며 14일이 지나면 만료된다. 2026-10-25 시드: OpenAI GPT-5.6+ explicit 모드 지원·이전 모델 자동만, Anthropic `cache_control` 최대 4개·최소 512토큰(현행 모델), Gemini 2.5+ 암묵 캐시·Gemini 4는 explicit 미지원.
- 모델 간 KV 공유·이식은 하지 않는다. 공급사를 바꾸면 `ContextPacket`을 다시 만든다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R22-1 | 키 비노출 | Broker 외 신원의 키 복호화 시도 0건 성공, 시도는 보안 이벤트 |
| R22-2 | 예약 없는 호출 0 | 모든 receipt에 `reservation_key`가 있음(스키마 필수) |
| R22-3 | 공정성 | 부하 시험에서 한 테넌트가 한도의 10배를 요청해도 다른 테넌트 큐 대기 p95 증가 ≤ 20%(제안값) |
| R22-4 | 캐시 격리 | 같은 프롬프트의 두 테넌트 L0 해시가 다름, 교차 캐시 적중 0 (CR-26) |
| R22-5 | 공급사 사고 대응 | 공급사·SDK 사고 시 해당 어댑터를 1분 안에 비활성화하는 스위치 + runbook |
| R22-6 | 캐시 배치 | L3 breakpoint 또는 캐시 prefix 안의 도구 결과가 있는 패킷 발행 0건 (CR-69, S11) |

---
