# EvoForge 기술 레이더 2026-10 (v4.1 반영 근거)

조사일 2026-10-25. 대상은 논문 33건(31건은 2025-12 ~ 2026-10 공개, 기반 방법론 2건은 PPI 2023·CaMeL 2025-03)과 SWE-bench Pro 공개 자료다. 이 문서는 **무엇을 채택했고, 어떤 근거로, 어떤 테스트로 확인하는지**를 한 줄씩 남긴다. 기획서(p.16, 22, 26, 28, 29, 31~40, 45, 47, 49, 50)와 계약(`contracts/quality_gates.json` v1.1, `contracts/sql/core_DRAFT.sql`, `reference_impl/*`)은 이 표를 따른다.

## 0. 읽는 법

**논문 수치는 EvoForge 성과가 아니다.** 아래 "논문 보고치"는 저자가 자기 설정에서 보고한 값이다. 서로 다른 모델·벤치마크·scaffold에서 나온 값이라 **더하거나 옮겨 쓸 수 없다.** 채택한 모든 기법은 EvoForge 자체 평가에서 Quality Gate Tier A(카나리)와 Tier B(기본값)를 통과해야 켜진다(p.36–37). 통과 전에는 제품 문구·가격·SLO에 쓰지 않는다.

**근거 등급**

| 등급 | 기준 |
|---|---|
| A | 동료 심사 학회·저널 게재 또는 독립 재현 있음, 코드·데이터 공개 |
| A- | 공개 코드·벤치마크가 있는 프리프린트, 복수 벤치마크 또는 대규모 실증(수만 건 이상) |
| B | 프리프린트, 단일 영역 벤치마크 또는 구성(constructed) 과제, 소표본 |
| C | 제안·프로토콜·예비 결과, 정량 결과 없음 또는 학습 필요 |
| D | 공급사 자체 보고, 블로그·리더보드 집계 |

**채택 고리(ring)**

| 고리 | 의미 | EvoForge에서 하는 일 |
|---|---|---|
| ADOPT | 위험이 낮고 근거가 충분하다 | 계약·DB·게이트에 고정. 기본 켬(게이트·검증 계열은 성능이 아니라 안전 장치라 A/B 없이 켠다) |
| TRIAL | 이득 가능성이 크지만 우리 환경 효과는 모른다 | 참조 구현 + 실험군. Tier A 통과 시 카나리, Tier B 통과 시 기본값 |
| ASSESS | 흥미롭지만 전제(학습·인프라)가 맞지 않거나 근거가 약하다 | 문서화만, 분기마다 재검토 |
| HOLD | 지금 쓰지 않는다 | 이유 기록 |

## 1. 요약: v4.1에서 바뀐 것

1. **병합 무결성 게이트 2개 추가.** `GH_INTEGRITY`(테스트 오라클 강도 + 보상 해킹 탐지 + 검증기 변조 탐지, 항상 필수)와 `GC_COMPOSITION`(같은 wave에 살아 있는 후보 2개 이상이면 결합 실행 필수). DB의 `core.authorize_merge`가 강제한다(C-16, C-17).
2. **고위험 독립성 규칙 교체.** v4.0의 "다른 모델 계열 critic 2" 규칙을 <!-- vocab:allow --> **자격 있는(qualified) + 컨텍스트 독립 + 명세 선행(spec-first) 검증자**로 바꿨다. 근거: 독립성의 효과는 공급사 차이가 아니라 컨텍스트 분리와 명세 선행에서 나왔다(2610.28667). DB가 강제한다(C-18, C-19).
3. **차단 리뷰는 실행 가능한 증거 필수.** 증거 없는 차단 지적은 advisory로 강등하고 후보당 5개로 제한한다. 리뷰어 자격에 정밀도(SNR) 하한을 추가했다(2603.11078).
4. **선택은 실행 증거가 먼저.** 다면 재현 테스트와 봉인 held-out 결과로 순위를 매기고, 증거가 같을 때만 토너먼트 판정을 쓴다. 샘플 수는 증거가 결정적이면 일찍 멈춘다(adaptive k).
5. **응집도 기반 분할.** 허브 파일을 wave 0에서 직렬 처리하고, 나머지를 커뮤니티 단위로 나눠 병렬화한다. 응집도 0.75·예상 속도 1.3배 미만이면 SINGLE로 남는다.
6. **캐시 배치 규칙 S11.** 캐시 breakpoint는 L0–L2에만, 동적 도구 결과는 캐시 prefix 밖에만 둔다. validator가 검사한다.
7. **읽기 전용 도구의 투기 실행.** 공급사 호출·GitHub·과금·쓰기·셸·네트워크는 절대 투기하지 않는다. 순서대로 커밋하고, 투기 이후 앞선 쓰기와 read set이 겹치면 재실행한다.
8. **평가 효율·위생.** 사람 라벨이 비싼 지표에 PPI(예측 기반 추론), 압축은 경계 단위로 평가, 평가 샌드박스에서 미래 git 이력 제거와 scaffold 동시 보고.
9. **M6 하네스 진화 규칙 구체화.** GEPA 기준선, 구조화 패치, dev 세트로만 선택, 봉인 test 1회, 편집 예산 annealing.

