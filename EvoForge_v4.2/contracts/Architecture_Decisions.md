# EvoForge v4.2 — 기술 결정 기록 (ADR-035 ~ ADR-065)

v3.5의 ADR-035~040을 v3.6에서 다시 검토했고(**R** = 개정, **N** = 신규), v4.0에서 사용자 결정 5건과 통합 결정을 ADR-047~053으로, v4.1에서 최신 연구 반영 결정을 ADR-054~061로, v4.2에서 미구현·미측정 항목을 닫는 결정을 ADR-062~065로 추가했다. 통합 기획서 p.50의 결정 레지스터(D-001~D-057)가 이 문서를 가리킨다. v4.1 근거는 `research/Technology_Radar_2026-10.md`. 원본: `legacy/v3.5_contracts/EvoForge_v3.5_Architecture_Decisions.md`, `legacy/v3.6/Architecture_Decisions_v3.6.md`.

## ADR-035 (유지) Context Mesh 도입
API 중립 Context Packet, 서버 측 암호화 원문 보존, 역할별 선별 전달, 공급사별 캐시. 모델 간 KV 공유와 Chat 세션 무인 지속 실행 가정은 거절한다.

## ADR-036R Caveman 엔진 코드를 쓰지 않고 클린룸으로 재구현
- **v3.5 전제:** "3.0.0 이상 Apache-2.0" → **틀렸다.** 2026-10-25 기준 main `LICENSING.md`는 엔진·proxy·mcp·shrink·mem Go 코어 등이 BSL-1.1이며, 제3자 대상 호스팅/임베디드/멀티테넌트 사용에는 상용 라이선스가 필요하다고 명시한다.
- **결정:** 엔진 계열 코드는 임베드·링크·사이드카 호출하지 않는다. 공개 기술 문서(engine.md, context-recovery.md)만 참고해 클린룸으로 구현한다. MIT 경로는 커밋 고정·NOTICE·SBOM을 거쳐 쓸 수 있다. 제품 표면에 "Caveman" 상표를 쓰지 않는다.
- **결과:** v3.5의 "P1 직접 도입 기술검증"은 취소한다. 상용 라이선스를 검토하는 것은 사업 결정이다. 법무 검토가 필요하다.

## ADR-037R Ref = 무작위 grant, 권한·콘텐츠 주소와 분리
Ref는 패킷×blob 단위 128-bit 무작위 ID이고 만료·폐기된다. blob_id는 외부에 노출하지 않는다. 콘텐츠 해시 기반 handle(upstream CCR 방식)은 같은 바이트면 같은 ID가 되므로 멀티테넌트에서 존재 오라클이 된다. 외부 테넌트의 ref와 존재하지 않는 ref는 같은 `not_found`로 응답한다.

## ADR-038R 비용 최적화의 기준선은 같은 캐시 조건의 RAW 실측
- 압축 후보는 `A_RAW`(공급사 기본 캐시) 실측 대비 순편익으로만 평가한다. 캐시 없는 원가와 비교하지 않는다.
- 복원 1회 = 추가 모델 턴 1회로 계산하고 `call_purpose=retrieval_turn` receipt로 귀속한다.
- "캐시 먼저, 압축은 그다음": 레이아웃(안정 Prefix)과 캐시 계획이 압축보다 우선한다.

## ADR-039R 품질 보호: 결정적 게이트 + 커버리지 원장
"Critic은 원문을 확인해야 한다"를 판정 가능한 조건으로 바꾼다. 요구 원문의 모든 바이트가 그 리뷰어에게 전달됐는지를 접근 로그로 계산하고, 미달이면 DB 함수가 승인을 거부한다. 압축 품질은 LLM 판정이 아니라 형식별 결정적 불변식으로 판정한다. 새 압축기는 자동으로 승격하지 않는다.

## ADR-040 (유지·보강) 5-Agent × 10X의 공정 실험
단일 모델, 단순 5병렬, v3.4 적응형 5, v3.6 컨텍스트 최적화 5를 같은 작업·예산·품질 조건으로 비교한다. 품질은 사전 등록한 비열등성 margin으로 판정한다. 10배는 목표이고 측정 전에는 주장하지 않는다.

## ADR-041N Fidelity와 Cache를 별개 축으로 분리
v3.5는 `strategy` 하나에 압축 방식과 캐시 방식을 섞었고, 문서마다 이름이 9가지였다. v3.6은 항목별 `fidelity`(RAW/STRUCTURAL/RECOVERABLE/REF_ONLY)와 호출별 `cache_mode`(NONE/PROVIDER_IMPLICIT/PROVIDER_EXPLICIT)로 나눈다. 실험 arm은 두 축의 조합으로 정의한다. 어휘는 `vocabulary.v3.6.json` 하나에서 관리하고 lint로 강제한다.

