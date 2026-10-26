# Claude Code 실행 프롬프트 — EvoForge v4.2 (M0 → M3)

> 사용법: 이 파일 전체를 Claude Code 첫 메시지로 붙여 넣는다. 저장소 루트에 이 패키지를 `docs/evoforge-v4.2/`로 둔다고 가정한다. 각 Phase 끝에서 Claude Code는 **멈추고** 확인을 기다린다. Phase는 통합 기획서 p.49의 마일스톤 사다리와 1:1로 대응한다.

---

## 0. 역할·우선순위·금지 사항

너는 EvoForge의 M0~M3를 구현한다. 정본은 아래 순서로 우선한다. 문서와 코드가 다르면 멈추고 보고한다.

1. `docs/evoforge-v4.2/contracts/sql/core_DRAFT.sql`, `context_plane_DRAFT.sql` 및 각 `*_tests.sql`
2. `docs/evoforge-v4.2/contracts/schemas/*.json`, `contracts/quality_gates.json`
3. `docs/evoforge-v4.2/reference_impl/*` (codec·Fidelity Gate·비용 모델·품질 판정의 동작 기준)
4. `docs/evoforge-v4.2/contracts/vocabulary.json` (모든 열거값·이벤트·도구명)
5. `docs/evoforge-v4.2/EvoForge_Blueprint_50pages_v4.2.md`, `contracts/Context_Mesh_Spec.md`
6. `docs/evoforge-v4.2/research/Technology_Radar_2026-10.md` (채택 근거만. 논문 수치를 코드·문구·테스트 기대값으로 쓰지 않는다)

**절대 금지**
- `JuliusBrussee/caveman`의 BSL-1.1 경로(`engine/`, `rewriter/`, `browse/`, `proxy/`, `mcp/`, `shrink/`, `mem/` Go 코어, `shared/platform/`, `extension/engine.wasm`)를 열람·복사·의존성 추가·사이드카 호출하는 것. lockfile에 나타나면 즉시 중단·보고.
- LiteLLM 등 제3자 LLM 게이트웨이를 기본 의존성으로 넣는 것. 공급사 **공식 SDK**만 사용.
- 고객에게 공급사 키 입력을 받는 기능(BYOK)을 만드는 것. 공급사 키는 KMS에 있고 Broker 서비스 신원만 복호화한다.
- `core.reserve_cost`를 거치지 않는 공급사 호출, 금액의 float 저장.
- 패킷에 LLM 생성 요약을 넣는 것(M3까지).
- `vocabulary.json`의 `deprecated` 식별자를 코드·스키마·이벤트·로그 키로 새로 쓰는 것.
- 부작용 도구(`provider.call`, `github.*`, `billing.*`, `deploy.*`, `fs.write`, `shell.*`, `net.*`)를 투기 실행하는 것. 보호 테스트·CI 파일을 고쳐 게이트를 통과시키는 것.
- HIGH/CRITICAL verifier에게 빌더 transcript·근거·자기평가를 넘기는 것.
- 앱 DB 역할에 DELETE·BYPASSRLS를 주는 것, 테스트 통과를 위해 계약(CHECK·트리거·스키마·`quality_gates.json` 수치)을 완화하는 것. 계약이 틀렸다고 판단되면 Phase를 멈추고 근거와 함께 제안한다.

## 1. 공통 Phase 프로토콜

1. **계획(쓰기 금지):** 만들/고칠 파일, 각 파일의 책임, 이 Phase의 수용 테스트 ID(CR-xx, C-xx, T-xx), 예상 위험을 10줄 이내로 보고한다.
2. **실행:** 계획한 파일만 수정한다. 계획 밖 수정이 필요하면 이유를 적고 멈춘다.
3. **검증:** 아래를 실행하고 출력 마지막 20줄을 붙인다.
   - `python3 -I docs/evoforge-v4.2/tools/validate_package.py --pg`
   - 이 Phase의 단위·통합 테스트
4. **Diff 보고:**
   ```
   ## Phase N 결과
   - 변경 파일: <경로> (+추가/-삭제)
   - 수용 테스트: <ID> PASS | FAIL(사유)
   - 계약 대비 차이: 없음 | <항목>
   - 남은 위험/미구현: <항목>
   - git diff --stat
   ```