## 2. 레이더 전체

표기: `QG.x` = `contracts/quality_gates.json`의 섹션, `PERF` = `reference_impl/test_performance.py`, `C-xx` = `contracts/sql/core_tests.sql`, `VAL` = validator.

### 2.1 협업·토폴로지·병렬화

| ID | 제목(제출일) | 등급 | 논문 보고치 | 고리 | EvoForge 반영 | 수용 테스트 |
|---|---|---|---|---|---|---|
| 2606.00953 | Cohesion-Aware Task Partitioning for Multi-Agent Coding, Co-Coder (2026-05-31) | B | 28개 과제에서 통과율 최대 +14.0%, 벽시계 최대 2.10배, API 비용 최대 −35%. 의존성 밀도 높은 프로젝트에서 이득 최대. 응집도 지표·임계값은 미공개 | TRIAL | `reference_impl/partitioner.py`: 허브 격리 → 결정적 label propagation → 좌석 수 상한 병합 → 응집도·예상 속도 판정. 임계값은 우리가 정했다(QG.partitioning). p.28–29 | CR-59 · PERF `Partitioner.*` |
| 2609.25396 | Passes Alone, Fails Together (2026-09-21) | B | 구성 과제에서 결합 시 간섭 97%, 완료된 동시 변경을 알리는 메시지로 82% 회복. 실제 병합 PR 쌍에서는 834회 중 1회. 저자 스스로 실제 빈도 추정이 아니라고 밝힘 | ADOPT | `GC_COMPOSITION` 게이트(결합 실행, 간섭 시 차단, 쌍 단위 원인 특정) + 진행 중 Builder에게 공개 심볼 변경 통지. `reference_impl/composition_gate.py`. p.29, 36 | CR-60, CR-61 · C-17 · PERF `Composition.*` |
| 2602.16873 | AdaptOrch (2026-02-18) | B | 정적 단일 토폴로지 대비 12–23%. 폭 0.5·결합 0.6·하위 과제 5를 기본 임계값으로 사용 | ASSESS | 폭(width)·결합 밀도(coupling density)를 partitioner 보고 지표로만 계산한다. 토폴로지 결정에는 쓰지 않는다(우리 데이터로 보정 전) | — |
| 2601.12307 | A Strong Single Agent Baseline, OneFlow (2026-01-18) | B | 단일 에이전트가 동질 다중 에이전트 워크플로와 동등, 추론 비용 감소(수치 미공개) | ADOPT(원칙) | `X_SINGLE` 기준선을 모든 다중 에이전트 주장의 비교 대상으로 고정(기존 D-005 강화). 같은 모델만 쓰는 RACE_2는 계획이 서로 달라야 한다 | CR-65(분기 다양성) · p.10 사다리 |
| 2607.11250 | Multi-Agent LLMs Fail to Explore Each Other (2026-07-13) | B | 에이전트끼리의 탐색이 근시안적·양극화, 수치 미공개 | ASSESS | RACE_2 후보의 계획 지문이 같으면 두 번째 후보를 재계획한다(p.28). 동료 탐색 방법(MACE)은 도입하지 않는다 | — |
| 2606.03115 | SPOQ: Specialist Orchestrated Queuing (2026-06-01) | C | 방법론 제안 중심 | ASSESS | 참고만 | — |

