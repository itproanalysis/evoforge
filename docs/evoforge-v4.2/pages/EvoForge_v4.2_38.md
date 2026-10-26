<!-- PAGE:38/50 -->

# 38. Champion–Challenger와 하네스 진화

> **목적:** 제품 개선과 에이전트 하네스 개선을 같은 통계 규칙으로, 그러나 분리해서 운영한다. · **결정:** D-011, D-012, D-013, D-014, D-016, D-035, D-051, D-057 · **계약:** `contracts/quality_gates.json`

### 두 층
**Product Evolution**은 고객 코드 개선(Candidate 경쟁)이고, **Harness Evolution**은 EvoForge의 작업 배분·프롬프트·컨텍스트·재시도 정책 개선이다. 두 층을 같은 평가로 섞지 않는다. 하네스 진화는 **M6**에서 연다(이유: 충분한 실행 trace와 봉인 평가 인프라가 먼저 있어야 한다).

### Product Champion–Challenger
현재 코드를 Champion으로 두고 Challenger를 만든다. Challenger 수는 1에서 시작하고 adaptive k 규칙(p.16, p.35)으로만 늘린다. 필수 게이트(`GH_INTEGRITY` 포함) 통과 후보만 비교하고, 비교는 실행 증거 우선 선택 규칙(D-045)을 따른다. Critic이 검증 가능한 결함으로 실패를 예측하면 조기 종료한다. 합격 후보가 없으면 현재를 유지한다. 예산: `max_candidates`, `max_rounds`, 크레딧 상한, `deadline`. 개선이 정체되면 멈춘다.

### Harness(M6)
- `H = Compose(T, C, S, M, W)` — Tool Interface, Context Management, Skills, Memory, Agent Workflow. 각 모듈은 `variant_id`, 계약 버전, 해시, 권한 선언을 가진 불변 아티팩트다. 보호 정책·검증기·과금기는 모듈이 아니며 바꿀 수 없다.
- 파이프라인: `FailureAudit → CapabilityGap → ResearchQuery → PaperCluster(방법론 다양성) → MutationBlueprint → ContractCheck(→ VALIDATION_ELIGIBLE) → D_val 단일 모듈 평가 → 상위 소수 조합 전체 평가 → D_test → 승격 요청`.
- 승격: `immutable champion snapshot → 같은 D_val 비교 → 보안·계약·비용 게이트 → 관리자 승인(고위험은 2인) → Tier A Canary → 신규 Run에만 적용 → 관측 → Tier B면 기본값 / 아니면 롤백`. 진행 중 Run은 시작 시 고정한 `harness_version`을 유지한다.
- Context 모듈의 압축기 변경은 `compressor_registry_version`, `preservation_policy_hash`, `recovery_codec_version`을 갖고, 압축률만 최대화할 수 없다(원문 보존·품질·ACL을 함께 평가).
- **최적화기 규칙(D-051).** 기준선은 GEPA(반성적 프롬프트 진화, ICLR 2026)다. 새 최적화기는 같은 예산에서 GEPA를 이겨야 채택한다. 변이는 구조화 패치 `(file, anchor, op)`로만 만들고(자유 재작성 금지), 패치는 미니배치 점수를 올릴 때만 후보가 되며, 최종 선택은 `D_val`(dev) 점수로만 한다. `D_test`는 1회만 쓰고 그 결과로 하네스를 고치지 않는다(2608.23041 AutoSaddler 방식). 한 세대가 묶을 수 있는 편집량은 120줄에서 20줄로 세대에 따라 줄이고, 벤치마크 특화 제안은 critic이, 너무 작거나 비싸거나 쓸모없어진 변경은 pruner가 제거한다(2609.24972 RRSI: 분포 밖 +4.3점, 정책 토큰 −30%). 하네스와 정책 모델을 RL로 함께 최적화하는 방식(2610.22791)은 플랫폼 키 상용 모델 구조와 맞지 않아 HOLD.
- **실행 규율(D-057).** 최적화 실행은 상태 머신이다: `OPEN`(패치 제안·미니배치·dev 평가) → `FROZEN`(dev 1위 후보만, GEPA 대비 dev 쌍별 우월성 단측 95% 하한 > 0일 때) → `CLOSED`(`D_test` 1회). FROZEN 이후 새 패치는 거부되고, 동결 후보가 아니면 `D_test`를 열 수 없으며, 두 번째 test 평가는 거부된다. 변이 단위는 `contracts/schemas/harness-patch.v1.schema.json`이다: 연산은 insert_after/insert_before/replace/delete/create 5종(자유 재작성 불가), 경로에 `..` 금지, EvoDAG 부모 1~4개, `evaluated_on`에 test를 적을 수 없다. Trust Kernel 경로(policy·verifiers·billing·eval_data·gates)를 건드리는 패치, 없는 anchor·중복 anchor, 세대별 편집 예산 초과는 `harness_optimizer.check_patch`가 거부한다.
- 하네스에 도구 호출 전 결정적 행동 검증기를 둔다(스키마·경로·권한). 2603.03329에서 합성 검증기가 불법 행동을 0으로 만들고 작은 모델이 큰 모델을 이겼다. 검증기 자체는 Trust Kernel 쪽이며 진화 대상이 아니다.
- `research_mode = OFF | SUGGEST | EVALUATE | CANARY`, 기본 OFF. 외부 논문 코드 자동 설치·무승인 운영 반영은 없다. ScholarEvolve(arXiv:2609.40169) 등 외부 연구의 수치는 해당 논문의 실험 결과일 뿐 EvoForge의 승격 기준이 아니다. 사전 예측과 실제 결과의 오차를 장기 지표로 쌓는다.

### 지식 축적
성공·실패 실험의 `(task fingerprint, method, result, context cost, regression)`을 저장해 유사 과제에 재추천한다. 고객 코드를 모델 학습에 쓰는 것은 별도 동의 없이는 하지 않는다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R38-1 | 빠르지만 틀린 후보 | 테스트 실패 Challenger 승격 0건, 판단 근거가 실험 기록으로 설명됨 |
| R38-2 | 하네스 승격 통계 | Tier A 미통과 하네스의 Canary 진입 0, Tier B 미통과의 기본값 승격 0 |
| R38-3 | 버전 고정 | 승격 중 진행 Run의 하네스 버전 변경 0건 |
| R38-4 | 최적화 규율 | 선택에 `D_test` 사용 0건, `D_test` 2회 이상 사용 0건, 편집 예산 초과 변이 0건, GEPA 기준선 비교 없는 채택 0건 (CR-76) |

---
