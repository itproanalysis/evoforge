# M0 위생 평가 러너·Broker/CLI 사전 바인딩/예약 가드 및 다중 코덱·섀도 감사·승격 게이트 런타임

갱신: 2026-10-27. 본 문서는 `DEVELOPMENT_STATUS.md`(98, 99행) 및 `Acceptance_Test_Matrix.md`(`CR-03`, `CR-04`, `CR-05`, `CR-09`, `CR-27`, `CR-29`, `CR-33`, `CR-36`, `CR-37`, `CR-38`, `CR-41`, `CR-51`..`CR-58`, `CR-62`..`CR-64`, `CR-67`, `CR-74`, `CR-77`, `CR-79`)에 해당하는 런타임 모듈 및 수용 테스트 구현·검증 결과를 기록한다.

## 1. 구현 모듈 및 계약 매핑

### 1.1 [`services/api/evoforge/eval_runner_and_preflight.py`](../services/api/evoforge/eval_runner_and_preflight.py)
- **M0 위생 평가 러너 통합 (`HygieneEvalRunner`, `CR-74`, `D-050`)**:
  - `verify_naive_clone_vs_hygiene_sandbox`: 일반 `git clone` + `git checkout <base>`는 미래 커밋(정답 패치·태그·remote)을 객체 저장소에 남겨 누출하지만, `eval_hygiene.build_sandbox_repo`는 base 도달 가능 객체만으로 새 저장소를 재구성하여 미래 커밋 블롭 접근을 원천 차단하고 7항목 감사(`no_remote`, `single_base_ref`, `head_is_base`, `no_alternates`, `empty_reflog`, `future_commits_absent`, `all_commits_ancestors_of_base`)를 통과함을 실증한다.
  - `evaluate_candidate_in_sandbox`: 실행 전·후 7항목 위생 감사, 후보 패치 적용 후 `visible` 및 격리된 `heldout` 스위트 실행, `GH_INTEGRITY`·`G2_REQUIRED` 게이트 판정, 그리고 5필드 scaffold 메타데이터(`name`, `version`, `turn_cap`, `model`, `harness_version`)와 무결성 위반 0건을 강제하는 `eval_hygiene.score_record` 생성을 단일 파이프라인으로 통합한다.
- **Broker 및 개발 CLI 사전 바인딩·예약·영수증 가드 (`PreflightCallBroker`, `DevBuilderCLIGuard`, `CR-29`, `CR-33`, `CR-37`, `CR-38`, `CR-41`)**:
  - `validate_packet_and_registry`: 호출 전 `context-packet.v2.schema.json` 및 `validate_package.semantic()`(S1–S11)을 검사하며, 캐시 비활성화가 불가능한 공급사/모델에서의 `A0_RAW_NOCACHE`/`cache_mode="NONE"` 요청(`CR-29`, `CACHE_DISABLE_UNSUPPORTED`)과 14일(`max_age_days`)을 초과한 레지스트리 엔트리(`CR-33`, `REGISTRY_ENTRY_STALE`)를 즉시 차단한다.
  - `prebind_and_reserve` & `validate_and_settle_receipt`: 공급사 허용 목록·테넌트 공급사 동의·활성 리스(`lease_epoch`, 만료 시각)를 확인하고, 호출 전 원자적 비용 예약(`CR-37`)을 수행한다. 선불 잔액 부족(`CREDIT_EXHAUSTED`) 또는 프로젝트 상한 초과(`BUDGET_EXCEEDED`) 시 공급사 호출을 0건으로 차단하며(`CR-38`), 정산 시 `provider-usage-receipt/v1` 스키마·`reservation_key` 일치·`billing_owner="platform"`(`CR-41`, BYOK 거부)을 검증한다.
  - `DevBuilderCLIGuard`: 개발자 Muse Builder CLI 태스크 실행을 사전 패킷 바인딩·프로젝트 예산 예약·정식 영수증 발행/정산 경로 안에서만 수행하도록 강제한다.

### 1.2 [`services/api/evoforge/codec_and_quality_runtime.py`](../services/api/evoforge/codec_and_quality_runtime.py)
- **다중 코덱 파이프라인 및 독립 Fidelity Gate (`MultiCodecPipeline`, `CR-03`, `CR-04`, `CR-05`, `CR-09`, `CR-27`, `CR-36`)**:
  - `EvidenceVault` 저장 및 read-back SHA-256 검증(`U1`) 후 `junit.structural`(`T1–T5`), `json.structural`(`J1–J5`), `log.text`(`L1–L5`) 코덱과 게이트를 실행한다.
  - 바이너리 입력 및 미등록 `source_kind`는 `RAW(UNSUPPORTED_TYPE)`(`CR-04`), XML `<!DOCTYPE`/`<!ENTITY` 확장 폭탄 및 구문 오류는 파싱 전 `RAW(PARSE_FAILED)`(`CR-04`), 토큰 미감소 뷰는 `RAW(NO_TOKEN_GAIN)`(`CR-05`), 비결정적 코덱(`U3` 실패)·실패 케이스 누락/카운트 0 위조(`CR-09`)·`SAFE` 프로필의 무규칙 배열 절단 및 규칙 일치 원소 누락(`CR-36`, `J5`)은 `RAW(FIDELITY_FAILED)`로 폴백한다.
- **코덱 런타임 섀도 감사 모니터 (`CodecShadowAuditMonitor`, `CR-09`, `CR-57`)**:
  - `(source_kind, codec@version, provider)` 프로필별 섀도 감사 및 폴백 통계를 집계하여 `quality_gate.codec_runtime_decision`을 수행하고, 치명적 누락(`critical_misses > 0`) 또는 목표 누락률 초과 시 해당 프로필을 자동 비활성화(`DISABLE` → 이후 모든 요청 `RAW(PROFILE_DISABLED)`)한다.
- **제자리 이력 재작성 비용 회계기 (`RewriteCostAccountant`, `CR-27`)**:
  - 세션 중간 제자리 재작성(`rewrite_at=turn`)으로 인한 캐시 prefix 무효화 추가 비용(`surcharge_ite`, `cache_write_surcharge_tokens`)을 계산하고 영수증 주석으로 기록한다.
- **품질 판정·승격·오라클 정확도·리뷰 신호 분류 런타임 (`QualityAndIntegrityRuntime`, `CR-51`..`CR-58`, `CR-62`..`CR-64`, `CR-67`, `CR-77`, `CR-79`)**:
  - 표본 크기 공식 일치(`CR-51`), 클러스터 부트스트랩 비열등성·Tier A/B 승격·안전 0 허용 게이트·10X 사다리 하한 문구(`CR-52`..`CR-58`), AST 오라클 분류기 개발/홀드아웃 말뭉치 정확도 검증(`CR-77`), `GH_INTEGRITY` 판정 매핑(`CR-62`..`CR-64`, `CR-79`), 실행 가능한 증거가 없는 차단 지적의 advisory 강등 및 후보당 5개 상한(`CR-67`)을 통합한다.

## 2. 검증 명령

```powershell
python -I docs/evoforge-v4.2/tools/validate_package.py
python -m pytest services/api/tests/test_eval_runner_and_preflight_cr.py services/api/tests/test_codec_and_quality_runtime_cr.py -q -p no:cacheprovider
python -m pytest services/api -q -p no:cacheprovider
```