### 2.2 선택·검증·리뷰

| ID | 제목(제출일) | 등급 | 논문 보고치 | 고리 | EvoForge 반영 | 수용 테스트 |
|---|---|---|---|---|---|---|
| 2607.00990 | SWE-Doctor (2026-07) | A- | 다면 재현 테스트 + 디버거 진단으로 SWE-bench Pro 50.5 → 59.4, 이슈당 추가 비용 약 $0.1–0.2 | TRIAL(우선) | 재현 테스트를 3개 측면(원 증상·경계·회귀 방지)으로 쓰게 하고(QG.selection.repro_facets), 각 테스트는 강한 오라클이어야 한다. 선택 1순위 증거 | CR-62, CR-65 · PERF `Selection.*`, `Oracle.*` |
| 2604.16529 | Scaling Test-Time Compute for Agentic Coding (2026-04-16) | A- | 구조화 요약 + 재귀 토너먼트 투표(RTV)·PDR로 SWE-bench Verified 70.9 → 77.6, Terminal-Bench v2 46.9 → 59.1. 비용 수치 미공개 | TRIAL | `reference_impl/selection.py`의 `tournament()`: **실행 증거가 같을 때만** 쓰는 동점 처리. 후보 요약은 구조화(가설·진행·실패 모드) | CR-65 · PERF `Selection.test_tie_goes_to_tournament` |
| 2610.00972 | VeriHarness (2026-10-01) | B | 불일치 해결기 + 합의 반박기로 단일 rollout 대비 +6.2/+6.4점. 2.6만 rollout, $10만 이상 | TRIAL | 실행 결과가 다른 full-pass 후보가 있으면 샘플을 더 뽑는다(합의 반박). 다수결로 선택하지 않는다 | CR-65 · PERF `Selection.test_adaptive_k` |
| 2610.28667 | Who Verifies the Builder? (2026-10) | B | 독립 검증의 효과는 컨텍스트 독립과 명세 선행(Phase A/B)에서 나옴. 다른 공급사 검증자가 결함을 더 찾지 못함(H2) | ADOPT | HIGH/CRITICAL: 자격 + 컨텍스트 독립(빌더 transcript·근거·자기평가 금지) + Phase A(명세만 보고 수용 테스트 봉인) → Phase B(diff 열람). 빌더에게는 반례만 전달. `core.authorize_merge`·`review_policy.py`. p.35 | CR-66 · C-18, C-19 · PERF `ReviewPolicy.*` |
| 2603.11078 | CR-Bench (2026-03-10) | A- | 리뷰 에이전트 정밀도 3–5%. Reflexion은 recall↑, SNR↓(GPT-5-mini 2.89 → 0.91) | ADOPT | 차단 리뷰는 실패 테스트·재현 스크립트·정적 규칙·정책 위반 중 하나의 증거 필수(DB CHECK). 증거 없는 차단은 advisory로 강등, 후보당 5개 상한. 자격에 지적 정밀도 Wilson 하한 0.40 추가 | CR-67, CR-68 · C-19 · QG `Reviewer.*` |
| 2606.18168 | All Smoke, No Alarm (2026-06-16) | A- | 에이전트 테스트 패치 86,156건 중 80.2%가 오라클 약함·없음. 정규식 분류기 인간 라벨 일치 86.7% | ADOPT | `reference_impl/oracle_strength.py`(Python·JS 정적 분류). 새 테스트의 강한 오라클 비율 ≥ 0.8, 재현 테스트는 전부 강해야 함. `GH_INTEGRITY`의 일부 | CR-62 · C-16 · PERF `Oracle.*` |
| 2605.21384 | SpecBench (2026-05) | A- | 공개 검증 통과율과 held-out 통과율의 격차가 큼(Claude Code 43–48pp), 과제가 클수록 증가. 합성·부정 테스트 필요 | ADOPT | `reward_hack.gap()`(Newcombe 구간), held-out에 compositional·negative 필수, 조회 테이블·검증기 변조 탐지. `GH_INTEGRITY`의 일부 | CR-63, CR-64 · PERF `RewardHack.*` |
| 2610.10947 | RH-Detect (2026-10) | B | LLM 모니터 AUROC 약 0.96, 다회차 transcript에서 약함 | TRIAL | LLM 모니터는 보조 신호. 단독 차단 근거로 쓰지 않는다 | CR-63(정적 탐지가 1차) |
| 2603.03329 | AutoHarness (2026-02-10) | B | 합성된 행동 검증기로 불법 수 0(145게임), 작은 모델이 큰 모델을 이김 | ADOPT(원칙) | 도구 호출 전 결정적 검증기(스키마·경로·권한)를 먼저 둔다. 기존 p.34 정책 검사와 동일 위치. 하네스 자동 합성은 M6 | p.34 R34 계열 |

