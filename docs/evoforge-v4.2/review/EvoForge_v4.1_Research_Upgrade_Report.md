# EvoForge v4.1 연구 반영 보고서

대상: `legacy/v4.0/EvoForge_Blueprint_50pages_v4.0.md`와 v4.0 계약 패키지 · 조사 범위 논문 33건(31건은 2025-12 ~ 2026-10 공개, 기반 방법론 PPI·CaMeL 2건) + SWE-bench Pro 공개 자료 · 작성일 2026-10-25

## 1. 결과 요약

| 항목 | v4.0 | v4.1 |
|---|---|---|
| 기획서 | 157KB, 요구사항 160개, 결정 D-001~D-040 | 185KB, 요구사항 181개, 결정 D-001~D-052 |
| ADR | 035~053 | 035~061 |
| 수용 테스트 | CR-01~58 | CR-01~76 (신규 18개 중 15개 실행 근거 있음) |
| 병합 게이트 | G0, G1, G2, G3, GR, G4 | + `GH_INTEGRITY`(항상 필수), `GC_COMPOSITION`(wave 후보 ≥ 2) |
| 고위험 독립성 | 서로 다른 모델 계열 critic 2 또는 인간 <!-- vocab:allow --> | 자격 + 컨텍스트 독립 + 명세 선행 verifier + 인간 승인(DB 강제) |
| SQL 검사 | 85 (context 39 + core 46) | 96 (context 39 + core 57) |
| 참조 구현 테스트 | 43 (REF 22 + QG 21) | 84 (REF 22 + QG 23 + PERF 39) |
| 의미 규칙 | S1–S10 | S1–S11(캐시 배치) |
| 예시 | valid 6 / invalid 28 | valid 6 / invalid 30 |
| `quality_gates.json` | v1.0, 15개 섹션 | v1.1, 30개 섹션(v1.0 수치 불변) |

`tools/validate_package.py --pg` 전체 통과(PostgreSQL 16.15, Python 3.13.17): 스키마 4종, 예시 36개(실패 사유까지 일치), 어휘 lint 6개 파일(연구 레이더 포함), 50페이지 바이트 동일성, README 참조, 참조 구현 84개, SQL 96개, 페이지 서식·추적성(요구사항 181, 결정 52, 모든 참조 해석).

**변이 시험.** 복사본에 오류를 하나씩 넣어 검사가 잡는지 확인했다. 수용 테스트 행 삭제 → C9 FAIL. `GH_INTEGRITY`를 필수 목록에서 빼기 → SQL C-16 FAIL. 고위험 독립성 조건 삭제 → SQL C-18 FAIL. 폐기된 독립성 문구 삽입 → C4 FAIL. 오라클 기준 0.8 → 0.3 완화 → PERF FAIL. valid 패킷 L3에 breakpoint → S11 FAIL. 투기 허용 목록에 `fs.write` 추가 → 처음에는 통과했다(`speculable()`의 write set 검사가 막아 테스트가 깨지지 않음). 계약 목록 자체를 검사하는 테스트를 추가해 지금은 FAIL로 잡는다.

## 2. 채택 원칙

1. **논문 수치는 EvoForge 성과가 아니다.** 레이더에 "논문 보고치"로만 적고, 페이지에는 근거로만 인용한다. 서로 다른 모델·벤치마크·scaffold의 이득을 더하지 않는다(D-052).
2. **안전·무결성 장치는 바로 켠다(ADOPT).** 거짓 성공을 막는 장치(오라클 강도, 보상 해킹, 결합 실패, 증거 없는 차단, 캐시 배치, 평가 위생)는 성능을 올리는 기법이 아니라 측정의 전제다.
3. **속도·품질 기법은 실험으로만 켠다(TRIAL).** 각 기법은 독립 플래그를 갖고, 단독 절제 실험에서 Tier A를 통과해야 카나리, Tier B를 통과해야 기본값이 된다(p.49 R49-4).
4. **학습이 필요한 방법은 넣지 않는다.** 플랫폼 키로 상용 모델을 쓰는 구조(D-019)에서는 정책 모델 학습이 불가능하다 → Context-as-Tool, ACM 학습부, Self-HPO는 ASSESS/HOLD.
5. **임계값은 우리 제안값이다.** 논문이 공개하지 않은 기준(예: Co-Coder의 응집도 기준)은 우리가 정했고, `quality_gates.json`에 출처와 함께 적었다. 실측으로 조정한다.