## ADR-042N 좌석과 기능 역할 분리
`seat_id`(1–5, 기본 라벨 Navigator/Builder Alpha/Builder Beta/Critic/Integrator)와 `function_role`(planner/builder/critic/verifier/integrator/observer)을 분리한다. v3.4 토폴로지(HIGH_RISK의 Critic 2 + Verifier, DAG_PARALLEL의 Builder 3)를 그대로 표현한다. critic/verifier는 비작성자이고 chat 채널일 수 없다.

## ADR-043N 결정적 codec + Compress-on-insert
P0 codec은 모두 결정적 코드다(LLM 요약 금지). 출력이 바뀌면 버전을 올린다. 도구 결과는 이력에 들어갈 때 한 번만 변환하며, 이미 보낸 이력을 다시 쓰는 것은 명시적 에폭 경계에서만 허용한다. 이 규칙이 있어야 압축과 공급사 캐시가 함께 동작한다.

## ADR-044N 플랫폼 키 사용 시 테넌트별 캐시 네임스페이스
플랫폼 관리 키로 여러 테넌트를 처리할 때 테넌트별 무작위 솔트를 L0 맨 앞에 렌더링해 테넌트 간 Prefix 공유를 원천 차단한다. 비용은 호출당 수십 토큰이다. OpenAI `prompt_cache_key`는 회계 보조 수단으로만 쓴다.

## ADR-045N 감사 로그는 FK 없는 append-only, 삭제는 crypto-shred
거부된 열람은 대상이 존재하지 않거나 다른 테넌트 것일 수 있으므로 FK를 걸 수 없다. 행위자 테넌트에 기록하고, 외부 테넌트·미존재 ref 탐색은 플랫폼 `security_events`에 따로 기록한다. 삭제는 tombstone + 블롭별 DEK 파기로 하며(백업 포함), 그 blob에 의존한 패킷은 REVOKED로 바꾼다. 소송 보존(legal hold)은 shred를 막는다.

## ADR-046N 실행 가능한 계약이 문서보다 우선
스키마·SQL·참조 구현·validator가 계약의 정본이다. 문서와 실행 산출물이 어긋나면 결함이다. `tools/validate_package.py`를 CI 필수 체크로 둔다. v3.5 리뷰가 "정합성 테스트 수행"이라고 적었지만 SQL은 실행되지 않았고, 문서 간 어휘 불일치와 예시–SQL 타입 불일치가 남아 있었다. 이런 일이 다시 생기지 않게 하려는 결정이다.

## ADR-047 (v4.0, 사용자 결정) 플랫폼 관리 공급사 키
- **결정:** 고객은 공급사 키를 넣지 않는다. EvoForge가 공급사 계정·키를 보유하고, KMS envelope 암호화로 보관하며, 복호화는 Provider Broker 서비스 신원만 할 수 있다. 공급사가 지원하면 테넌트(그룹)별 하위 키를 쓴다. BYOK는 v4.0 범위 밖이며 Enterprise 단계(M6)에서 재검토한다.
- **결과:** (1) 모델 비용을 EvoForge가 먼저 부담하므로 선결제 크레딧·호출 전 예약·하드캡을 DB에서 강제한다(`core.reserve_cost`, `core.settle_reservation`, `core.usage_ledger`). (2) 테넌트 간 공급사 캐시 공유 위험 때문에 namespace 솔트가 필수다(ADR-044N). (3) 공급사 조직 한도를 공유하므로 테넌트별 가중 공정 큐가 필요하다. (4) EvoForge가 데이터 국외 이전·처리 위탁의 주체가 되므로 공급사 DPA·약관(재제공 조건) 확인과 개인정보 법률 검토가 M0/M1 선행 조건이다. (5) receipt 스키마는 `billing_owner = platform`, `customer_price_micros`, `reservation_key`를 필수로 한다.