5. **확인 대기:** `계속하려면 "Phase N+1 진행"이라고 입력하세요.`라고 쓰고 멈춘다.

## 2. Phase 목록

### Phase 0 — 저장소 감사 (쓰기 금지)
언어·프레임워크·마이그레이션 도구·테스트 러너·CI 파악. 기존 인증 컨텍스트를 `app.tenant_id`, `app.project_ids`, `app.policy_hash` 세션 변수로 주입할 수 있는지 확인. 기존 Autonomous AI Collective 소스와 이 명세의 충돌 목록. 로컬 PostgreSQL ≥ 14에서 `validate_package.py --pg` 기준선 기록. **파일을 만들지 않는다.**

### Phase 1 — M0-a 계약 코드와 CI
- JSON Schema 4종에서 타입·런타임 검증기를 생성한다. validator의 의미 규칙 S1–S11을 `PacketValidator`로 이식하고, valid 7 / invalid 33 예시의 판정이 validator와 100% 일치하게 한다(`harness-patch.v1` 포함).
- p.43 엔드포인트 표와 스키마에서 OpenAPI 문서와 계약 테스트 골격을 생성한다.
- CI에 `validate_package.py --pg`를 필수 체크로 추가한다.
- 수용: CR-29, 30, 31, 33, 41, 69 (예시 기반)

### Phase 2 — M0-b DB 마이그레이션
- `core_DRAFT.sql`, `context_plane_DRAFT.sql`을 저장소 마이그레이션 도구로 옮긴다. 외래키를 기존 사용자 테이블에 연결하는 것 외에는 CHECK·트리거·RLS·GRANT를 바꾸지 않는다.
- 96개 SQL 검사(context 39 + core 57)를 CI에서 실행한다.
- 수용: CR-06, 07, 08, 10, 14, 16, 17, 21, 22, 37–48, 60, 66, 67 (DB 수준: C-16~C-19)

### Phase 3 — M0-c Provider Broker(플랫폼 키)와 과금 경로
- 공식 SDK 어댑터(OpenAI·Anthropic·Google 우선), KMS envelope 키 로딩(Broker 신원 전용), 공급사×모델 전역 토큰 버킷 + 테넌트 가중 공정 큐.
- 호출 경로: allowlist → `reserve_cost` → `side_effect_intents(provider.call)` → 호출 → receipt(`provider-usage-receipt.v1`) → `settle_reservation`. 결과 불명확 시 조회 후 진행.
- Registry probe 잡(14일 만료), 테넌트 cache namespace 솔트 발급·저장(솔트 값은 패킷에 넣지 않음).
- 수용: CR-13, 26(솔트 생성 단위), 37, 38, 39, 50(IAM 시험)

### Phase 4 — M0-d 실행·게이트·기준선
- microVM Runner 연동(egress deny, 키·메타데이터 차단), 저장소 프록시, Evidence Vault(블롭별 DEK, **RAW만**), Retrieval Gateway + selector 파서.
- 게이트 G0/G1/G2/**GH_INTEGRITY**/GR/G4(+G3 성능 과제) 기록 → `core.gate_results`, 병합 경로는 `core.authorize_merge` 뒤에만. `GH_INTEGRITY`는 `reference_impl/integrity_gate.py`(오라클은 Python AST `oracle_ast.py`, 보상 해킹 `reward_hack.py`)와 같은 판정(PERF `Oracle.*`·`RewardHack.*`, V42 `OracleAccuracy.*`·`Integrity.*` 이식). 오라클 말뭉치 2종을 서비스 CI 회귀로 쓴다. 사람 라벨 holdout을 200건 이상으로 늘리는 라벨 작업(가이드 = 말뭉치 형식)을 이 Phase에 포함한다. 프로젝트 보호 경로 glob 설정.
- 리뷰 기록: 차단 판정에 `evidence_kind`·`evidence_ref` 필수, advisory 강등·상한(`reference_impl/review_policy.py` `triage_findings`).
- 봉인 평가 세트 v0(과제 계열 6종, 과제당 held-out ≥ 3개·compositional·negative 포함) + `X_SINGLE` 측정 하네스. 평가 Runner는 `reference_impl/eval_hygiene.py` 방식(재구성 + 감사 7항목)으로 샌드박스를 만들고 `score_record()` 규칙으로만 점수를 기록한다(V42 `Hygiene.*` 이식). 판정은 `reference_impl/quality_gate.py`와 같은 결과(23개 테스트 이식).
- 수용: CR-01, 06, 07, 15(REST), 30, 31, 45, 51–56, 62, 63, 64, 67, 74; Exit = 로그인 → 저장소 → 1좌석 → 격리 실행 → 검증 PR + X_SINGLE 기준선 봉인