## 3. 영역별 변경

### 3.1 병합 무결성(ADOPT)
- **`GH_INTEGRITY`** (D-042, ADR-055, p.36): ① 새 테스트의 강한 오라클 비율 ≥ 0.8, 재현 테스트는 전부 강함(2606.18168: 에이전트 테스트 패치 80.2%가 약하거나 오라클 없음) ② 봉인 held-out 격차(2605.21384) ③ 조회 테이블 ④ 검증기 변조. 참조: `reference_impl/oracle_strength.py`, `reference_impl/reward_hack.py`. DB가 필수 게이트로 강제(C-16).
- **`GC_COMPOSITION`** (D-043, ADR-056, p.29, p.36): 같은 wave에 살아 있는 후보가 2개 이상이면 결합 실행 PASS 필수, 간섭 시 원인 쌍 특정. 작업 중 Builder에게 참조 심볼의 시그니처 변경·삭제를 통지(2609.25396: 통지로 82% 회복). `candidates.wave_id`, C-17, `reference_impl/composition_gate.py`.

### 3.2 리뷰·검증(ADOPT)
- **고위험 독립성 교체** (D-041, ADR-054, p.06, p.28, p.35): 아래 §4 충돌 해소 1번.
- **차단 리뷰 증거** (D-044, ADR-057, p.35): `changes_requested`·`reject`는 실행 가능한 증거 종류와 참조가 있어야 DB에 기록된다(CHECK). 증거 없는 차단은 advisory로 강등, 후보당 5개 노출. 리뷰어 자격에 지적 정밀도 Wilson 하한 0.40 추가(2603.11078). `reference_impl/review_policy.py`, `reference_impl/quality_gate.py`, C-19.

### 3.3 선택·샘플링(TRIAL)
- **실행 증거 우선 선택** (D-045, ADR-058, p.16, p.35): 다면 재현 테스트(2607.00990) → held-out → diff 크기 순, 동점에서만 재귀 토너먼트(2604.16529), full-pass끼리 행동이 다르면 추가 샘플(2610.00972 합의 반박). `reference_impl/selection.py`.

### 3.4 병렬화·속도(TRIAL)
- **응집도 분할** (D-046, ADR-059, p.28, p.29): 허브 wave 0 + 결정적 커뮤니티 분할, 응집도 ≥ 0.75·예상 속도 ≥ 1.3배일 때만 DAG_PARALLEL(2606.00953). `reference_impl/partitioner.py`.
- **읽기 전용 투기 실행** (D-047, ADR-059, p.34): 읽기 전용 5종만, 순서 커밋, read set 검증, 거짓 수락 0(2609.38201). 무작위 호출열 300개에서 순차 실행과 결과 동일함을 테스트로 확인. `reference_impl/speculative.py`.

### 3.5 비용·컨텍스트(ADOPT + TRIAL)
- **S11 캐시 배치** (D-048, ADR-060, p.22, p.32, p.39; ADOPT): breakpoint는 L0–L2만, 도구 결과·비신뢰 자료는 캐시 prefix 밖(2601.06007). validator + invalid 예시 2개.
- **경계 단위 압축 평가**(ADOPT, 2608.06503), **가역 접기**(TRIAL, 2610.07863), **보정 cascade**(TRIAL, 2605.18796; critic·보안·HIGH/CRITICAL 제외), **단계 기억 회상**(TRIAL, 2610.27377). `reference_impl/cascade.py`, `reference_impl/memory_policy.py`, `contracts/Context_Mesh_Spec.md` §7.1·§11.