### 2.3 컨텍스트·캐시·기억

| ID | 제목(제출일) | 등급 | 논문 보고치 | 고리 | EvoForge 반영 | 수용 테스트 |
|---|---|---|---|---|---|---|
| 2601.06007 | Don't Break the Cache (2026-01) | B | 프롬프트 캐시로 비용 41–80% 감소, 동적 도구 결과를 캐시 블록에서 빼야 함 | ADOPT | 의미 규칙 **S11**: breakpoint는 L0–L2에만, `untrusted_content`·`verified_tool_output` 항목은 마지막 breakpoint 뒤에만. invalid 예시 2개 | CR-69 · VAL S11 |
| 2610.07863 | ReFold (2026-10-06) | B | 학습 없이 토큰 최대 2.5배 감소, 성공률 저하 없음. 변경을 청크로 묶어 캐시 prefix를 몇 단계마다만 다시 씀 | TRIAL | M3 compaction epoch 경계에서만 접기(이미 본 내용 stub, 끝난 턴 한 줄 노트). 원문은 Evidence Vault에 있으므로 복원 가능 | CR-75 |
| 2608.06503 | Execution Instability under Context Compression (2026-08-06) | B | 반복 압축이 최근 상호작용 영향력을 약화 → 막힌 행동·반복 탐색 증가. 압축 사건 단위 평가 제안 | ADOPT(평가법) | 압축은 **경계 단위**로 평가: 같은 상태에서 압축/비압축 continuation을 짝지어 3턴 내 지속 성공률 비교(QG.compaction_eval) | CR-75 |
| 2512.22087 | Context as a Tool (2025-12-26) | C(우리 기준) | 32B 모델 SFT 후 SWE-bench Verified 57.6% | ASSESS | 학습이 필요해 플랫폼 키 기반 상용 모델에 적용 불가. 원리(고정 구간 + 장기 요약 + 최근 k턴)는 p.39 레이아웃과 일치 | — |
| 2607.23809 | ACM: Agentic Context Management (2026-07-26) | C(우리 기준) | 9B 학습 후 SWE-bench Verified 0.489 → 0.530 | ASSESS | 원문을 외부 저장하고 요약 ID로 조회하는 구조는 이미 `ctx.retrieve_evidence`로 있음. 학습부는 미적용 | — |
| 2610.27377 | REM (2026-10-19, NeurIPS 2026 워크숍) | B | 단계 구조 기억 + 게이트 회상 + 1회 노출 후 퇴출로 해결률 24.9 → 27.6%, 비용 −17%. 요약·원 trajectory 주입은 효과 없음 | TRIAL | `reference_impl/memory_policy.py`: Verified Improvement에서만 적재, 단계(localize·reproduce·fix·verify) 일치 + 태그 Jaccard ≥ 0.3일 때만 회상, 과제당 1회 노출 후 퇴출, 원 Run crypto-shred 시 함께 삭제 | CR-73 · PERF `Memory.*` |

### 2.4 실행 속도·비용 라우팅

