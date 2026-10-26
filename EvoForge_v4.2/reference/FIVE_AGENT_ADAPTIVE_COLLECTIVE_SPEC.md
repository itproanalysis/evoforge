# EvoForge v3.4 — Five-Agent Adaptive Collective & Bottleneck-Free-by-Design

> **상태:** 상용 서비스 설계 · 구현 전 · 실제 10배 성능 향상 미검증. 2026-10-23.

## A. 10X 가설과 물리적 한계

동일한 연산량을 5개의 동일 작업자로 나누기만 하면 최고 가속비는 5배이며, 실제 소프트웨어 작업은 순차 의존·협의·검증·통합이 있어 더 낮다. Amdahl 모델 `S(N) = 1 / (f + (1-f)/N)`; 직렬 비중 `f=0.10`, `N=5`이면 약 3.57배다. 따라서 10배는 순수한 '시간 가속' 약속이 될 수 없다. **쓸모 없는 재작업 제거, 낮은 비용의 검증 조기 필터, 높은 품질의 가설 선정, 파이프라이닝, 중요 작업 우선 배치**에 의해 `유효 성과/시간` 지표가 10배 달성될 수 있는지 별도로 실증한다.

**North Star:** `Verified Impact per Week` = 사전에 합의한 사용자가 수용한 개선의 검증 점수 합계 / 경과 주. 반드시 `Verified PR/week`와 `Cost/Verified PR`, `p95 Time to Verified PR`, `Regression escaped`, `User intervention min`을 함께 표시. 품질이 나빠지면 10X 실패.

**명백히 가상인 예:** 단일 AI에서 주당 2건, 동일 프로젝트·동일 합격 기준의 5-Agent 팀이 주당 20건의 검증 수용 개선을 제공한다면 검증 생산성이 10배. 이는 **목표를 설명하기 위한 예시**로, 아직 실험 자료가 없다. 비용이 5배 상승했으면 비용당 생산성 개선은 2배일 수 있다. 사용시간/비용 공정 실험을 분리해야 한다.

## B. 다섯 개의 AI를 고정 부서가 아닌 스킬 기반 좌석으로 관리

| 논리 좌석 | 기본 선호 업무 | 단계 전환 시 수행 가능한 업무 | 격리/불변식 |
|---|---|---|---|
| Agent 1 / Navigator | Objective → DAG, 위험 평가, 인수 조건 | 목표 평가, 작업 분해, 필요한 경우 리뷰 아닌 구현 | 모든 실행마다 Director 호출 금지; Artifact Manifest 공유 |
| Agent 2 / Builder Alpha | 독립 구현/코드 후보 A | 빠른 버그 수정, 성능 최적화 | Worktree와 Lease 분리 |
| Agent 3 / Builder Beta | 병렬 구현/코드 후보 B | 테스트 코드, 리팩터, 기능 개발 | 변경 파일 충돌 시 분할·직렬화 |
| Agent 4 / Critic | 코드 리뷰, 악성/회귀 사례 탐색, 테스트 계획 | 증거/리스크 분석 | 자기가 작성한 후보의 독립 리뷰 금지 |
| Agent 5 / Integrator | 통합 계획, Benchmarks, 고객 피드백 재연결 | 구현, 연구, 비작성자 리뷰 | 최신 Base SHA/보호 브랜치 검증; Merge는 정책 엔진 |

이 표는 초기 선호일 뿐. 실제 역할은 `Capability Probe + task fitness + history + data permission + budget + availability`로 매 Task 재선정. 최대 5 AI가 팀에 참가하며 외부 API/AI Chat/원격 A2A 모두 참여 가능. 실시간 응답이 없는 AI Chat은 예약하되 임계경로 작업에 장시간 대기시키지 않음. 대체 API는 고객이 사전에 허락한 Provider에 한정.

## C. Five-Agent Adaptive Collaboration Modes

- **SINGLE (소규모 작업):** 1 AI 구현, 1 AI 독립 검토, 나머지 다른 작업/유휴. 필요 없는 AI 호출 금지.
- **RACE (불확실성 높은 변경):** 1 Planner가 brief 생성 후 2~3 Builder에 독립 구현 할당, 1 Critic + 1 Integrator/Benchmark가 검증. 동일 파일이면 서로 다른 Worktree·독립 시험 후 단일 후보 채택, 후보 간 섞어 병합하지 않음.
- **DAG_PARALLEL (분리 가능 작업):** 기능/API/문서/테스트 등 예상 Write Set으로 DAG 나누고 최대 3 Builder 병렬. Planner/Integrator는 이후 임계경로 작업 보조. Reviewer는 비작성자.
- **PIPELINE (지속적 개선):** Discovery/Plan → Build → Review → CI → Integrate가 겹치도록 실행. 현재 후보가 검증 중일 때 다음 독립 과제를 준비하되 Runner 포화 시 upstream stop.
- **HIGH_RISK:** 구현 한 명, 회귀/보안 독립 리뷰 두 명, 별도 테스트, 인간 승인 요구. 10배 속도보다 위험 억제 우선.

