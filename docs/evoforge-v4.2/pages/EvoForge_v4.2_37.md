<!-- PAGE:37/50 -->

# 37. 평가·실험 통계 기준 (Quality Gate Framework v1)

> **목적:** "품질이 유지됐다", "더 싸졌다", "N배 빨라졌다"를 판정하는 규칙을 하나로 정한다. · **결정:** D-014, D-020, D-021, D-029, D-036, D-049, D-050, D-052, D-056 · **계약:** `contracts/quality_gates.json`, `reference_impl/quality_gate.py`

### 왜 이 기준인가
v3.x는 "quality ≥ baseline", "2%p margin", "200건 중 2%" 같은 문장이 흩어져 있었고, 표본 크기·군집 상관·검정력·안전과 효율의 구분이 없었다. 최적화 기준은 세 가지다: ① **불리한 쪽 경계로 판정**한다(비열등성은 하한, 비용은 상한, 주장은 하한) ② **안전은 허용 오차 0**, 효과는 비열등성 margin, 효율은 유의한 개선일 때만 채택한다 ③ **비용과 검정력을 맞춘다** — 엄격한 margin은 표본이 매우 많이 필요하므로 단계(Tier)를 둔다.

### 실험 설계
- 표본 단위 = `(task, seed)` 쌍. 같은 쌍을 기준 arm과 후보 arm 모두에서 실행한다(paired). 과제당 seed ≥ 3.
- 군집 = task. 같은 과제의 반복은 상관되므로 **task 단위 cluster bootstrap**(4,000회, 시드 고정)으로 구간을 낸다. 독립 표본처럼 계산하면 구간이 거짓으로 좁아진다(테스트로 확인).
- 과제 계열 6종(`simple_sequential`, `parallel_multi_file`, `algorithmic_optimization`, `security_sensitive`, `chat_dropout`, `ci_saturated`), 계열당 ≥ 10%.
- 데이터 분리: `D_evo`(진단·개발) / `D_val`(선택) / `D_test`(봉인, 후보 동결 후 1회, 불리한 결과도 보고). 같은 모델 revision·샘플링·도구 버전·시작 SHA·실행 환경·비용/시간 한도.
- **사전 등록:** `ExperimentPrediction`(대상, 기준 버전, 지표, 기대 변화, 부작용, 예산, 평가 데이터 해시)을 시작 전에 불변 저장한다. 중간 분석은 무용성 중단만 허용하고 조기 성공 판정은 하지 않는다.

### 판정 규칙
| 클래스 | 지표 | 규칙 |
|---|---|---|
| 안전(0 허용) | 기준은 잡고 후보는 놓친 critical seeded defect, 봉인 재채점 회귀 유출, 정책·테넌트·승인 위반, 예산 초과, 비밀 노출 | 각 0건. critical seeded defect ≥ 100건, 후보 검출률 Wilson 95% 하한 ≥ 0.90 |
| 효과(비열등성) | 검증 수정률(VFR), seeded defect 전체 검출률 | 차이(후보−기준)의 단측 95% cluster-bootstrap 하한 > −δ, **관측 불일치율로 다시 계산한 필요 표본 이상** (부족하면 FAIL이 아니라 UNDERPOWERED) |
| 효율(우월성) | 쌍별 비용 비율(provider_billed) | 95% 구간 상한 < 1.0 |
| 주장 | 속도 비율 S, 비용 절감률 | 공개 값 = 95% 구간 하한 |

### Tier
| Tier | 용도 | δ | 최소 과제 | 필요 쌍(불일치율 0.10 기준) |
|---|---|---:|---:|---:|
| `A_canary` | 테넌트 opt-in Canary 진입, 실험의 다음 단계 진출 | 5%p | 80 | 248 |
| `B_default` | 전 테넌트 기본값 승격, GA 판정, 공개 성과 주장 | 2%p | 500 | 1,546 |
필요 쌍 `n = ⌈(z₀.₉₅ + z₀.₈₀)² · p_d / δ²⌉`. 불일치율이 0.20이면 2배가 필요하다. Tier B는 비싸므로 Canary·shadow 재생으로 쌍을 누적해 판정한다.

