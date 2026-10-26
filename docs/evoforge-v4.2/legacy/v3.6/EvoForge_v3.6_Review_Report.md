# EvoForge v3.5 → v3.6 검토 보고서

검토 대상: `EvoForge_Production_Blueprint_50pages_v3.5_Caveman_Context_Optimization.md`, `EvoForge_v3.5_Improvement_Review.md`, `EvoForge_v3.5_50_Page_Implementation_Package.zip`(61개 파일) · 검토일 2026-10-25

## 결론

1. **구현에 들어가면 안 되는 상태였다.** 라이선스 전제가 틀렸고(Caveman 엔진은 Apache-2.0이 아니라 BSL-1.1이며, 멀티테넌트 SaaS 사용은 상용 라이선스 범위), SQL 초안은 실제로 실행해 보니 테스트 매트릭스가 요구하는 감사·삭제·멱등성을 구조적으로 만족할 수 없었다.
2. **비용 논리의 기준선이 틀렸다.** 캐시 없는 원가와 비교하면 압축 효과가 크게 부풀려진다(계산 예시: 0.14x로 보이지만 같은 캐시 조건의 RAW와 비교하면 0.44x). 복원 1회가 추가 모델 턴 1회라는 점이 빠져 있었고, 예시 조건에서는 전체 원문 복원 6회부터 압축이 RAW보다 비싸진다.
3. **핵심 안전 요구 두 가지가 판정할 수 없는 문장이었다.** "Critic은 원문을 확인한다"와 "품질 검사 통과". v3.6은 이것을 DB 함수(커버리지 게이트)와 형식별 결정적 불변식으로 바꿨고, 둘 다 실행해서 검증했다.
4. **문서 간 어휘가 맞지 않았다.** 압축 전략 이름이 9가지, 같은 필드 이름이 3가지, 이벤트·도구·엔티티 이름이 페이지마다 달랐다. v3.6은 단일 어휘 파일과 lint로 강제한다.
5. v3.5 리뷰는 "정합성 테스트 수행"이라고 적었지만 SQL은 실행되지 않았고, 예시 JSON은 SQL 타입(uuid)과 맞지 않았으며, 참조 README는 존재하지 않는 파일 7개를 가리키고 있었다.

## 실행해서 확인한 것

| 검사 | 결과 |
|---|---|
| v3.5 SQL을 PostgreSQL 16.15에 적용 후 결함 재현 | 거부 열람 감사 INSERT 3가지 경우 모두 실패(FK/RLS), DELETE 실패(FK), 같은 요청 패킷 중복 생성 허용, `role='banana'`·`strategy='WHATEVER'` 허용 |
| v3.5 스키마 허점 | 원문 ref 없는 RECOVERABLE 패킷, 원문 불필요 표시된 Critic 패킷, receipt 없는 `measured=true` 모두 **유효** 판정 |
| v3.5 예시 vs SQL | `tenant-demo`, `project-01`, `task-01`, `ctxpkt-…` 모두 SQL `uuid` 컬럼에 들어갈 수 없음 |
| Caveman upstream(2026-10-25) | LICENSING.md(BSL-1.1 범위·상용 경계), engine.md(기본 압축기 15종), context-recovery.md(CCR: 로컬 SQLite·콘텐츠 해시 handle·저장 시 암호화 없음·멀티테넌트 비지원) |
| 공급사 캐시 문서(2026-10-25) | OpenAI·Anthropic·Gemini 현행 규약 → Registry 시드 반영 |
| v3.6 validator | 스키마 4종, 예시 31개(valid 6 / invalid 25, 실패 사유까지 일치), 어휘 lint 5개 파일, 50페이지 바이트 동일성, README 참조, 참조 구현 22개, SQL 39개 — **전부 통과** |

## 결함 목록 (심각도순)

### P0 — 구현·출시 차단