**Topology 선택 프로세스:**
1. `Task Analyzer`가 작업 난도, 파일 충돌 가능성, DAG 분리성, 변경 위험, 예상 테스트 시간과 도구 수를 계산.
2. `Candidate Estimator`가 Single 기준 예상 성공률/소요시간/비용을 추정(샘플 부족 시 넓은 불확실성/휴리스틱).
3. `Topology Selector`가 비용·예산·정책을 만족하는 모드 중 예상 Verified Gain이 높은 모드를 선택. AI가 자유로운 역할 협의를 하되 최대 1회 제안 + 1회 이의 제기로 종료.
4. `Admission Controller`는 공급사 RPM/TPM, 고객 예산, Runner/CI 용량, 파일 Lease/critical path를 점검하여 실행.
5. 단계별 Trace 결과가 다음 선택에 반영. 안정성이 입증된 뒤 contextual bandit 실험 가능하며 모델 배정 자체가 보안정책을 바꾸지는 않음.

## D. 임계경로 기반 스케줄러와 백프레셔

`ready_tasks = dependency_satisfied ∩ budget_authorized ∩ lease_safe ∩ provider_available`

각 ready task의 평가:

`priority(task) = user_urgency + critical_path_remaining_value + unblock_count_bonus + expected_verified_impact - collision_penalty - runner_backlog_penalty - API_cost_penalty`

선정 뒤 `atomic claim`과 `lease_epoch` 부여; 작성 상태 분산을 위한 파일·디렉터리 수준 예약; 갱신 실패 시 stale 결과 거부. Planner는 매 호출에 필요하지 않고 DAG/결정 근거를 캐시한 뒤 이벤트로 재계획한다.

검증 큐 장기 증가 시:
- 1순위: `RACE` 신규 후보 수 감소, 인접 중복 실험 제거
- 2순위: G0/G1로 빠른 실패 선별, 무거운 G2/G3 예약
- 3순위: 검증 전용 Runner 확장(예산·테넌트 SLA 검토)
- 4순위: 사용자에게 병목 및 예상 지연 명시

Provider 429/5xx 시: 공급사별 독립 큐, 토큰 버킷, Retry-After / Jitter, Circuit Breaker; 모델 대체 전 조직 Consent 검증. 모든 API 호출은 cancellable에서만 실제 취소 완료를 보고. 비활성 Chat 세션이 전체 작업을 멈추지 않도록 deadline+fallback.

## E. 리뷰·검증·병합의 정확성

`Candidate → G0 policy/secret/lint → G1 impacted tests → G2 required CI/security/full regression → G3 benchmark for performance goals → G4 latest merge-head checks → PR/Merge`

- `G0/G1` 실패만 조기 탈락; 브랜치 필수 테스트와 정책 게이트 우회 금지.
- 독립 코드 리뷰 모델은 patch author와 달라야 하며, 검증 스크립트·QA policy·보안 정책은 AI에게 비인가 수정 불가.
- benchmark는 동일 머신·부하·Warmup·데이터와 ABBA 또는 합리적 교차 반복으로 측정. 분산까지 보고.
- GitHub Merge Queue 사용 가능 시 `merge_group` 필수 checks; 없으면 latest SHA/CODEOWNERS/protection을 재확인하고 검증 후 병합.
- CI의 1차 통과를 '검증된 개선'으로 집계하지 않는다. 사전에 설정한 합격 기준과 고객 승인·수용까지 추적.

## F. 아티팩트 기반 커뮤니케이션 및 메모리

모델 간 메시지 표준: `{task_id, objective_version, intent, brief, artifact_uri, artifact_sha, base_sha, acceptance, deadline, sender, receiver, response_mode}`. 워크트리 diff·빌드 로그·테스트 보고서·계획/쟁점은 오브젝트 스토리지에 저장하고 짧은 참조와 판단만 메시지 버스에 게시한다. 캐시 재사용은 공급사별 권한 범위 안에서만 수행; 서로 다른 모델 사이에 내부 KV 전송 불가능. 액티브 작업은 최근 diff·필수 맥락만, 이전 완료작업은 구조화된 Lessons로 제공.

**Context minimization:** 1) 정책·프로젝트 불변 Prefix, 2) 변동 적은 공유 Task Brief, 3) 최신 실제 Diff/실험 결과. 벤더별 prompt cache available일 때 이용. 각 Provider에 보낼 파일 범위·민감성은 `DataAccessEnvelope`로 통제.

## G. 5-Agent 협업의 이벤트 모델

