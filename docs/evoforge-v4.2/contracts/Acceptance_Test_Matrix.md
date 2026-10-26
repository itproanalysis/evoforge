# EvoForge v4.2 — 수용 테스트 매트릭스

**실행 근거** 열의 표기: `SQL Txx` = `contracts/sql/context_plane_tests.sql`(39개 검사), `C-xx` = `contracts/sql/core_tests.sql`(57개 검사), `REF` = `reference_impl/test_reference.py`(22개), `QG` = `reference_impl/test_quality_gate.py`(23개), `PERF` = `reference_impl/test_performance.py`(39개, v4.1), `V42` = `reference_impl/test_v42.py`(28개, v4.2), `VAL` = `tools/validate_package.py` 스키마·의미 규칙(S1~S11). 모두 PostgreSQL 16.15 / Python 3.13에서 통과했다. **미구현**은 아직 실행 가능한 테스트가 없다는 뜻이다. 통과한 것은 계약 수준의 검사이며, 프로덕션 서비스를 시험한 결과가 아니다.

## A. Context Plane (CR-01 ~ CR-36)

| ID | 시나리오 | 기대 결과 | 실행 근거 |
|---|---|---|---|
| CR-01 | 압축 전 원문 저장·SHA 검증 | read-back 후 바이트 동일, 그 다음에만 ACTIVE | REF U1 (게이트 측) · Vault 왕복 **미구현** |
| CR-02 | 원문 저장 실패 | 손실 뷰 발행 불가, RAW(`VAULT_UNAVAILABLE`) 또는 BLOCK | SQL T04 · REF `test_vault_not_verified_blocks` |
| CR-03 | 실패 Assertion 요약 누락·의역 | 게이트 실패 → RAW(`FIDELITY_FAILED`) | REF `test_paraphrased_message_rejected`, `test_truncation_without_rule_rejected_in_safe` |
| CR-04 | 미지원/위험 입력(바이너리, DOCTYPE·ENTITY) | RAW(`UNSUPPORTED_TYPE`/`PARSE_FAILED`) | REF `test_entity_expansion_rejected`, `test_unknown_kind_is_raw` |
| CR-05 | 압축 후 토큰 미감소 | U2 실패 → RAW(`NO_TOKEN_GAIN`) | REF `test_no_gain_rejected` |
| CR-06 | 다른 테넌트가 ref로 GET | `not_found`(존재 여부 비노출), 0바이트, 플랫폼 보안 이벤트 | SQL T01·T03·T10 · 스키마 응답 규칙 |
| CR-07 | 같은 테넌트 다른 프로젝트 GET | `forbidden` + 감사 | SQL T02 (RLS가 프로젝트 단위) |
| CR-08 | Reviewer가 전체 Diff를 전달받지 못함 | 승인 거부 | SQL T12 |
| CR-09 | 압축 테스트 로그에서 실패가 사라지거나 0으로 보임 | T1/T2/T5 실패, 반복 시 프로필 비활성화 | REF `test_dropped_failure_rejected`, `test_zeroed_counts_rejected` |
| CR-10 | 리뷰 후 candidate head SHA 변경 | 승인 거부, 새 패킷 | SQL T12 (head moved) |
| CR-11 | 원문/뷰의 지시 탈취 문자열 | untrusted 등급 유지, L0/L1 진입 금지, 시스템 지시 승격 금지 | VAL S2 · 스키마 trust 규칙 · 런타임 인젝션 시험 **미구현** |
| CR-12 | 캐시 단독이 압축+캐시보다 쌈 | 압축하지 않음(`NET_COST_WORSE`) | REF `test_compression_without_cache_can_lose_to_cache_only` · 결정 로직 **미구현** |
| CR-13 | 청구 세부정보 없음 | `estimated`로만 표시, KPI 제외 | SQL T17 · C-13 · 스키마 receipt 규칙 |
| CR-14 | 복원 도구 없는 AI Chat | 승인자 배정 불가 | SQL T07 (chat 채널) · 스키마(리뷰어 recovery channel ≥1) |
| CR-15 | 권한 있는 Chat/Folder 복원 | ACL 범위만, 중복 요청 멱등 | 멱등: SQL T10 · Folder 어댑터 **미구현** |
| CR-16 | Vault 장애·Failover | Builder RAW 진행 가능, 리뷰어 증거는 ACTIVE 원문 필수 → 승인 차단 | SQL T21 |
| CR-17 | 고객 삭제 요청 | tombstone + DEK 파기, ref 폐기, 의존 패킷 REVOKED, legal hold 시 차단 | SQL T15·T18 · 인덱스/임베딩/백업 정리 **미구현** |
| CR-18 | 5-Agent 압축/캐시 A/B | 같은 품질 게이트, 실측 비용·시간 분리 기록 | **미구현**(P0-7) |
| CR-19 | 민감자료의 미승인 공급사 전송 | 경로 차단 | REF U4(뷰 2차 검사) · 라우팅 정책 **미구현** |
| CR-20 | 저장 용량 초과 | 임의 evict 금지, 명시적 실패 | **미구현** |
| CR-21 | 동일 요청 재처리 | 패킷 1개, 감사 1행, receipt 1행 | SQL T09·T10·T17 |
| CR-22 | 목표 버전 변경 | 패킷 STALE, 승인 차단, 되살리기 불가 | SQL T14 |
| CR-23 | 압축 엔진 공급망 스캔 실패 | 배포 거부, 기존 버전 유지 | **미구현**(CI) |
| CR-24 | 신규 codec 기능 플래그 OFF | 기존 경로 정상 | **미구현** |
| CR-25 | 같은 계약·역할의 연속 턴 | L0–L2 세그먼트 해시 동일 → 공급사 캐시 적중 | 스키마 segment sha256 · Compiler **미구현** |
| CR-26 | 플랫폼 키에서 두 테넌트가 같은 프롬프트 | L0 해시가 다름(네임스페이스 솔트), 교차 캐시 읽기 0 | 스키마 `cache_namespace_id` 필수 · Compiler **미구현**(M0) |
| CR-27 | codec 비결정성 / 이력 재작성 | U3 실패 / 재작성 비용 receipt 기록 | REF `test_deterministic`, `test_nondeterministic_codec_rejected`, `test_rewrite_in_place_costs_more` |
| CR-28 | 복원률이 손익분기 70% 초과 | 다음 패킷부터 RAW(`NET_COST_WORSE`) | REF `test_retrieval_break_even_exists` · 결정 로직 **미구현** |
| CR-29 | 캐시를 끌 수 없는 모델에서 A0 arm 요청 | 계획 거부(S6) | VAL `nocache_on_undisableable_provider.json` |
| CR-30 | JSONPath/정규식/`..` 경로 selector | 스키마 거부 | VAL `jsonpath_selector.json`, `path_traversal_selector.json` |
| CR-31 | 순차·추측 가능한 ref | 형식 거부 | VAL `sequential_ref.json` · SQL T19 |
| CR-32 | 대형 Diff(> `max_reviewable_diff_bytes`) | PR 분할 또는 인간 리뷰어 요구, chunk 리뷰 커버리지 합산 | 커버리지 합산: SQL T12 · 분할 정책 **미구현** |
| CR-33 | Registry 엔트리 14일 초과 | explicit/NONE 계획 불가 | VAL `stale_registry_entry.json` |
| CR-34 | Seeded-defect canary | 프로필·모델별 검출률 측정, 기준 미달 구성 승인자 풀 제외 | **미구현**(평가 하네스) |
| CR-35 | BSL 경로 코드·의존성 유입 | 빌드 실패(SBOM·라이선스 스캔) | **미구현**(CI) |
| CR-36 | JSON 배열 절단 시 규칙 일치 원소 누락 | J5 실패 | REF `test_failed_records_beyond_head_kept`, `test_rule_violation_rejected` |