| ID | 결함 | 근거 | v3.6 조치 |
|---|---|---|---|
| F-01 | **라이선스 전제 오류.** 리뷰·ADR-036·명세 §10은 "3.0.0+ Apache-2.0"이라고 적었다. | main `LICENSING.md`: engine/proxy/mcp/shrink/mem(Go)/shared/platform/engine.wasm은 BSL-1.1이다. 제3자 대상 호스팅·임베디드 서비스와 멀티테넌트 컨트롤 플레인은 상용 범위다. "Caveman"은 상표다. | ADR-036R: 엔진 코드 미사용, 공개 문서만 참고한 클린룸 구현, MIT 경로만 허용, 제품 표면에서 명칭 제거. p.05/32/41, 명세 §14, CR-35 |
| F-02 | **거부된 열람을 감사할 수 없다.** CR-06/07은 "403 + 감사"를 요구한다. | `evidence_reads_v35`가 패킷 ref에 FK를 걸고 RLS가 행위자 테넌트를 검사한다 → 외부 테넌트·미존재 ref에 대한 거부 기록 INSERT가 실패한다(재현). | FK 없는 append-only `evidence_access_log` + 플랫폼 `ctx_sec.security_events`. SQL T10·T11 |
| F-03 | **삭제(CR-17)가 불가능하다.** | blob → refs → reads FK 사슬 때문에 DELETE가 실패한다(재현). 백업 처리 방법도 없다. | Tombstone + 블롭별 DEK 파기(crypto-shred), ref 폐기, 의존 패킷 REVOKED, legal hold 차단. SQL T15·T18 |
| F-04 | **비용 기준선 오류 + 복원 비용 누락.** p.22 `Net Benefit = uncached_baseline_cost − …` | OpenAI·Gemini는 캐시가 기본 동작이라 "캐시 없는 RAW"는 실제 대안이 아니다. 복원 비용을 API GET으로만 계산했지만 실제로는 컨텍스트 전체를 다시 읽는 추가 모델 턴이다. | 기준선 = 같은 캐시 조건의 `A_RAW` 실측. `call_purpose=retrieval_turn`으로 귀속. 손익분기 감시. 명세 §10, `cost_model.py` |
| F-05 | **"Critic은 원문 확인"을 판정할 수 없다.** 대형 Diff가 컨텍스트 한도를 넘는 경우도 다루지 않았다. | 열람 로그는 있었지만 커버리지 개념이 없었다. | Review Coverage Ledger(`range_agg`) + `ctx.assert_review_gate`(비작성자·head SHA·STALE·100% 커버리지). chunk 리뷰·분할 기준. seeded-defect canary로 "전달 ≠ 주의"의 한계를 보완. SQL T12 |
| F-06 | **Fidelity Gate가 정의되지 않았다**("(iii) 품질 검사"). | CR-03/09를 판정할 기준이 없다. JSON 배열 절단은 일반적인 구조 검사를 모두 통과하면서 `FAILED` 레코드 3건을 조용히 버린다(픽스처로 재현). | 결정적 불변식 U1–U4, T1–T5, L1–L5, J1–J5. keep rule(닫힌 술어). 참조 구현 + mutation 테스트 22개 |

### P1 — 계약 결함

