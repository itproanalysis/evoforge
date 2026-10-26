# EvoForge v3.6 — Context Fidelity & Efficiency 수용 테스트

**실행 근거** 열에서 `SQL Txx`는 `contracts/sql/context_plane_v3_6_tests.sql`(PostgreSQL 16, 39개 검사 통과), `REF`는 `reference_impl/test_reference.py`(22개 통과), `VAL`은 `tools/validate_package.py`의 스키마/의미 규칙 검사다. **미구현**은 아직 실행 가능한 테스트가 없다는 뜻이다. 통과한 것은 계약 수준의 검사이며, 프로덕션 서비스를 시험한 결과가 아니다.

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
| CR-13 | 청구 세부정보 없음 | `estimated`로만 표시, KPI 제외 | SQL T17 · 스키마 receipt 규칙 |
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
| CR-26 | 플랫폼 키에서 두 테넌트가 같은 프롬프트 | L0 해시가 다름(네임스페이스 솔트), 교차 캐시 읽기 0 | **미구현**(P0-5) |
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

## 요약
- 실행 가능한 근거가 하나 이상 있는 항목: 36개 중 29개(상당수는 계약·DB 수준 검사이고, 런타임 구성요소 시험은 아님). 완전히 미구현인 항목: 7개(CR-18, 20, 23, 24, 26, 34, 35).
- 런타임 구성요소가 있어야 시험할 수 있는 항목(Vault 왕복, Gateway, Compiler, A/B 하네스, CI 공급망)은 **미구현**으로 표기했다. P0 단계별 수용 기준은 기술 명세 §15에 있다.