## B. Core Plane — 플랫폼 키·명령·실행·병합 (CR-37 ~ CR-48)

| ID | 시나리오 | 기대 결과 | 실행 근거 |
|---|---|---|---|
| CR-37 | 공급사 호출 전 예약 | 예약 없는 호출 0, receipt에 `reservation_key` 필수 | C-13 · 스키마 receipt(`receipt_without_reservation.json` 거부) |
| CR-38 | 선결제 잔액 0 / 프로젝트 상한 초과 | `CREDIT_EXHAUSTED` / `BUDGET_EXCEEDED`, 호출 안 함 | C-13 |
| CR-39 | 추정보다 큰 실제 사용 | `overrun` 표시, 원장은 실제 금액 | C-13 |
| CR-40 | 원장 정정 | 수정·삭제 불가, 정확히 상쇄하는 역분개 1회만 | C-14 |
| CR-41 | BYOK 영수증 | 스키마 거부(범위 밖) | VAL `receipt_byok.json` |
| CR-42 | 명령 재전송·오래된 버전·STOP_ALL | 같은 command_id, 409, 안전 명령은 fast lane 접수 | C-02 |
| CR-43 | 위험 명령 확정 생략 | `PLANNED` 진입 거부 | C-03, C-04 |
| CR-44 | 동시 Claim·만료 Lease·늦은 쓰기 | 1명만 성공, epoch 증가, `STALE_WRITE` | C-05, C-06, C-15 |
| CR-45 | 병합 승인 | 게이트 누락·INCONCLUSIVE·독립 approve 없음·head 이동·고위험 인간 승인 없음·나중 차단 리뷰 → 거부 | C-07, C-08, C-09 |
| CR-46 | 증거 불변 | 게이트·리뷰·승인·이벤트·원장 수정/삭제 불가 | C-10, C-11, C-14 |
| CR-47 | 외부 부작용 UNKNOWN | 조회 없이 재시도 거부, 확정 시 외부 ID 필수, 중복 예약 거부 | C-12 |
| CR-48 | 테넌트·프로젝트 격리 | 다른 조직·프로젝트 데이터·잔액 비가시, 교차 쓰기 거부, DELETE 권한 없음 | C-01 |
| CR-49 | 공정 큐(공유 공급사 한도) | 한 테넌트 폭주 시 다른 테넌트 대기 p95 증가 ≤ 20% | **미구현**(M4 부하 시험) |
| CR-50 | 플랫폼 키 복호화 | Broker 외 신원 복호화 성공 0 | **미구현**(M0 IAM 시험) |