| ID | 결함 | v3.6 조치 |
|---|---|---|
| F-07 | 압축 전략 어휘 9종 혼재(FULL, PRESERVE, SELECTIVE, STRUCTURAL_ONLY, RECOVERABLE_COMPACT, COMPACT, CACHE_ONLY, CACHE_AWARE_COMPACT, RAW_FALLBACK…). 압축 방식과 캐시 방식이 한 enum에 섞였고 패킷 단위였다. | `fidelity`(항목별) × `cache_mode`(호출별) 분리, 실험 arm은 조합으로 정의, `vocabulary.v3.6.json` + lint(C4) |
| F-08 | 스키마 `role` 5종 고정 → v3.4 HIGH_RISK(Critic 2 + Verifier), DAG_PARALLEL(Builder 3)을 표현할 수 없다. 명세는 "Planner", 스키마는 "navigator". | `seat_id` + `function_role` + `candidate_id`. 리뷰어는 비작성자이고 chat 채널일 수 없음(스키마·SQL 동시 강제) |
| F-09 | 스키마·SQL·예시·p.42 불일치: ID 타입(slug vs uuid), `required_original`/`requires_original`/`original_required`, 엔티티 이름(`context_access_events` vs `evidence_reads_v35`), SQL에 `ref` 컬럼 없음, 예시 ref `evref-000000000001`은 "예측 불가 ID" 원칙과 모순. | 하나의 이름 체계. `evidence_refs`를 무작위 grant 테이블로 신설(만료·폐기). 형식 CHECK |
| F-10 | 멱등성 제약 없음(CR-21), 상태·역할 CHECK 없음. | `idempotency_key`·`request_id`·`provider_request_id` UNIQUE, 모든 열거값 CHECK, 상태머신 트리거 |
| F-11 | RLS가 테넌트 단위뿐이다. 같은 테넌트 다른 프로젝트 차단(CR-07)을 앱 코드에만 맡겼다. | 테넌트 **및** 프로젝트 RLS. SQL T02 |
| F-12 | 플랫폼 관리 키를 쓸 때 테넌트 간 공급사 캐시 Prefix가 공유될 수 있다(타이밍 사이드채널·과금 귀속). | 테넌트별 cache namespace 솔트를 L0 맨 앞에 렌더링(ADR-044N) |
| F-13 | 보안 세부: ref 존재 오라클(403/404 구분), selector 문법 모순(p.32 "JSON 경로" vs p.43 "JSON Pointer"), 경로 탈출, XML entity expansion. | 외부·미존재 ref는 같은 `not_found`, 닫힌 selector 문법(정규식으로 `..`·선행 `/`·역슬래시 차단), DOCTYPE/ENTITY 거부 |
| F-14 | 실험 설계가 실행 불가능하다: OpenAI 이전 모델·Gemini는 캐시를 끌 수 없어 "RAW 무캐시" 대조군이 없다. "quality ≥ baseline"은 통계적으로 판정할 수 없다. | arm별 실행 조건(Registry `can_disable`), 사전 등록 비열등성 margin(제안 −2%p) |
| F-15 | 압축과 캐시의 상호작용을 다루는 규칙이 없다: canonical 직렬화가 없고, 패킷 본문의 `created_at`이 렌더링될 수 있으며, 이력 재작성이 Prefix를 깨뜨린다는 점이 빠졌다. | `evoforge-canonical/v1`, 휘발성 메타데이터 비렌더링, compress-on-insert + 결정적 codec(ADR-043N), 세그먼트 해시 |
| F-16 | 스키마가 핵심 불변식을 강제하지 못한다(손실인데 ref 없음, 리뷰어인데 원문 불필요, 측정됐다는데 receipt 없음). 사용량을 사전 객체인 패킷에 넣었다. | 조건부 스키마(`if/then`) + 의미 규칙 S1–S10. usage는 별도 receipt 스키마(정수 `cost_micros`) |

### P2 — 정확성·정리

| ID | 결함 | 조치 |
|---|---|---|
| F-17 | 통합 MD front matter가 v3.4·2026-10-23 그대로였다. 제목에 타사 상표가 들어 있었다. | v3.6 front matter, 제목 변경 |
| F-18 | p.50 "독립 18개 검증 시나리오" 아래 실제 항목은 10개, 테스트 매트릭스는 24개였다. | 제목 정정, CR ID 연결, v3.6 Go/No-Go 추가 |
| F-19 | p.39 "16종 변환기" — upstream 문서는 기본 레지스트리 15종이다. | 정정 |
| F-20 | 이벤트 이름이 p.27/p.44/명세에서 달랐다. 복원 도구 이름도 p.21(`retrieve_artifact`, `open_source_evidence`)과 p.23(`retrieve_evidence`)이 달랐다. | 단일 이벤트 카탈로그, 도구 4종으로 통일 |
| F-21 | `reference/README.md`가 패키지에 없는 파일 7개와 `pages/EvoForge_v3.4_NN.md`를 가리킨다. | 주석으로 표시(원본 보존), validator C6 |
| F-22 | 50페이지마다 v3.1~v3.5 절이 쌓여 있어, 구현자가 페이지마다 5개 버전을 머릿속으로 합쳐야 한다. | **이번에는 하지 않음.** 우선순위 규칙(vocabulary 우선)만 명시. 통합본 작성은 결정 필요 사항 5번 |
| F-23 | OpenAI "explicit prefix breakpoint"는 GPT-5.6 이상에만 해당한다. | p.22·Registry에 모델 범위 명시 |