### 3.6 평가(ADOPT + TRIAL)
- **PPI** (D-049, ADR-061, p.37; TRIAL): 사람 라벨 지표에만, 안전 지표 금지. 좋은 autorater로 표준오차가 줄고 쓸모없는 autorater에서도 편향이 없음을 테스트로 확인. `reference_impl/ppi.py`.
- **평가 위생** (D-050, p.34, p.37; ADOPT): git 이력·remote 제거, scaffold 동시 기록, 공급사 scaffold 점수 인용 금지.

### 3.7 하네스 진화(M6, ADOPT 규칙)
- **최적화기 규칙** (D-051, ADR-061, p.38): GEPA 기준선, 구조화 패치, dev 선택, test 1회(2608.23041), 편집 예산 annealing·critic·pruner(2609.24972). 행동 검증기는 Trust Kernel 쪽(2603.03329).

### 3.8 보안(ADOPT)
- p.45 ASI01 통제를 "필터가 아니라 구조"로 명시: 계획은 신뢰 컨텍스트에서 확정, 비신뢰 데이터는 값으로만(2601.17548, 2503.18813). 위협 등록부에 보상 해킹·투기 실행 부작용 추가.

## 4. 충돌 해소

| # | v4.0 서술 | 충돌 근거 | v4.1 결정 |
|---|---|---|---|
| 1 | HIGH/CRITICAL은 서로 다른 모델 계열 critic 2명(p.06 I-1, p.28 HIGH_RISK, p.35, p.39 라우팅) <!-- vocab:allow --> | 2610.28667: 효과는 컨텍스트 독립·명세 선행에서 나왔고 다른 공급사 검증자는 결함을 더 찾지 못함. 또한 플랫폼 키 구조에서 공급사 2곳을 고위험 과제마다 강제하면 데이터 전송 동의 범위가 넓어진다 | 자격 + 컨텍스트 독립 + 명세 선행(DB 강제) + 인간 승인. 공급사 다양성은 장애 격리 목적으로만 남김. 폐기 문구는 `vocabulary.json` `deprecated`에 등록해 lint로 재유입 차단 |
| 2 | 리뷰는 `changes_requested`만 있으면 차단(C-09) | 2603.11078: 리뷰 정밀도 3–5% → 근거 없는 차단이 대부분 잡음 | 차단은 실행 증거 필수(DB CHECK). C-09 시험은 증거를 붙여 유지 |
| 3 | 후보 수 k는 "기대 추가 승률 × 영향 > 비용"일 때만 증가(p.16, p.38) | 기대 승률은 실측 전 추정 불가 | 실행 증거 기반 adaptive k(1~5) 규칙으로 대체 |
| 4 | DAG_PARALLEL 조건 = write set 비중첩(p.28) | 2606.00953: 파일이 겹치지 않아도 교차 의존이 컨텍스트 전달 비용을 만든다 | 응집도·예상 속도 판정 추가. write set 비중첩은 여전히 필요조건(p.29) |
| 5 | 테스트 조작 방지 = 테스트 삭제·skip 증가 전후 비교(p.36) | 2606.18168, 2605.21384: 테스트가 있어도 오라클이 약하거나 공개 테스트만 맞추는 경우가 많음 | `GH_INTEGRITY`로 확장, 항상 필수 |
| 6 | C-15 번호(v4.0: 에이전트 승인·폐기) | v4.1 신규 SQL 시험이 처음에 같은 번호를 썼음 | 신규 시험을 C-16~C-19로 배정, 기존 C-15 유지 |

## 5. 채택하지 않은 것