## ADR-048 (v4.0, 사용자 결정) Quality Gate Framework v1
- **결정:** 판정은 신뢰구간의 불리한 쪽 경계로 한다(비열등성=하한, 비용=상한, 공개 주장=하한). 안전 지표는 0 허용, 효과 지표는 비열등성 margin, 효율은 유의한 개선일 때만 채택한다. 표본 단위는 (task, seed) 쌍, 군집은 task(cluster bootstrap). 검정력은 관측 불일치율로 다시 계산하고 부족하면 UNDERPOWERED. Tier A(δ 5%p, 과제 ≥ 80)는 Canary 진입, Tier B(δ 2%p, 과제 ≥ 500)는 기본값·GA·공개 주장. 리뷰어 자격(critical seeded ≥ 100, Wilson 하한 ≥ 0.90, 오차단 ≤ 10%), codec 런타임 감시(감사 2%, miss 목표 0.5%), 10X 사다리(M2 ≥ 1.5, GA ≥ 3.0, 장기 10)를 같은 파일에 둔다.
- **근거:** δ 2%p는 불일치율 0.10에서 1,546쌍이 필요해 모든 결정에 쓰기에는 비싸다. 그래서 저비용 Tier A로 걸러내고 Tier B는 Canary·shadow 재생으로 쌍을 누적해 판정한다. v3.6의 "200건 중 게이트 실패 2%" 규칙은 안전(놓친 결함)과 효율(폴백)을 섞어 폐기했다.
- **계약:** `contracts/quality_gates.json`, `reference_impl/quality_gate.py`(21개 테스트).

## ADR-049 (v4.0, 사용자 결정) 제안 수준 임계값의 기본값 채택
`max_reviewable_diff_bytes = 409,600`, Lease TTL 10분, Registry 만료 14일, 검증 Runner 이용률 80% backpressure, 컨텍스트 결정 최소 30세션·복원률 손익분기 70%, 공정성 지표 등 v3.x에서 "제안"이던 값을 기본값으로 채택한다. 값 변경은 `quality_gates.json`(또는 해당 계약) 새 버전 + ADR로만 한다. 실측으로 근거가 생기면 조정한다.

## ADR-050 (v4.0, 사용자 결정) 단일 통합 명세
페이지별 v3.1~v3.6 레이어를 없애고 각 페이지를 현재 유효한 결정 하나로 다시 썼다. 페이지 서식(목적·결정·계약 머리줄, 요구사항 표 `R{NN}-{n}`)과 결정 레지스터(p.50)를 validator가 검사한다(C9). 어휘 lint(C4)는 이제 기획서 전체에 적용된다. 충돌 해소 목록은 `review/EvoForge_v4.0_Integration_Report.md`.

## ADR-051 (v4.0) 마일스톤 사다리 M0–M6
v3.x의 6가지 단계 체계를 하나로 합쳤다. 순서 원칙: 증명 수단(봉인 평가·X_SINGLE 기준선)과 과금 안전(예약·원장)이 첫 외부 호출보다 먼저(M0), 압축 codec은 A_RAW 기준선 이후(M3), 연동 표준은 필요한 순서대로(MCP·Folder M2, A2A M4), 하네스 연구 루프는 GA 이후(M6).

## ADR-052 (v4.0) Core Plane 불변식의 DB 강제
병합 승인(`core.authorize_merge` + `MERGED` 진입 트리거), Lease fencing(`claim_task`, `assert_fencing`), 명령 수명주기·위험 명령 확정·멱등성(`accept_command`, 전이 트리거), 외부 부작용 상태 머신(UNKNOWN 재시도 금지), 비용 예약·하드캡·원장 부호·역분개 규칙을 PostgreSQL에서 강제한다. 앱 역할에는 DELETE가 없고 UPDATE는 컬럼 단위다. 서비스 코드의 버그가 있어도 이 불변식은 깨지지 않는다. 계약: `contracts/sql/core_DRAFT.sql`, `core_tests.sql`(v4.0 46개, v4.1 57개 검사).

## ADR-053 (v4.0) 상태 모델·명명 통일
명령 수명주기 1개(RECEIVED…REJECTED), 에이전트 4차원 상태, Run/Task/Candidate 분리 상태 머신, 토폴로지 5종(SINGLE, RACE_2, DAG_PARALLEL, PIPELINE, HIGH_RISK), 제품 실험군 `X_*`와 컨텍스트 실험군 `A_RAW…`의 분리, North Star는 WVI 하나, 테넌트 컬럼 `tenant_id`. 이전 이름은 `vocabulary.json`의 `deprecated`에 대응표로 남긴다.