## v3.5 리뷰 문서 자체에 대한 평가

| v3.5 리뷰의 주장 | 실제 |
|---|---|
| "LICENSING.md의 3.0.0+ Apache-2.0 확인" | 현재 main 기준 사실과 다르다(F-01). |
| "50페이지 번호·스키마 형식·예시 유효성·ZIP 무결성 검증 수행" | 페이지 번호와 예시–스키마 검사는 통과한다. 하지만 예시–SQL 타입 불일치, 문서 간 어휘 불일치, README가 가리키는 누락 파일 7개는 잡지 못했다. |
| "DB 마이그레이션 … 미실시" | 맞다. 실행했으면 F-02·F-03·F-10을 바로 발견했을 것이다. |
| "10X는 제품 목표이며 보장하지 않음" | 맞다. v3.6도 유지한다. |

## 결정이 필요한 사항

1. **Caveman 엔진 상용 라이선스를 검토할지.** 현재 결정은 미사용·클린룸이다. 클린룸으로 해도 P0 범위(JSON·로그·테스트 보고서 3종)에는 지장이 없다.
2. **비열등성 margin(−2%p)과 codec 자동 비활성화 임계(최근 200건 중 2%)**를 확정할지. 둘 다 제안값이다.
3. **`max_reviewable_diff_bytes`(제안 400KB)** — 이 값을 넘으면 PR을 분할하거나 인간 리뷰어를 요구한다.
4. **기본 키 운영 방식(BYOK vs 플랫폼 키).** 캐시 격리 방식과 원가 원장 구조가 달라진다.
5. **v3.1~v3.6 레이어를 페이지별 단일 유효 명세로 통합할지(F-22).** 구현팀 온보딩 비용을 크게 줄이지만, 50페이지 전체를 다시 쓰는 작업이다.

## 이번 패키지에서 하지 않은 것

- 프로덕션 코드, 실제 공급사 API 호출과 캐시 실측, Vault·Gateway·Compiler 런타임, A/B 하네스, 부하·침투 시험.
- 로그 codec(L1–L5)의 참조 구현. 명세에만 있다.
- 법률 검토. 라이선스 해석은 공개 문서를 읽은 결과이며 법무 확인이 필요하다.

## 부록 A. 블루프린트 정정·추가 목록 (자동 생성, 52건)

정정은 v3.5 절 본문을 직접 고친 것, 추가는 해당 페이지 끝에 `### v3.6 ·` 절을 붙인 것이다. 페이지 0은 front matter·머리말이다.