### 운영 중 감시(codec 런타임)
손실 뷰로 리뷰한 패킷의 2%를 RAW 원문으로 shadow 재리뷰한다. 손실 쪽이 놓친 high 이상 결함 = miss. critical miss 1건 또는 miss율 Wilson 하한 > 0.5%이면 `(source_kind, codec@version, provider)`를 즉시 비활성화한다. 30일 창에서 감사가 50건 미만이면 `감사 부족` 경보. 게이트 실패로 인한 RAW 폴백은 **안전 사건이 아니라 효율 문제**이므로, 500건 이상에서 폴백 30% 이상이면 검토 대상으로만 올린다.

### 비교 실험군
- 제품 arm: `X_SINGLE`(단일 AI + 독립 검증), `X_NAIVE5`(무계획 5병렬), `X_ADAPTIVE5`(적응형 5좌석), 절제 `X_ABL_BACKPRESSURE`·`X_ABL_HANDOFF`·`X_ABL_TOPOLOGY`·`X_ABL_CONTEXT`. **동일 시간 실험과 동일 비용 실험을 따로** 판정한다.
- 컨텍스트 arm(p.39): `A_RAW`(주 기준선, 공급사 기본 캐시) / `B_STRUCTURAL` / `C_RECOVERABLE` / `D_RAW_EXPLICIT_CACHE` / `E_CACHE_AWARE`, 그리고 캐시를 끌 수 있는 모델에서만 참고용 `A0_RAW_NOCACHE`.
- ABBA 벤치마크는 환경 드리프트를 줄이는 수단일 뿐이다. 외란·캐시 워밍업·데이터 누출·컴파일 재사용을 기록한다. 개선 폭이 오차 범위면 `NO_CONFIDENT_IMPROVEMENT`.

### 평가 효율과 위생(v4.1)
- **PPI(D-049).** 사람 라벨이 필요한 효과 지표(`human_acceptance`, `review_usefulness`)는 autorater 점수를 모든 과제에, 사람 라벨을 무작위 부분집합에 붙이고 예측 기반 추론(power-tuned λ)으로 구간을 낸다. autorater가 나빠도 편향되지 않고 구간만 넓어진다(λ→0). 최소 라벨 Tier A 80, Tier B 300. **안전 지표(critical recall, 회귀 유출, 정책 위반)에는 쓰지 않는다.** `reference_impl/ppi.py`.
- **경계 단위 압축 평가(D-056).** 압축·접기는 compaction 경계마다 같은 상태에서 압축/비압축 continuation(3턴, seed ≥ 3)을 짝지어 비교한다(2608.06503: 반복 압축이 막힌 행동·반복 탐색·실행 불안정을 늘림). 군집은 세션. 네 조건을 모두 만족해야 통과한다: ① 지속 성공률 비열등(Tier δ) ② 반복 탐색 비율 95% 상한 ≤ 1.10 ③ 막힌 행동 비율 95% 상한 ≤ 1.10 ④ seed 간 결과가 갈리는 경계 비율 증가 ≤ 5%p. 세션 30개 미만은 UNDERPOWERED. 성공률이 같아도 반복 탐색이 늘면 탈락한다. `reference_impl/compaction_eval.py`.
- **평가 위생(D-050).** 평가 샌드박스는 base 이후 git 이력·remote를 제거한다. 모든 점수에 scaffold를 표기하고, 공급사 자체 scaffold 점수는 비교·공개 문구에 쓰지 않는다(공개 보드에서 공급사 scaffold가 10–30점 높게 나타남).
- **연구 수치의 지위(D-052).** 외부 논문의 수치는 사전 예측(`ExperimentPrediction`)의 근거로만 쓰고, 판정은 우리 실측으로만 한다. 서로 다른 논문의 이득을 더하지 않는다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R37-1 | 판정 구현 일치 | 서비스 판정이 `quality_gate.py`·`ppi.py`와 같은 입력에서 같은 결과(참조 테스트 23개 + PPI 3개 이식) |
| R37-2 | 과소표본 처리 | 표본 부족 실험의 승격 0건(UNDERPOWERED는 승격 불가) |
| R37-3 | 사전 등록 | 결과 확인 후 목표·지표를 바꾼 실험 0건(불변 기록) |
| R37-4 | 공개 성과 | 모든 성과 문구에 재현 코드·환경·기준선·반복·측정일·구간 하한·scaffold 연결 |
| R37-5 | PPI 범위 | 안전 지표에 PPI 적용 0건, 최소 라벨 미달 판정은 UNDERPOWERED (CR-72) |
| R37-6 | 경계 판정 | 기본값이 된 압축·접기 방식은 모두 경계 단위 4조건 통과 기록이 있음 (CR-75) |

---
