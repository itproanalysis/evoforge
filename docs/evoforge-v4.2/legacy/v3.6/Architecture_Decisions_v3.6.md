# EvoForge v3.6 — 기술 결정 기록 (ADR-035 ~ ADR-046)

v3.5의 ADR-035~040을 다시 검토했다. **R**은 개정된 결정, **N**은 새 결정이다. 원본: `legacy/v3.5_contracts/EvoForge_v3.5_Architecture_Decisions.md`.

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