| 페이지 | 구분 | 사유 | 변경 후(앞부분) |
|---:|---|---|---|
| 00 | 정정 | front matter가 v3.4로 남아 있었음 | title: "EvoForge v3.6 — 50페이지 상용 서비스 구현 기획서" |
| 00 | 정정 | front matter 버전 불일치 | version: "3.6-recoverable-context-contracts-corrected" |
| 00 | 정정 | 날짜 | date: "2026-10-25" |
| 00 | 정정 | 상태 문구 | status: "v3.6 · v3.5 Context Mesh의 계약 정합성·라이선스·비용 기준선 정정 / 구현 전 / 성능 미검증" |
| 00 | 정정 | 제목에서 타사 상표 제거, 버전 | # EvoForge v3.6 — Recoverable Context Mesh (정정판) & 5-Agent Efficiency (50페이지) |
| 00 | 정정 | v3.6 개정 요약과 우선순위 | > **v3.6 개정(2026-10-25) · 최우선:** v3.5 Context Mesh를 실행 가능한 계약으로 다시 맞췄다. (1) 압축 방식(`fidelity`: RAW/STRUCTURAL/R… |
| 05 | 정정 | 라이선스 전제 오류(Apache-2.0 아님) | Caveman 엔진 계열 코드(engine/proxy/mcp/shrink 등, BSL-1.1)는 사용하지 않는다. 제3자 대상 호스팅·멀티테넌트 사용은 상용 라이선스 범위다(ADR-036R). 공개… |
| 06 | 정정 | RAW 폴백과 승인급 증거 구분 | 2. 원문 저장 실패, 권한 불명확, 콘텐츠 식별 실패, 토큰 감소 없음, 검증 핵심 정보 손실 위험이면 원문 전달(`fidelity=RAW` + `raw_reason`). 단, Critic/Ver… |
| 06 | 추가 | 결정성·삽입 시 압축·계약 고정·ref 규칙 | ### v3.6 · 불변식 추가 (DB·스키마가 강제) |
| 10 | 추가 | 기준선 오류 정정 | ### v3.6 · 효율 KPI의 기준선과 복원 턴 |
| 12 | 추가 | 관측 항목 보강 | ### v3.6 · Context 카드의 판정 항목 |
| 16 | 정정 | 전략 어휘 통일 | 같은 Candidate에 `A_RAW`, `B_STRUCTURAL`, `C_RECOVERABLE`, `E_CACHE_AWARE` 실험 arm(fidelity × cache_mode 조합)을 별도 R… |
| 19 | 정정 | 프로필 정의를 판정 가능한 매트릭스로 연결 | SAFE는 확인된 형식만 압축, 실패 근거/보안·정책·계약 전체 보존. 프로필별 허용 fidelity는 기술 명세 §4.2 매트릭스가 정본이다(예: SAFE에서 테스트 보고서는 STRUCTURAL까… |
| 21 | 정정 | 도구 이름 통일 | MCP/Folder/AI Chat 참여자는 `retrieve_evidence`(MCP·REST·Folder 공통 계약 `evidence-retrieval.v1`)의 실제 호출 권한을 Probe한다. |
| 22 | 정정 | 공급사별 사실 정정·구체화 | - OpenAI는 GPT-5.6 이상에서만 explicit 모드(`prompt_cache_breakpoint`)와 `cache_write_tokens`를 제공하고 이전 모델은 자동 캐시·`cache… |
| 22 | 정정 | Net Benefit 기준선 오류와 복원 비용 누락 정정 | - 문맥 압축이 Prefix 일치를 무너뜨릴 수 있다. `net_benefit(s) = cost(A_RAW 실측, 같은 캐시 조건) − cost(s 실측)`을 품질 비열등성을 통과한 후보에 대해서만… |
| 22 | 추가 | 캐시 격리 누락 | ### v3.6 · 테넌트 캐시 네임스페이스 |
| 23 | 정정 | 인자 형식을 스키마와 일치 | `retrieve_evidence(request)` |
| 23 | 정정 | selector 문법·존재 오라클 | `retrieve_evidence`는 테넌트/프로젝트/주체별 ACL, 버전, 분량·요청 상한을 검사한다. selector는 닫힌 문법(`all`, `bytes:`, `lines:`, `json:`(… |
| 24 | 정정 | Folder 요청 형식 고정 | 참여 AI가 `GET_EVIDENCE` 요청 파일(본문 = `evidence-retrieval.v1` 요청 스키마)을 원자적으로 기록하면, |
| 27 | 정정 | 이벤트 이름이 p.27/p.44/명세에서 서로 달랐음 | `EVIDENCE_INGESTED`, `EVIDENCE_STORED`, `EVIDENCE_STORE_FAILED`, `CONTEXT_DECISION_MADE`, `CONTEXT_FIDELITY_FA… |
| 28 | 정정 | v3.4 토폴로지와 역할 enum 충돌 | 표의 '역할'은 기본 **좌석 라벨**이다. 패킷은 `seat_id`(1–5)와 `function_role`(planner/builder/critic/verifier/integrator/observ… |
| 29 | 정정 | 이벤트명·DB 함수 연결 | `CONTEXT_PACKET_STALE` 이벤트와 재검토를 유발한다(`ctx.mark_task_packets_stale`, STALE은 되살릴 수 없음). |
| 31 | 정정 | 상태 이름을 DB 상태머신과 일치 | 흐름은 `수집 → 원문 저장(blob PENDING) → read-back 검증(ACTIVE) → codec → Fidelity Gate → 패킷 ISSUED → (복원) → 평가`이고, 상태의 정… |
| 32 | 정정 | 패킷 단위 전략 → 항목 단위 fidelity | 2. 항목마다 `RAW`(정책상 원문: 보안 정책·사용자 목표·Diff 원본 등, `raw_reason=POLICY_REQUIRED`), `STRUCTURAL`(원문 값을 그대로 둔 필드/범위 선택… |
| 32 | 정정 | 'JSON 경로'(p.32)와 'JSON Pointer'(p.43) 불일치 | selector는 닫힌 문법(JSON Pointer RFC 6901, 바이트/행 범위, `junit:`, `hunk:`, `file:`)으로 제한하며 JSONPath 등 식 선택기는 금지한다. |
| 32 | 정정 | 품질 검사 미정의 | (iii) 형식별 결정적 Fidelity Gate(U/T/L/J 불변식, 기술 명세 §6) |
| 32 | 정정 | 라이선스 | 제품에서는 Stateless Compiler Worker + Postgres 메타데이터 + 암호화 Object Storage(블롭별 DEK) + tenant ACL로 클린룸 재구현한다. Cavema… |
| 35 | 추가 | 검증 불가능한 요구를 판정 가능한 게이트로 | ### v3.6 · '원문 확인'의 판정 기준 |
| 36 | 정정 | 불변식 ID 연결 | 테스트 로그 압축에는 테스트 건수·실패 목록·Assertion·파일/라인/스택 위치·요약 오류를 반드시 보존하고(불변식 T1–T5, 참조 구현 `reference_impl/fidelity_gate.… |
| 36 | 추가 | 구조 압축의 의미 손실 | ### v3.6 · JSON 절단의 숨은 손실 |
| 37 | 정정 | 실행 불가능한 대조군 정의 | 비교군 `A_RAW`(주 기준선: 공급사 기본 캐시), `B_STRUCTURAL`, `C_RECOVERABLE`, `D_RAW_EXPLICIT_CACHE`, `E_CACHE_AWARE`, 그리고 캐… |
| 37 | 정정 | 'quality ≥ baseline'은 통계적으로 판정 불가 | 품질(정확성·회귀 검출·정보 누락)을 합격 게이트로 놓고(사전 등록한 비열등성: 검증 수정률·seeded-defect 검출률 차이의 단측 95% 신뢰하한 > −2%p, 핵심 결함 누락 0건 — ma… |
| 39 | 정정 | 개수 사실 오류(16→15), 어휘 | **기본 정책:** 항목마다 `RAW`(규정·보안·검증 원문) / `STRUCTURAL`(원문 값 그대로의 필드 선택·범위 추출) / `RECOVERABLE`(원문 먼저 저장한 결정적 변환) / `… |
| 39 | 정정 | 필드명 | `ContextDecision`에 항목별 `fidelity`·`raw_reason`, 호출별 `cache_mode`, |
| 41 | 정정 | 기본 OFF → 경로 자체 제거 | 외부 Caveman Cloud로 가는 경로는 제품에 존재하지 않는다(설정으로 켤 수 없음). upstream 문서상 Cloud 경유 요청은 system prompt·도구 결과·코드가 통째로 전달된다… |
| 42 | 정정 | v3.5 엔티티 이름·필드가 SQL과 달랐음 | 신규 데이터(정본: `contracts/sql/context_plane_v3_6_DRAFT.sql`): `ctx.evidence_blobs`(sha256, size, source_kind, trus… |
| 42 | 정정 | 프로젝트 격리·삭제 방식 | **제약:** 테넌트 **및 프로젝트** 단위 RLS + `(tenant_id, project_id)` 복합 FK, 게이트웨이 역할 DELETE 금지(삭제 = `ctx.shred_blob` tomb… |
| 43 | 정정 | 엔드포인트가 blob id를 노출 | `POST /v1/evidence-refs/{ref}/retrieve`, `GET /v1/context-packets/{packet_id}/review-coverage` |
| 43 | 정정 | 스키마 연결 | 복원 요청(`evidence-retrieval.v1`)은 `request_id`(멱등), `selector`(닫힌 문법), |
| 44 | 정정 | UI 이벤트 이름을 도메인 이벤트와 통일 | 도메인 이벤트(p.27)의 투영으로 `CONTEXT_DECISION_MADE`, `CONTEXT_PACKET_ISSUED`, `EVIDENCE_RETRIEVAL_REQUESTED`, `EVIDENC… |
| 45 | 정정 | 위협 누락 | 추론 캐시 데이터 보존 불일치, **플랫폼 키에서 테넌트 간 공급사 캐시 Prefix 공유(타이밍 사이드채널)**, **ref 존재 오라클**, **XML entity expansion**, **s… |
| 45 | 정정 | 완화책 | 완화: 테넌트 cache namespace 솔트, 외부/미존재 ref 동일 `not_found`, DOCTYPE/ENTITY 거부, 닫힌 selector 문법, 랜덤 opaque ID, |
| 46 | 정정 | v3.5 SQL에서 삭제가 FK로 막혀 있었음 | 삭제 시 요약본·검색 인덱스·임베딩·백업 만료·소송보존 예외까지 처리한다. 원문은 블롭별 DEK로 암호화하고 삭제 시 DEK를 파기해 백업 사본까지 복호화 불가로 만든다(crypto-shred). … |
| 47 | 정정 | 어휘·임계값 | 실패가 발견되면 `ctx.codec_profile_state`에서 해당 `(source_kind, codec@version, provider)`만 DISABLED로 바꾸고 RAW(`raw_reaso… |
| 48 | 정정 | 복원 턴 귀속·부동소수 금액 제거 | 원가에 `provider uncached input`, `provider cache write/read`, `output`, `call_purpose`(task_turn/retrieval_turn/… |
| 49 | 정정 | 구현 순서를 실행 가능한 산출물 기준으로 재배열 | P0-1 `스키마 + validator CI` → P0-2 `SQL 마이그레이션 + RLS(39개 검사)` → P0-3 `Vault(블롭별 DEK) + Retrieval Gateway + selec… |
| 50 | 정정 | 제목은 18개, 실제 목록은 10개 | ### v3.5 · 추가 출시 Go/No-Go (10개 항목, v3.6에서 CR ID 연결) |
| 50 | 정정 | 어휘 | - [ ] 미지원 형식·원문 누락·권한 부족·유효기간 만료·최적화 무효 시 RAW(`raw_reason` 기록) 또는 BLOCK이 발생한다. (CR-02, 04, 05) |
| 50 | 정정 | 어휘 | - [ ] 5-Agent 평가에 `A_RAW/B_STRUCTURAL/C_RECOVERABLE/D_RAW_EXPLICIT_CACHE/E_CACHE_AWARE` arm과 동일한 사전 등록 비열등성 게이… |
| 50 | 정정 | 확인 날짜 | **핵심 근거(2026-10-25 재확인):** [Caveman repository] |
| 50 | 추가 | Go/No-Go를 실행 근거와 연결 | ### v3.6 · 추가 Go/No-Go (실행 근거 연결) |

## 부록 B. 재현·검증 명령

```bash
# v3.6 전체 검증 (PostgreSQL 슈퍼유저 접속 필요)
PGHOST=... PGUSER=postgres python3 -I tools/validate_package.py --pg
# 참조 구현만
python3 -I reference_impl/test_reference.py -v
# 비용 예시 표 재계산
python3 -I reference_impl/cost_model.py
# 예시 재생성
python3 -I tools/make_examples.py
```