| ID | 제목(제출일) | 등급 | 논문 보고치 | 고리 | EvoForge 반영 | 수용 테스트 |
|---|---|---|---|---|---|---|
| 2609.38201 | TomasuLLM (2026-09-22) | B | 투기 도구 실행 1.27–1.35배, 커밋 검증 4,010건 거짓 수락 0 | TRIAL | 읽기 전용 5종만 투기(QG.speculation). 금지 접두사: provider.call, github., billing., deploy., fs.write, shell., net. 순서대로 커밋, read set 충돌 시 재실행. `reference_impl/speculative.py` | CR-70 · PERF `Speculation.*`(무작위 300회, 순차 실행과 결과 동일) |
| 2605.18796 | UCCI (2026-05-11) | B | isotonic 보정 cascade로 비용 −31%(95% CI 27–35%), 단일 영역(NER) | TRIAL | `reference_impl/cascade.py`: PAV 보정, 수락 오류 Wilson 상한 ≤ 5%를 지키는 최소 비용 임계값. critic·보안 리뷰어·HIGH/CRITICAL에는 쓰지 않음 | CR-71 · PERF `Cascade.*` |
| 2604.07494 | Triage (2026-04-08) | C | 코드 건강도 신호로 모델 등급 라우팅. 측정 결과 없음(프로토콜) | ASSESS | 라우팅 특징 후보로 기록(복잡도·결합도). 근거 생기면 cascade 점수 입력으로 검토 | — |

### 2.5 평가 통계·평가 위생

| ID | 제목(제출일) | 등급 | 논문 보고치 | 고리 | EvoForge 반영 | 수용 테스트 |
|---|---|---|---|---|---|---|
| 2301.09633 | Prediction-Powered Inference (Angelopoulos 외, Science 2023) | A | 예측 모델 품질과 무관하게 유효한 구간, 좋은 예측기일수록 좁아짐(PPI++ λ 조정) | TRIAL | `reference_impl/ppi.py`: 사람 수용 라벨(WVI의 accepted 성분)에만 사용. 안전 지표 금지. 라벨 최소 Tier A 80, Tier B 300 | CR-72 · PERF `PPI.*` |
| 2601.20251 | FAQ: Efficient Evaluation with Statistical Guarantees (2026-01-28) | B | 유효 표본 최대 5배 | TRIAL(미구현) | 다음 버전에서 능동 질의 선택 검토. 지금은 무작위 라벨 표본만 | — |
| SWE-bench Pro 공개 자료 | Scale 보드·집계 자료(2026-09 열람) | D | 공급사 자체 scaffold 점수가 Scale 표준 scaffold보다 10–30점 높음. mini-swe-agent에서 git 이력 악용 21%(100과제) | ADOPT | 평가 샌드박스에서 base 이후 git 이력·reflog·remote 제거, 모든 점수에 scaffold 동시 표기, 공개 문구에 공급사 scaffold 점수 인용 금지(QG.eval_hygiene) | CR-74 |
| 2609.40169 | ScholarEvolve(v4.0에서 반영) | B | — | 유지 | p.38 연구 루프 | 기존 |

### 2.6 하네스 자기 개선(M6)

| ID | 제목(제출일) | 등급 | 논문 보고치 | 고리 | EvoForge 반영 | 수용 테스트 |
|---|---|---|---|---|---|---|
| GEPA | Reflective Prompt Evolution (ICLR 2026) | A | 반성적 프롬프트 진화가 RL보다 적은 rollout으로 우수 | ADOPT | M6 최적화기 기준선. 새 최적화기는 GEPA를 이겨야 채택 | CR-76 |
| 2608.23041 | AutoSaddler (2026-08-24) | A- | 구조화 패치 + EvoDAG + dev 선택 + test 1회로 SWE-bench Pro 37.3 → 46.9(본문 +8.4pp와 표 불일치), GEPA·Meta-Harness 대비 +4.4~7.4pp | ADOPT(M6) | 패치 형식 (file, anchor, op), dev 세트로만 선택, 봉인 test 1회, 테스트 피드백으로 하네스 수정 금지(QG.optimizer) | CR-76 |
| 2609.24972 | RRSI (2026-09-21) | B | 편집 예산 annealing + critic + pruner로 OOD +4.3점, 정책 토큰 −30% | ADOPT(M6) | 세대별 편집 예산 120 → 20줄 선형 감소, 벤치마크 특화 제안 critic 차단 | CR-76 |
| 2609.37834 | Mixture of Self-Improving Branches (2026-09-29) | B | Meta-Harness 대비 Terminal-Bench 2 +11.6%, SWE-bench Lite +3.8% | ASSESS | 분기별 하네스 + 라우터는 M6 이후 검토 | — |
| 2610.22791 | Self-HPO (2026-10-16) | C(우리 기준) | 하네스 + 정책 RL 공동 최적화, 57.8 → 64.8% | HOLD | 정책(모델) 학습이 필요. 플랫폼 키로 상용 모델을 쓰는 구조와 맞지 않음 | — |