## C. 품질 판정 (CR-51 ~ CR-58)

| ID | 시나리오 | 기대 결과 | 실행 근거 |
|---|---|---|---|
| CR-51 | 계약 수치와 공식 일치 | `pairs_required` = 공식 계산값 | QG `test_contract_numbers_match_formula` |
| CR-52 | 동등한 후보 | Tier A 통과 | QG `test_equivalent_arm_passes_tier_a` |
| CR-53 | 열화된 후보 | FAIL(하한 ≤ −δ) | QG `test_degraded_arm_fails` |
| CR-54 | 작은 표본 | UNDERPOWERED, 승격 불가 | QG `test_small_sample_is_underpowered_not_pass` |
| CR-55 | 반복 상관 | cluster bootstrap 구간이 독립 가정보다 넓음 | QG `test_cluster_bootstrap_is_wider_than_naive` |
| CR-56 | 안전 0 허용 | 기준만 잡은 critical defect 1건·회귀 유출 1건·seeded 부족 → 실패 | QG `Safety.*` |
| CR-57 | codec 런타임 | critical miss·높은 miss율 → DISABLE, 감사 부족 → 경보, 폴백 과다 → 효율 검토 | QG `Runtime.*` |
| CR-58 | 리뷰어 자격·10X 문구 | 97/100 통과·95/100 탈락·오차단 초과 탈락·정밀도 증거 없음 탈락, 공개 문구는 하한 | QG `Reviewer.*`, `Speedup.*` |