## ADR-054 (v4.1) 고위험 독립성 = 자격 + 컨텍스트 독립 + 명세 선행
- **바뀐 것:** v4.0은 HIGH/CRITICAL에 서로 다른 모델 계열의 critic 2명을 요구했다. <!-- vocab:allow --> 2610.28667은 독립 검증의 효과가 컨텍스트 독립과 명세 선행 테스트에서 나왔고, 다른 공급사 검증자가 결함을 더 찾지는 못했다고 보고했다.
- **결정:** HIGH/CRITICAL 병합에는 (1) 해당 위험 등급·하네스 버전에 자격이 유효한 검증자의 (2) 빌더 transcript·근거·자기평가를 보지 않은(context_independent) (3) diff를 보기 전에 명세만으로 수용 테스트를 봉인한(spec_tests_sealed_at < diff_first_read_at) approve가 필요하다. 빌더에게 돌려주는 것은 반례(입력·기대값·관측값·테스트 참조)뿐이다. 인간 승인 요구는 그대로다.
- **강제:** `core.authorize_merge`, `core.reviewer_qualifications`, `reviews.review_spec_first_order` CHECK(C-18, C-19). 참조: `reference_impl/review_policy.py`.
- **결과:** 공급사 다양성은 장애 격리(p.22) 목적에서만 유지한다. 모델 계열이 같아도 위 조건을 만족하면 독립 검증으로 인정한다.

## ADR-055 (v4.1) 병합 무결성 게이트 GH_INTEGRITY
테스트 오라클 강도(2606.18168), 공개/held-out 격차·조회 테이블(2605.21384), 검증기 변조(skip 추가·assert 삭제·예외 삼킴·보호 파일 수정)를 한 게이트로 묶어 **항상 필수**로 둔다. 순서는 G2_REQUIRED 다음, G3_BENCHMARK 앞. 실패·INCONCLUSIVE는 병합 차단. LLM 보상 해킹 모니터(2610.10947)는 보조 신호이고 단독 차단 근거가 아니다. 참조: `oracle_strength.py`, `reward_hack.py`, C-16.

## ADR-056 (v4.1) 결합 게이트 GC_COMPOSITION과 동시 변경 통지
같은 wave에 REJECTED가 아닌 후보가 2개 이상이면 결합본 실행 결과가 PASS여야 병합한다. 간섭 = 기준선과 각 패치 단독에서 통과한 테스트가 결합본에서 실패. 실패 시 쌍 단위 재실행으로 원인 쌍을 찾는다. 작업 중인 Builder에게는 다른 Builder가 바꾸거나 지운 공개 심볼 중 자기가 참조하는 것만 통지한다(2609.25396: 통지로 82% 회복). 참조: `composition_gate.py`, C-17.

## ADR-057 (v4.1) 리뷰 신호 규칙
차단 판정(changes_requested, reject)에는 실행 가능한 증거(failing_test, reproducer_script, static_rule_hit, policy_violation)와 참조가 필수다(DB CHECK). 증거 없는 차단 지적은 advisory로 강등하고 후보당 5개만 노출한다. 리뷰어 자격에 지적 정밀도 Wilson 하한 0.40(≥ 100건)을 추가한다. 근거: 2603.11078(정밀도 3–5%, Reflexion은 SNR 하락).

## ADR-058 (v4.1) 선택 = 실행 증거 우선, 판정자는 동점에서만
후보 순위: 게이트 PASS → 보상 해킹 flag 없음 → 재현 테스트 Wilson 하한 → held-out Wilson 하한 → 작은 diff → ID. 증거 차이가 0.02 이내인 후보끼리만 재귀 토너먼트(3표 다수결). 샘플 수는 adaptive k(1~5): LOW는 첫 full-pass에서, 나머지는 행동이 같은 full-pass 2개에서 멈추고, full-pass끼리 행동이 다르면 더 뽑는다. 근거: 2607.00990, 2604.16529, 2610.00972. 참조: `selection.py`.

## ADR-059 (v4.1) 응집도 기반 분할과 읽기 전용 투기 실행
DAG_PARALLEL은 허브 격리 후 응집도 ≥ 0.75, 예상 속도 ≥ 1.3배일 때만 고른다. 허브 파일은 wave 0에서 인터페이스 먼저 직렬 처리한다(2606.00953). 도구 호출 투기는 읽기 전용 5종만, 순서 커밋 + read set 검증, 거짓 수락 0을 불변식으로 둔다. 공급사 호출(과금), GitHub, 과금, 배포, 쓰기, 셸, 네트워크는 투기하지 않는다(2609.38201). 참조: `partitioner.py`, `speculative.py`.

## ADR-060 (v4.1) 캐시 배치 S11과 경계 단위 압축 평가
캐시 breakpoint는 L0–L2에만 두고, 동적 도구 결과·비신뢰 콘텐츠는 마지막 breakpoint 뒤에만 둔다(2601.06007). 압축(M3)은 compaction 경계 단위로 짝지어 평가하고(2608.06503), 접기는 ReFold처럼 청크 단위로 몇 단계마다만 prefix를 다시 쓴다(2610.07863, TRIAL). validator S11, invalid 예시 2개.