| 대상 | 고리 | 이유 |
|---|---|---|
| AdaptOrch 토폴로지 라우터(2602.16873) | ASSESS | 임계값이 그 논문 환경에서 보정됨. 폭·결합 밀도는 보고 지표로만 계산 |
| Context-as-Tool(2512.22087), ACM 학습부(2607.23809) | ASSESS | 모델 학습 필요. 원문 외부 저장 + ID 조회 구조는 이미 동일 |
| Self-HPO(2610.22791) | HOLD | 정책 RL 필요, 플랫폼 키 구조와 불일치 |
| Mixture of Self-Improving Branches(2609.37834) | ASSESS | M6 이후, 분기별 하네스 + 라우터 운영 비용 미검증 |
| Triage(2604.07494) | ASSESS | 측정 결과 없는 프로토콜 |
| FAQ 능동 질의(2601.20251) | TRIAL(미구현) | 다음 버전. 지금은 무작위 라벨 표본 + PPI |
| MACE(2607.11250), SPOQ(2606.03115) | ASSESS | 정량 근거 부족. RACE_2 계획 지문 중복 시 재계획만 채택 |
| LLM 보상 해킹 모니터 단독 차단(2610.10947) | TRIAL(보조) | 다회차 transcript에서 약하다고 보고됨 |

## 6. 한계

- **논문 확인 수준.** 33건 모두 초록·공개 HTML·검색 요약으로 확인했다. 전문의 실험 세부(표본, 분산, 비용)는 일부 논문에서 확인하지 못했고, 레이더에 "미공개"로 적었다. AutoSaddler는 본문(+8.4pp)과 표(+9.6pp)가 다르다.
- **참조 구현은 규칙의 실행 명세다.** 오라클 분류·조회 테이블 탐지·심볼 변경 추출은 정규식 기반 휴리스틱이다. 실제 서비스는 AST 기반으로 구현하고 이 테스트를 회귀 기준으로 이식한다. 휴리스틱 오탐·미탐률은 측정하지 않았다.
- **성능은 측정하지 않았다.** v4.1 기법의 EvoForge 내 효과는 M2·M3 절제 실험에서 처음 측정된다. 미측정 상태의 수치를 제품 문구·가격·SLO에 쓰지 않는다.
- **미구현 수용 테스트 3개:** CR-74(평가 러너), CR-75(M3 경계 평가), CR-76(M6 최적화기).

## 7. 파일 변경

| 구분 | 파일 |
|---|---|
| 신규 | `research/Technology_Radar_2026-10.md`, `review/EvoForge_v4.1_Research_Upgrade_Report.md`, `reference_impl/partitioner.py`, `reference_impl/composition_gate.py`, `reference_impl/oracle_strength.py`, `reference_impl/reward_hack.py`, `reference_impl/selection.py`, `reference_impl/review_policy.py`, `reference_impl/speculative.py`, `reference_impl/cascade.py`, `reference_impl/ppi.py`, `reference_impl/memory_policy.py`, `reference_impl/test_performance.py`, `contracts/examples/invalid/breakpoint_on_task_delta.json`, `contracts/examples/invalid/tool_output_in_cached_prefix.json`, `legacy/v4.0/EvoForge_Blueprint_50pages_v4.0.md` |
| 이름 변경 + 수정 | `EvoForge_Blueprint_50pages_v4.1.md`(헤더, p.06·10·16·22·26·28·29·31~40·42·45·47·49·50), `pages/EvoForge_v4.1_NN.md`(재생성) |
| 수정 | `contracts/quality_gates.json`(v1.1), `contracts/vocabulary.json`(4.1), `contracts/sql/core_DRAFT.sql`, `contracts/sql/core_tests.sql`, `contracts/Architecture_Decisions.md`, `contracts/Acceptance_Test_Matrix.md`, `contracts/Context_Mesh_Spec.md`, `reference_impl/quality_gate.py`, `reference_impl/test_quality_gate.py`, `tools/validate_package.py`(S11, C7, v4.1 이름), `tools/make_examples.py`, `tools/split_pages.py`, `build/CLAUDE_CODE_BUILD_PROMPT.md`, `README.md` |