### 2.7 보안

| ID | 제목(제출일) | 등급 | 논문 보고치 | 고리 | EvoForge 반영 | 수용 테스트 |
|---|---|---|---|---|---|---|
| 2601.17548 | Prompt Injection on Agentic Coding Assistants, SoK (2026-01-24) | A- | 78개 연구 종합, 적응형 공격이 최신 방어를 85% 넘게 통과, 방어 18종 대부분 절반 미만 차단 | ADOPT | 필터가 아니라 구조로 방어: 신뢰 등급 분리(S2), 계획을 신뢰 컨텍스트에서 먼저 확정하고 비신뢰 데이터는 값으로만 흐르게(CaMeL 계열, 2503.18813), 부작용은 정책 엔진 + 인간 확인. p.45 | CR-11 · p.45 R45 |
| 2503.18813 | CaMeL (2025-03) | A- | 제어 흐름/데이터 흐름 분리로 증명 가능한 보안 일부 확보 | ADOPT(원칙) | 위와 같음 | — |

## 3. 수용 테스트 신규 ID (CR-59 ~ CR-76)

정의와 실행 근거는 `contracts/Acceptance_Test_Matrix.md` §D에 있다. 요약:

| ID | 내용 | 근거 |
|---|---|---|
| CR-59 | 분할 판정(허브 격리, 응집도·예상 속도 미달 시 SINGLE, 결정적) | PERF |
| CR-60 | 결합 실행 간섭 차단과 원인 쌍 특정 | C-17, PERF |
| CR-61 | 동시 변경 통지(참조자에게만, 추가는 통지 안 함) | PERF |
| CR-62 | 오라클 강도 게이트 | C-16, PERF |
| CR-63 | 보상 해킹 3종 탐지 | C-16, PERF |
| CR-64 | held-out 구성(합성·부정 필수) | PERF |
| CR-65 | 선택(증거 우선·하드 필터·동점 토너먼트·adaptive k) | PERF |
| CR-66 | HIGH/CRITICAL 독립성(자격·컨텍스트 독립·명세 선행·반례 피드백) | C-18, C-19, PERF |
| CR-67 | 차단 리뷰 증거 필수, advisory 상한 | C-19, PERF |
| CR-68 | 리뷰어 SNR 자격 | QG |
| CR-69 | 캐시 배치 S11 | VAL |
| CR-70 | 투기 실행(읽기 전용, 거짓 수락 0) | PERF |
| CR-71 | 보정 cascade(오류 상한, 금지 역할·위험) | PERF |
| CR-72 | PPI(허용 지표·최소 라벨) | PERF |
| CR-73 | 기억 정책(적재·회상·퇴출·삭제) | PERF |
| CR-74 | 평가 위생(git 이력 제거, scaffold 표기) | v4.2: V42 `Hygiene.*`(실제 git), 러너 통합은 M0 |
| CR-75 | 압축 경계 평가 | v4.2: V42 `CompactionEval.*`, 실제 수집은 M3 |
| CR-76 | 하네스 최적화 규칙(GEPA 기준선, dev 선택, test 1회, 편집 예산) | v4.2: V42 `Optimizer.*` + `harness-patch.v1`, 실제 루프는 M6 |

## 4. 기대 효과를 어떻게 다루는가

v4.1의 성능 기법은 세 종류로 나뉜다. 측정 방법이 서로 다르다.