- `TEAM_CREATED`, `AGENT_ELIGIBLE`, `TOPOLOGY_PROPOSED`, `TOPOLOGY_SELECTED`
- `ROLE_BID_SUBMITTED`, `ROLE_ASSIGNED`, `ROLE_REASSIGNED`
- `TASK_READY`, `TASK_CLAIMED`, `WORKTREE_PREPARED`, `ARTIFACT_SUBMITTED`
- `BACKPRESSURE_APPLIED`, `BOTTLENECK_DETECTED`, `AGENT_TIMED_OUT`
- `GATE_PASSED`, `CANDIDATE_REJECTED`, `MERGE_QUEUED`, `MERGE_CONFIRMED`
- `VERIFIED_IMPACT_RECORDED`, `USER_FEEDBACK_LINKED`

모든 이벤트는 tenant-scoped `run_id`, `trace_id`, `causation_id`, `policy_version`, `plan_epoch`와 `actor` 포함; 중복 메시지를 멱등 처리. Mission Control은 snapshot+cursor로 상태를 복구하며 AI 토큰 로그를 전체 UI에 브로드캐스트하지 않음.

## H. 지표·수용 기준

| 지표 | 우선 방향 | 측정 대상 |
|---|---|---|
| `verified_pr_per_week` | 최대화 | 단일 AI vs 5-Agent |
| `weighted_verified_impact_per_week` | 최대화 | 고객 합의 목적 가중치 |
| `cost_per_verified_pr` | 악화 억제 | BYOK 비용+Runner+CI 별도 표기 |
| `p95_time_to_verified_pr` | 최소화 | 입고~검증/고객 수용 완료 |
| `queue_wait_ms by lane` | 최소화 | API, Build, Review, CI, Merge |
| `rework_ratio` | 최소화 | 수정 재시도/전체 후보 |
| `reject_bad_patch_rate` | 극대화 | 알려진 결함 패치 차단 실험 |
| `unauthorized_merge_count` | 0 목표 | 안전 불변식 |
| `human_command_ack_p95` | 2초 이하 제안 | 실제 배포 성능 실측 후 SLO 확정 |

**실험군:** A 단일 AI, B 5AI 무계획 일괄 병렬, C 5AI Adaptive Topology, D C에서 Artifact Handoff 제거, E C에서 Backpressure 제거, F C에서 정책 기반 역할 동적배정을 고정 역할로 변경. 샘플수가 적으면 통계적 의미 없는 10배 결과를 주장하지 않는다. 같은 고정 작업 목록·동일 시작 커밋·기준 테스트·컨텍스트 접근 정책·모델 가격과 버전을 기록. 같은 비용 기준과 같은 시간 기준 결과를 **별도 보고**한다.

## I. 권장 제품 화면

**Mission Control 상단:** Verified Impact / week, Verification queue wait, P95 completion, Team slots 0~5, current topology, Provider incidents.

**Collective Map:** 5개의 모델 세션에 현재 역할·과제·이전 역할·왜 선택했는지·Queue 원인을 표시. Idle은 최적화된 가용성 상태임을 설명한다.

**Bottleneck Intelligence:** critical path, queue length trend, provider throttle, merge collision, CI saturation, cost per validated outcome. 'AI 5개를 동시에 돌려라' 대신 `추천: Builder B를 재검증 작업으로 재배정, 개선 예측과 오판 비용 표시` 제안.

**Feedback → Work:** 사용자가 `테스트를 먼저 강화해` 명령하면 Fast Lane ACK → 명령 영향 평가 → DAG 재계획 → 역할 협의 → 실제 적용 → 테스트/사용자 확인까지 연결.

## J. 참조 연구 및 상용 검증 기준

- Google Research (2026), *Towards a science of scaling agent systems*: https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/ — 작업 의존·도구 수와 협업 토폴로지의 관계.
- Anthropic Engineering (2025), *How we built our multi-agent research system*: https://www.anthropic.com/engineering/multi-agent-research-system — 3~5 병렬 연구자와 아티팩트 직접 저장, 높은 토큰 비용·코딩 병렬화 한계.
- Geng & Neubig (COLM 2026), *Effective Strategies for Asynchronous Software Engineering Agents*: https://proceedings.colm.cc/paper_files/paper/2026/hash/3b5c10bf5d70533e955cba9fba491bf4-Abstract-Conference.html — CAID, 작업 의존 DAG·격리 Worktree·Test 기반 통합.
- GitHub, *Managing a merge queue*: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue — 최신 브랜치 기준 CI 정책 및 merge_group.

**검증 전제:** 연구에서 보고한 수치와 이 문서의 10X 제품 목표는 별개다. 본 문서 내용은 설계·실험 프로토콜이며, 현재 고객 데이터와 실제 시스템에서 속도·생산성 10배가 입증된 상태가 아니다.
