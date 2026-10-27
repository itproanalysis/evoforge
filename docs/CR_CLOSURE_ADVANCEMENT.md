# Context Mesh·리뷰어 자격·공급망/공정 큐/키 격리 고도화 검증 기록

갱신: 2026-10-27 (Asia/Seoul). `docs/evoforge-v4.2/`의 정본 계약(JSON Schema, `quality_gates.json` v1.2, `vocabulary.json` v4.2, `reference_impl/*`)을 수정하지 않고, `Acceptance_Test_Matrix.md`와 `SERVICE_STATUS.md` P1의 미구현·미검증 시나리오를 API 런타임 모듈과 수용 테스트로 구현·검증했다.

## 1. 구현 모듈 및 계약 매핑

| 모듈 | 구현 기능 | 수용 매트릭스 / 명세 근거 |
|---|---|---|
| [`services/api/evoforge/context_mesh.py`](../services/api/evoforge/context_mesh.py) | 결정적 `log.text` 코덱(`encode_log`) 및 독립 파서 기반 **L1–L5 Fidelity Gate**(`log_fidelity_checks`, `evaluate_fidelity_gate`): `WARN` 이상 보존·중복 그룹 `Σcount` 일치(L1), 시작/종료 N줄 원문 유지(L2), 생략 구간 `lines:S-E` 기록(L3), `critical_assertions` 토큰 포함 줄 원문 보존(L4), 타임스탬프/줄번호 단조성(L5) 및 게이트 실패 시 `RAW(FIDELITY_FAILED)` 폴백 | `Context_Mesh_Spec.md` §6, CR-03, L1–L5 |
| [`services/api/evoforge/context_mesh.py`](../services/api/evoforge/context_mesh.py) | **Evidence Vault**(`EvidenceVault`): 블롭별 256-bit DEK 포락선 암호화, 저장 직후 복호화 read-back 바이트·SHA-256 일치 확인 후에만 `ACTIVE` 전환(CR-01), 명시적 용량 상한 초과 시 임의 evict 없이 거부(CR-20), 고객 삭제 요청 시 `legal_hold` 차단·DEK 파기·tombstone·검색/임베딩 색인 제거·의존 패킷 `REVOKED` 전이(CR-17), Vault 장애 시 Builder `RAW(VAULT_UNAVAILABLE)` 폴백 및 Critic 승인 패킷 차단(CR-16) | CR-01, CR-02, CR-16, CR-17, CR-20 |
| [`services/api/evoforge/context_mesh.py`](../services/api/evoforge/context_mesh.py) | **Retrieval Gateway & Folder Bridge 어댑터**(`RetrievalGateway`): `evidence-retrieval.v1.schema.json` 입출력 검증, 외부 테넌트·미존재 `ref`에 대해 구별 불가능한 `not_found`(0바이트) 응답 및 `security_events` 기록(CR-06), 동일 테넌트 타 프로젝트 `forbidden` 감사(CR-07), `GET_EVIDENCE.*.request.json` Folder Bridge 어댑터 및 `(actor_tenant_id, request_id)` 멱등성·단일 감사 행 보장(CR-15, CR-21) | CR-06, CR-07, CR-15, CR-21, CR-22 |
| [`services/api/evoforge/context_mesh.py`](../services/api/evoforge/context_mesh.py) | **온라인 컨텍스트 결정 엔진 및 5-Agent A/B 계측**(`ContextDecisionEngine`): 코덱 기능 플래그 OFF 시 `RAW(PROFILE_DISABLED)` 정상 폴백(CR-24), 공급사 캐시 적용 `A_RAW` 실측 기준선 대비 압축 순편익이 없거나 비캐시 압축이 더 비쌀 때 `RAW(NET_COST_WORSE)` 선택(CR-12), 세션당 평균 복원 횟수가 손익분기(`cost_model.break_even_retrievals`)의 70%를 초과하면 다음 패킷부터 `RAW(NET_COST_WORSE)` 전환(CR-28), 5좌석(1–5) 압축/캐시 A/B 실험의 품질 게이트·비용(µUSD)·소요 시간(ms) 분리 집계(CR-18) | CR-12, CR-18, CR-24, CR-28 |
| [`services/api/evoforge/context_mesh.py`](../services/api/evoforge/context_mesh.py) | **Context Packet v2 컴파일러**(`ContextPacketCompiler`): `context-packet.v2.schema.json` 및 `validate_package.semantic()`(S1–S11) 전수 검증, 비신뢰 입력의 프롬프트 인젝션 탐지·`trusted_contract` 승격 및 `L0/L1` 진입 원천 차단·마지막 `cache_breakpoint` 뒤(`L3_TASK_DELTA`) 배치 강제(CR-11, S2, S11), 미승인 공급사로의 민감자료 라우팅 차단(CR-19), 동일 테넌트·계약·역할의 연속 턴에서 휘발성 메타데이터를 제외한 `L0–L2` 세그먼트 SHA-256 동일성 보장(CR-25), 테넌트별 32바이트 무작위 솔트(`cache_namespace_id`)를 `L0_PLATFORM` 선두에 반영해 테넌트 간 `L0` 해시 분리(CR-26) | CR-11, CR-19, CR-25, CR-26, S1–S11 |
| [`services/api/evoforge/review_qualification.py`](../services/api/evoforge/review_qualification.py) | **대형 Diff 분할 및 Review Coverage 원장**(`plan_diff_review`, `ReviewCoverageLedger`): `max_reviewable_diff_bytes`(409,600B) 초과 Diff에 대해 단일 자동 리뷰 거부 및 PR 분할/인간 리뷰어 요구(`REQUIRES_SPLIT_OR_HUMAN`, CR-32), `max_safe_context_bytes` 초과 Diff의 hunk 단위 `review_chunk` 분할 + `review_cross_chunk` 색인 패스 계획, 해당 리뷰어 `agent_id`에게 `ALLOW`로 전달된 바이트 구간의 합집합(`range_agg`)으로 `requires_original` 100% 전달·후보 head SHA 일치·비작성자·복원 채널 보유 검증(CR-08, CR-10, CR-14, CR-32) | `Context_Mesh_Spec.md` §8, CR-08, CR-10, CR-14, CR-32 |
| [`services/api/evoforge/review_qualification.py`](../services/api/evoforge/review_qualification.py) | **Seeded-Defect Canary 및 리뷰어 자격 시험 풀**(`ReviewerQualificationPool`): `quality_gate.reviewer_qualification`(critical seeded ≥ 100, recall Wilson 하한 ≥ 0.90, clean ≥ 100, 오차단 ≤ 10%, 지적 정밀도 SNR ≥ 100건·Wilson 하한 ≥ 0.40) 판정(CR-58, CR-68), seeded-defect canary 검출률(`context_fidelity_probe_score`) 미달 시 승인자 풀에서 즉시 제외(CR-34), 모델 리비전·하네스 버전·컨텍스트 프로필 변경 시 재자격 요구 및 `HIGH/CRITICAL` 독립성(`review_policy.check_independence`) + 인간 승인 통합 검사(CR-66) | CR-34, CR-58, CR-66, CR-68 |
| [`services/api/evoforge/runtime_guards.py`](../services/api/evoforge/runtime_guards.py) | **공급망·BSL-1.1·금지 의존성 스캐너 및 코덱 릴리스 가드**(`scan_supply_chain`, `CodecReleaseManager`): Python/npm 매니페스트와 소스 코드에서 BSL-1.1 라이선스, `caveman*` 패키지/임포트, `litellm`, 커밋 SHA 미고정 git URL 탐지 및 결정적 SBOM 다이제스트 생성(CR-35, ADR-036R, D-017), 코덱 배포 시 공급망 스캔·번들 SHA-256·결정성 자체 시험 실패 시 배포를 거부하고 기존 활성 버전 유지(CR-23) | CR-23, CR-35, ADR-036R |
| [`services/api/evoforge/runtime_guards.py`](../services/api/evoforge/runtime_guards.py) | **테넌트 가중 공정 큐 및 플랫폼 키 KMS 격리 가드**(`TenantFairScheduler`, `PlatformKeyVault`): 공유 공급사 한도에서 단일 테넌트 폭주(25배 트래픽 집중) 시 Start-Time Fair Queuing으로 정상 테넌트 대기시간 p95 증가율을 ≤ 20% 이내로 억제(CR-49), 플랫폼 공급사 키 포락선 암호화 및 `provider_broker` 신원 외 모든 신원(`codec_worker`, `runner`, `critic`, `web_bff` 등)의 복호화 성공 0건 강제·보안 이벤트 기록(CR-50) | CR-49, CR-50, ADR-047 |

## 2. 재현 및 검증 명령

저장소 루트에서 실행:

```powershell
python -m pytest services/api/tests/test_context_mesh_cr.py services/api/tests/test_review_qualification_cr.py services/api/tests/test_runtime_guards_cr.py -q
python -m pytest services/api -q
python -I docs/evoforge-v4.2/tools/validate_package.py
```

## 3. 확인 범위와 미검증 경계

- 신규 수용 테스트 **15 passed** (`test_context_mesh_cr.py` 8개, `test_review_qualification_cr.py` 3개, `test_runtime_guards_cr.py` 4개).
- 전체 API 테스트 스위트 및 `validate_package.py` C1–C7·C9(참조 구현 112개 포함) 통과.
- 이번 변경은 기존 `main.py`, 웹 프론트엔드, PostgreSQL 마이그레이션 및 `docs/evoforge-v4.2/` 정본 파일을 수정하지 않는 독립 런타임 모듈·수용 테스트 보강이다.
- 실제 외부 공급사(Meta API) 과금 호출, GCP KMS 하드웨어 키 서버 연동, 프로덕션 Cloud Run 다중 인스턴스 부하 시험은 이 단위/수용 테스트와 별도 범위다.