## ADR-061 (v4.1) 평가 효율·위생과 M6 최적화 규칙
- 사람 라벨 지표(수용·리뷰 유용성)에는 PPI(power-tuned)를 허용하고 안전 지표에는 금지한다. 최소 라벨 Tier A 80, Tier B 300.
- 평가 샌드박스는 base 이후 git 이력·reflog·remote를 제거하고, 모든 점수에 scaffold를 함께 기록한다. 공급사 자체 scaffold 점수는 공개 문구에 인용하지 않는다.
- M6 하네스 최적화: GEPA 기준선, 구조화 패치, dev 세트로만 선택, 봉인 test 1회, 편집 예산 120 → 20줄 annealing(2608.23041, 2609.24972). 정책 RL 공동 최적화(2610.22791)는 HOLD.
- 보정 cascade(2605.18796)와 단계 기억(2610.27377)은 TRIAL이며 critic·보안 리뷰어·HIGH/CRITICAL에는 cascade를 쓰지 않는다.

## ADR-062 (v4.2) Python 오라클 분류는 AST, 정확도는 측정해서 공개
- **문제:** v4.1의 줄 단위 정규식은 assert 메시지 속 `==`(약한 테스트를 강하다고 판정), 문자열 속 assert 문구, 여러 줄 assert를 잘못 읽었다. 정확도도 측정하지 않았다.
- **결정:** Python은 `ast`로 분류하고(`reference_impl/oracle_ast.py`), 파싱 실패 시에만 정규식을 쓴다. 개발 말뭉치(58건, 회귀 기준 100%)와 분류기 확정 후 작성한 holdout(20건, 튜닝 금지)으로 측정한다. 현재 holdout 강/약 일치 0.85(Wilson 95% 0.64–0.95), 약→강 오판 0.05. 같은 holdout에서 정규식은 0.90이었으므로 "AST가 항상 낫다"고 주장하지 않는다. 78건 전체로는 AST 0.96, 정규식 0.78.
- **잠정 규칙:** 사람 라벨 holdout이 200건 미만이면 오라클 미달은 `GH_INTEGRITY=INCONCLUSIVE`(예외 승인·테스트 보강으로 해제 가능). 보상 해킹·변조는 항상 FAIL. `reference_impl/integrity_gate.py`.
- 같은 AST 비교로 동시 변경 통지의 Python 심볼 비교도 바꿨다(`composition_gate.notices_from_sources`).

## ADR-063 (v4.2) 평가 샌드박스는 재구성, 정리하지 않는다
기존 clone에서 ref·remote를 지우는 방식은 alternates·packed refs·reflog·dangling 객체 등 빠뜨릴 경로가 많다. 그래서 임시 bare clone에서 base에 브랜치를 걸고, 그 브랜치만 `--no-local --single-branch --no-tags`로 새 저장소에 받는다. 이어서 remote 제거, reflog 만료, gc, hooks 비우기를 한다. 실행 전 감사 7항목을 통과해야 하고, 점수 행은 scaffold 5필드가 있어야 만들어진다. 실제 git으로 시험했다: 일반 clone + checkout은 미래 커밋과 remote를 남기고, 재구성본에서는 미래 커밋 객체와 그 내용이 모두 없다(`reference_impl/eval_hygiene.py`, CR-74).

## ADR-064 (v4.2) 압축 경계 판정 수치
경계마다 짝지은 continuation(3턴, seed ≥ 3, 군집 = 세션)으로 판정하고, 다음 네 조건을 모두 요구한다. (1) 지속 성공률 비열등 (2) 반복 탐색 비율 95% 상한 ≤ 1.10 (3) 막힌 행동 비율 95% 상한 ≤ 1.10 (4) seed 간 불일치 경계 비율 증가 ≤ 5%p. 세션이 30개 미만이면 UNDERPOWERED다. 성공률만 보면 반복 탐색이 늘어나는 것을 놓치므로 이 조건들을 둔다(`reference_impl/compaction_eval.py`, CR-75).

## ADR-065 (v4.2) M6 최적화 실행 상태 머신과 패치 스키마
`OPEN → FROZEN → CLOSED`. 동결은 dev 1위이면서 GEPA 대비 dev 쌍별 우월성 하한이 0보다 클 때만 한다. 동결 후에는 새 패치를 받지 않고, `D_test`는 동결 후보에 1회만 연다. 변이 단위 `harness-patch/v1`에는 test 평가를 기록할 필드가 없다(표현 불가). 연산 5종, `..` 경로 금지, 부모 1~4개. Trust Kernel 경로, anchor 오류, 편집 예산 초과는 `check_patch`가 거부한다(`reference_impl/harness_optimizer.py`, CR-76).