### Phase 5 — M1 Private Alpha
- 2좌석 SINGLE(builder + 독립 critic), Review Coverage(RAW 인라인 + REF_ONLY Diff), Command fast lane(`accept_command`), Mission Control 기본 카드, 선결제 크레딧(테스트 결제), receipt 일일 대사.
- 수용: CR-08, 10, 14, 22, 42, 43; Exit = 외부 3팀 검증 PR, 안전 불변식 위반 0, 청구 = 원장 = receipt

### Phase 6 — M2 Closed Beta
- 5좌석·5토폴로지(규칙 기반 선택), Lease·fencing 경로 전체, MCP 서버(2026-07-28, 지원 클라이언트 1+), Folder Bridge(`evoforge.folder/1`), Feedback 폐쇄 루프, SSE 스냅샷+커서, 리뷰어 자격 시험(seeded defect + 정밀도) → `core.reviewer_qualifications`.
- 성능 기법(각각 독립 플래그, 기본 OFF → 절제 실험 후 ON): 응집도 분할 `partitioner.py` + `candidates.wave_id` + `composition` 큐/`GC_COMPOSITION` + 동시 변경 통지 `composition_gate.py`; 다면 재현 테스트 생성 + 실행 증거 우선 선택·adaptive k `selection.py`; HIGH/CRITICAL 명세 선행 verifier(Phase A 봉인 → Phase B) `review_policy.py`.
- `X_ADAPTIVE5` vs `X_SINGLE` 실험(동일 시간·동일 비용 분리), Tier A 판정. 기법별 절제(ablation) 결과를 따로 보고.
- 수용: CR-15, 32, 44, 58, 59, 60, 61, 65, 66, 68; Exit = 품질 Tier A 비열등 + 안전 0 + 속도 비율 하한 ≥ 1.5

### Phase 7 — M3 Context Efficiency
- 결정적 codec(JUnit/Jest·JSON(keep rule)·로그 L1–L5), Fidelity Gate, Packet Compiler(`evoforge-canonical/v1`, S11 배치), Cache Planner, arm B/D/E, 런타임 shadow 감사(2%).
- TRIAL 기법(각각 독립 플래그): 읽기 전용 투기 실행 `speculative.py`(Tool Runtime read-set 추적 필수), 보정 cascade `cascade.py`, epoch 경계 가역 접기(경계 단위 평가), 단계 기억 회상 `memory_policy.py`, 사람 라벨 PPI `ppi.py`. 압축·접기의 기본값 판정은 `compaction_eval.py` 4조건(V42 `CompactionEval.*`).
- `reference_impl` 픽스처·mutation 테스트를 그대로 이식하고 같은 판정을 낸다. 로그 불변식은 새로 구현하고 mutation 테스트를 추가한다.
- 수용: CR-03, 04, 05, 09, 12, 25, 27, 28, 29, 36, 57, 70, 71, 72, 73, 75; Exit = 채택 codec·기법이 Tier A + 비용 비율 상한 < 1.0, 투기 불일치 0

## 3. 완료 정의
- `validate_package.py --pg` 통과, Phase별 수용 테스트 PASS, 계약 대비 차이 0건(또는 승인된 변경 기록).
- 코드 기준 deprecated 식별자 grep 0건, SBOM에 Caveman BSL 경로·LiteLLM 0건.
- 참조 테스트 112개(REF 22 + QG 23 + PERF 39 + V42 28)가 서비스 구현에 이식되어 같은 판정을 낸다. M6 최적화기(`harness_optimizer.py`, `harness-patch.v1`)는 이 프롬프트 범위 밖이지만 스키마 검증은 Phase 1에서 함께 이식한다.
- 미구현 항목은 테스트 매트릭스에서 **미구현**으로 남기고 구현했다고 보고하지 않는다. M4 이후(A2A, 실결제, 침투 시험, GA)는 이 프롬프트의 범위가 아니다.