| 종류 | 기법 | 켜는 조건 | 측정 |
|---|---|---|---|
| 안전·무결성 | GH_INTEGRITY, GC_COMPOSITION, 독립성, 리뷰 증거, S11, 평가 위생 | 즉시(ADOPT). 품질을 올리는 게 아니라 거짓 성공을 막는다 | 회귀 유출·critical miss 0 유지, 오차단율 ≤ 10% |
| 품질 | 다면 재현 테스트, 증거 기반 선택, 토너먼트, adaptive k, 기억 | Tier A → 카나리, Tier B → 기본값 | verified_fix_rate 비열등성(δ 5pp/2pp) + 우월성 별도 판정 |
| 속도·비용 | 분할, 투기 실행, cascade, ReFold, PPI(평가 비용) | 같음 + 비용 상한 ≤ 1.0 | WVI/주 비율 하한(p.10 사다리), 비용 비율 상한 |

예상 이득은 쓰지 않는다. 논문 수치를 그대로 더하면(예: 분할 2.1배 × 투기 1.3배) 2.7배가 나오지만, 서로 다른 과제·모델에서 나온 최대값이고 같은 병목(테스트 실행 대기)을 함께 줄이므로 겹친다. M2 사다리 1.5배는 이 기법 없이도 목표였고, v4.1 기법은 M5 3.0배 하한을 맞출 수단이다. 판정은 실측 하한으로만 한다.

## 5. 재검토 주기

분기마다(다음 2027-01) 다시 조사한다. ASSESS 항목은 (1) 코드 공개 (2) 우리와 같은 상용 모델 설정 재현 (3) 비용 수치 공개 중 둘 이상이 충족되면 TRIAL로 올린다. TRIAL 항목이 Tier A를 두 번 연속 통과하지 못하면 ASSESS로 내린다.

## 출처

- arXiv: [2606.00953](https://arxiv.org/abs/2606.00953) · [2609.25396](https://arxiv.org/abs/2609.25396) · [2602.16873](https://arxiv.org/abs/2602.16873) · [2601.12307](https://arxiv.org/abs/2601.12307) · [2607.11250](https://arxiv.org/abs/2607.11250) · [2606.03115](https://arxiv.org/abs/2606.03115) · [2607.00990](https://arxiv.org/abs/2607.00990) · [2604.16529](https://arxiv.org/abs/2604.16529) · [2610.00972](https://arxiv.org/abs/2610.00972) · [2610.28667](https://arxiv.org/abs/2610.28667) · [2603.11078](https://arxiv.org/abs/2603.11078) · [2606.18168](https://arxiv.org/abs/2606.18168) · [2605.21384](https://arxiv.org/abs/2605.21384) · [2610.10947](https://arxiv.org/abs/2610.10947) · [2603.03329](https://arxiv.org/abs/2603.03329) · [2601.06007](https://arxiv.org/abs/2601.06007) · [2610.07863](https://arxiv.org/abs/2610.07863) · [2608.06503](https://arxiv.org/abs/2608.06503) · [2512.22087](https://arxiv.org/abs/2512.22087) · [2607.23809](https://arxiv.org/abs/2607.23809) · [2610.27377](https://arxiv.org/abs/2610.27377) · [2609.38201](https://arxiv.org/abs/2609.38201) · [2605.18796](https://arxiv.org/abs/2605.18796) · [2604.07494](https://arxiv.org/abs/2604.07494) · [2301.09633](https://arxiv.org/abs/2301.09633) · [2601.20251](https://arxiv.org/abs/2601.20251) · [2608.23041](https://arxiv.org/abs/2608.23041) · [2609.24972](https://arxiv.org/abs/2609.24972) · [2609.37834](https://arxiv.org/abs/2609.37834) · [2610.22791](https://arxiv.org/abs/2610.22791) · [2601.17548](https://arxiv.org/abs/2601.17548) · [2503.18813](https://arxiv.org/abs/2503.18813)
- SWE-bench Pro: [Scale SWE-bench Pro V2](https://labs.scale.com/blog/swe-bench-pro-v2) · [benchlm 집계](https://benchlm.ai/benchmarks/scale-swe-bench-pro-public-v2-full)
- GEPA: [ICLR 2026 발표](https://slideslive.com/39062118/gepa-reflective-prompt-evolution-can-outperform-reinforcement-learning)