## D. v4.1 성능·무결성 + v4.2 마감 (CR-59 ~ CR-79)

근거 논문과 채택 고리는 `research/Technology_Radar_2026-10.md`에 있다. 수치는 `contracts/quality_gates.json` v1.1에서 읽는다.

| ID | 시나리오 | 기대 결과 | 실행 근거 |
|---|---|---|---|
| CR-59 | 두 모듈 + 공통 타입 파일 / 강결합 / 작은 과제 | 허브는 wave 0로 분리, 응집 파티션 2개 → DAG_PARALLEL. 강결합·작은 과제 → SINGLE. 같은 입력 → 같은 계획 | PERF `Partitioner.*` |
| CR-60 | 각 패치 단독 통과, 결합 시 실패 | `GC_COMPOSITION=FAIL`, 원인 쌍 특정, 병합 차단. 단독으로 이미 깨진 테스트는 간섭 아님. wave에 후보 2개 이상이면 게이트 누락 시 병합 거부 | C-17 · PERF `Composition.test_interference_blocks_and_is_attributed` |
| CR-61 | 다른 Builder가 공개 함수 시그니처를 바꾸거나 삭제 | 그 심볼을 참조하는 Builder에게만 통지, 자기 변경·추가는 통지 안 함 | PERF `Composition.test_notice_goes_only_to_referencing_builder` |
| CR-62 | 실행만 하는 테스트·존재 확인·mock 호출 확인·동어반복 | 약한 오라클로 분류, 새 테스트 강한 비율 < 0.8이면 `GH_INTEGRITY` FAIL. 테스트 없음도 FAIL | C-16 · PERF `Oracle.*` |
| CR-63 | 공개 검증 대비 held-out 격차, 입력별 상수 반환, 테스트 skip·assert 삭제·예외 삼킴 | 각각 flag, 하나라도 있으면 후보 탈락 | C-16 · PERF `RewardHack.*` |
| CR-64 | held-out이 단위 테스트만 | 불완전 판정(합성·부정 필수, 과제당 3개 이상) | PERF `RewardHack.test_heldout_must_be_compositional_and_negative` |
| CR-65 | 증거가 다른 후보 / 하드 필터 위반 / 증거 동점 / full-pass 행동 불일치 | 증거가 판정을 이긴다, 탈락 후보는 선택 불가, 동점만 토너먼트, 불일치면 추가 샘플, LOW는 첫 full-pass에서 멈춤 | PERF `Selection.*` |
| CR-66 | HIGH 후보: 일반 approve + 인간 승인 / 명세 선행 순서 위반 / 자격 없음 / 다른 하네스 자격 / 반례 아닌 피드백 | 모두 병합 거부. 자격 + 컨텍스트 독립 + 명세 선행 approve + 인간 승인이 모두 있어야 병합. 같은 공급사 모델이라도 허용 | C-18 · C-19 · PERF `ReviewPolicy.*` |
| CR-67 | 증거 없는 changes_requested / 증거 없는 차단 지적 | DB가 거부(CHECK) / advisory로 강등, 후보당 5개 노출 | C-19 · PERF `ReviewPolicy.test_blocking_needs_executable_evidence` |
| CR-68 | recall 100%지만 지적 대부분이 잡음 | 리뷰어 자격 탈락(정밀도 Wilson 하한 < 0.40) | QG `Reviewer.test_noisy_reviewer_does_not_qualify` |
| CR-69 | L3에 캐시 breakpoint / 도구 결과가 캐시 prefix 안 | S11 위반 | VAL `breakpoint_on_task_delta.json`, `tool_output_in_cached_prefix.json` |
| CR-70 | 쓰기와 읽기가 섞인 무작위 호출열 300개 | 투기 결과가 순차 실행과 항상 동일(거짓 수락 0), 부작용 종류는 투기 안 함 | PERF `Speculation.*` |
| CR-71 | 보정 표본 부족 / critic·HIGH 요청 | cascade 비활성 / 항상 강한 모델. 활성 시 수락 오류 Wilson 상한 ≤ 5% | PERF `Cascade.*` |
| CR-72 | 안전 지표에 PPI / 라벨 부족 / 쓸모없는 autorater | NOT_ALLOWED / UNDERPOWERED / λ→0으로 편향 없음 | PERF `PPI.*` |
| CR-73 | 검증 안 된 교훈 / 다른 단계·테넌트·저관련 / 두 번째 회상 / 원 Run 삭제 | 적재 거부 / 회상 안 됨 / 퇴출 / 함께 삭제 | PERF `Memory.*` |
| CR-74 | 평가 샌드박스에 미래 커밋·remote·태그·alternates 존재 | base 도달 객체만으로 재구성, 감사 7항목 통과, 미래 커밋 내용 접근 불가, scaffold 5필드 없는 점수 거부. 대조: 일반 clone + checkout은 미래 커밋을 남김 | V42 `Hygiene.*`(실제 git) · 평가 러너 통합 **미구현**(M0) |
| CR-75 | 압축 경계 직후 성능 | 4조건(성공 비열등, 반복 탐색·막힌 행동 비율 상한, 불안정 증가) 모두 통과해야 PASS, 세션 < 30은 UNDERPOWERED | V42 `CompactionEval.*` · 실제 continuation 수집 **미구현**(M3) |
| CR-76 | 하네스 최적화기 | GEPA가 아닌 기준선 거부, 비개선 패치 비후보, dev 1위·GEPA 우월만 동결, 동결 후 패치 거부, test 1회, Trust Kernel·anchor·예산 위반 거부, 패치에 test 결과 표현 불가 | V42 `Optimizer.*` · VAL `harness_patch_*.json` · 실제 최적화 루프 **미구현**(M6) |
| CR-77 | 오라클 분류기 정확도 | 개발 말뭉치 100%, holdout 강/약 일치 ≥ 0.85, 약→강 오판 ≤ 5% | V42 `OracleAccuracy.*` |
| CR-78 | AST 동시 변경 통지 | 메서드·기본값 시그니처 변경 통지, 본문만 변경·비공개·추가 심볼 통지 0, 비Python은 diff 대체 | V42 `AstNotices.*` |
| CR-79 | GH_INTEGRITY 판정 매핑 | 해킹·변조 FAIL, held-out 불완전 INCONCLUSIVE, 오라클 미달은 holdout < 200이면 INCONCLUSIVE·이상이면 FAIL | V42 `Integrity.*` |

## 요약
- A(36개): 실행 근거가 하나 이상 있는 항목 30개, 완전 미구현 6개(CR-18, CR-20, CR-23, CR-24, CR-34, CR-35).
- B(14개): 12개가 DB·스키마 수준에서 실행 검증됨, 2개(CR-49, CR-50)는 런타임 구성요소가 필요해 **미구현**.
- C(8개): 모두 참조 구현 테스트로 검증됨.
- D(21개): 21개 모두 참조 구현·DB·validator 수준의 실행 근거가 있음. CR-74·75·76은 규칙 계층이 검증됐고, 실제 평가 러너(M0)·continuation 수집(M3)·최적화 루프(M6) 통합은 **미구현**.
- 통과한 것은 계약 수준 검사다. 프로덕션 서비스를 시험한 결과가 아니다. 마일스톤별 수용 기준은 통합 기획서 p.49와 `Context_Mesh_Spec.md` §15에 있다.
