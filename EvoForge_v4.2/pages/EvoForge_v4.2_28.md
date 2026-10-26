<!-- PAGE:28/50 -->

# 28. 적응형 토폴로지와 역할 협의

> **목적:** 과제마다 필요한 만큼만 좌석을 쓰고, 독립성은 항상 지킨다. · **결정:** D-024, D-036, D-041, D-046 · **계약:** `contracts/vocabulary.json`(`topology`, `function_role`)

### 좌석과 기능 역할
좌석 5개(기본 라벨 Navigator, Builder Alpha, Builder Beta, Critic, Integrator)는 영구 직책이 아니라 배정 슬롯이다. 패킷·작업은 `seat_id`와 `function_role`(planner/builder/critic/verifier/integrator/observer)을 따로 가진다. Planner가 계획 산출물을 저장하면 그 좌석을 구현·검증에 다시 쓸 수 있다.

### 토폴로지(정본 5종)
| 토폴로지 | 활성 구성 예 | 선택 근거 |
|---|---|---|
| `SINGLE` (기본) | builder 1 + 독립 critic 1 | 작은 변경, 순차 의존 |
| `RACE_2` | planner(짧게) + builder 2(독립 후보) + critic + integrator | 설계 불확실, 독립 접근법의 가치가 큼 |
| `DAG_PARALLEL` | builder 최대 3 + planner/integrator + critic | 응집도 분할 판정 통과(허브 격리 후 응집도 ≥ 0.75, 예상 속도 ≥ 1.3배, p.29) |
| `PIPELINE` | planner → builder → critic → integrator/benchmark | 단계별 과제가 연속 공급됨 |
| `HIGH_RISK` | builder 1 + critic 1 + **자격 있는 컨텍스트 독립 verifier 1**(명세 선행) + planner | 보안·계약·마이그레이션 등 고위험 |

### 선택 규칙
1. Task Analyzer가 난도·위험·예상 write set·DAG 분리성·예상 테스트 시간을 구조화한다. 변경 예상 파일의 의존 그래프를 `reference_impl/partitioner.py` 규칙으로 분할해 허브·파티션·응집도·예상 속도를 계산한다. 폭(width)·결합 밀도(coupling density)는 보고용 지표로만 쓴다.
2. 처음에는 **규칙 기반**으로 고른다. 분할 판정이 SINGLE이면 `DAG_PARALLEL`을 고르지 않는다. 같은 모델의 단일 에이전트가 동질 다중 에이전트 워크플로와 동등하다는 보고(2601.12307)가 있으므로 모든 다중 좌석 토폴로지는 `X_SINGLE` 대비 이득을 증명해야 한다. 검증 완료 과제 100건 이상이 쌓이면 contextual bandit을 실험 arm으로 시험하고, p.37 Tier A를 통과해야 기본값이 된다.
3. 좌석 추가는 `예상 유효 개선 증가분 > 예상 API·CI 비용 + 통신·충돌 비용`일 때만. 미충족이면 축소한다.
4. 협의는 `1차 제안 → 1차 반론 → 결정`으로 끝낸다. 미응답 Chat 때문에 멈추지 않도록 `timeout + fallback_owner`.
5. 점수: `Utility = P(valid fix) × impact − λ·cost − μ·latency − ρ·risk`. 확률은 실측 표본·신뢰구간이 충분할 때만 쓰고, 아니면 단순 휴리스틱. AI의 자기선언 수치는 사실로 취급하지 않는다.
6. 계획 모델이 만든 DAG는 Scheduler가 비순환·권한·자원 충돌을 검증해야 실행된다. 파일 변경·도구 호출마다 Planner 승인을 기다리게 직렬화하지 않는다.

### 독립성
작성자는 같은 후보의 최종 리뷰어가 될 수 없다(DB 강제). `RACE_2`의 독립 후보는 서로의 미검증 패치를 기본으로 보지 않고, 두 후보의 계획 지문(접근법 요약 해시)이 같으면 두 번째 후보를 다른 접근법으로 재계획한다(에이전트끼리 탐색이 좁아지는 경향, 2607.11250). 연구 루프에서도 `patch author ≠ reviewer`, `implementer ≠ promotion approver`.

**고위험 독립성(D-041).** HIGH/CRITICAL의 독립성은 공급사·모델 종류가 아니라 **무엇을 보았는가**로 정의한다. verifier는 (1) 해당 등급·하네스 버전 자격이 유효하고 (2) 빌더 transcript·근거·자기평가·임시 테스트를 보지 않으며 (3) diff를 열기 전 명세만으로 수용 테스트를 봉인한다(Phase A → Phase B). 빌더에게는 반례만 돌려준다. 근거: 2610.28667에서 독립 검증의 효과는 컨텍스트 독립과 명세 선행에서 나왔고, 다른 공급사 검증자가 결함을 더 찾지 못했다. 공급사 다양성은 장애 격리(p.22) 목적으로만 남긴다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R28-1 | 과잉 협업 방지 | 단일 파일 수정 과제에서 X_ADAPTIVE5 비용 ≤ X_SINGLE × 1.2 (제안값) |
| R28-2 | 고위험 독립성 | HIGH/CRITICAL 병합 중 자격·컨텍스트 독립·명세 선행 approve 또는 인간 승인이 없는 것 0건 (C-18, C-19, CR-66) |
| R28-3 | 결정 기록 | 모든 토폴로지 선택에 사전 예측(대기시간·토큰·유효 패치율, 분할 응집도·예상 속도)과 실제값이 저장 |
| R28-4 | 분할 판정 | 같은 입력에서 같은 분할, 응집도·예상 속도 미달이면 SINGLE (CR-59) |

---
