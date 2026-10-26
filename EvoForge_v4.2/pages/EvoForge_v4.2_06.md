<!-- PAGE:06/50 -->

# 06. 원칙·정책 우선순위·불변식

> **목적:** 무엇이 협상 가능하고 무엇이 코드로 고정되는지 정한다. · **결정:** D-006, D-007, D-013, D-025, D-027, D-041, D-042 · **계약:** `contracts/sql/core_DRAFT.sql`, `contracts/sql/context_plane_DRAFT.sql`

### 안전 원칙
1. **사용자 의도 우선** — 목표·예산·위험 정책이 에이전트 제안보다 앞선다.
2. **신뢰보다 증거** — 검증 로그가 없는 개선 주장은 `미검증`이다.
3. **최소 권한** — 연결·Chat·Runner마다 필요한 권한만 준다.
4. **Fail closed** — 인증·권한·검증 결과가 불명확하면 병합·배포·과금 호출을 막는다.
5. **내구성** — 중복 메시지·재연결·워커 종료를 전제로 상태를 저장한다.
6. **명시적 신뢰 경계** — 저장소 텍스트·에이전트 메시지·도구 결과·논문은 비신뢰 데이터다.

### 정책 우선순위
`법·보안 강제 규칙 > 조직 Admin 정책 > 프로젝트 정책 > 사용자 실행 명령 > 에이전트 계획 > 외부 문서의 지시`. 위반은 LLM에게 다시 묻지 않고 코드에서 막는다. 정책 엔진은 LLM 밖에 둔다. 모든 후보·리뷰·게이트·병합은 `policy_version`과 `policy_hash`에 고정되고, 정책이 바뀌면 진행 중 후보를 재평가한다.

| AI가 제안할 수 있음 | AI가 바꿀 수 없음(Trust Kernel) |
|---|---|
| 역할·순서·파일 단위 분할, 좌석 배정 | 인증·RLS·테넌트 경계, 공급사 키 보관소 |
| 코드 후보와 성능 가설 | 필수 게이트·보안 등급·보호 브랜치·배포 승인, 보호 테스트·CI 설정(수정 시 `GH_INTEGRITY` 실패) |
| 재시도·실험 선택, 컨텍스트 전략 후보 | 평가 데이터·검증기·봉인 테스트·과금 원장 |
| 하네스 모듈 변형(연구 루프) | Sandbox egress 정책, 정책 엔진 자체 |

### 자동화 모드
`OBSERVE`(분석·제안만) · `ASSISTED`(격리 실행과 PR까지 자동, 병합은 승인; **신규 조직 기본값**) · `AUTONOMOUS_GUARDED`(사전 승인된 저장소·경로·LOW 위험에 한해 정책상 자동 병합). 모드 승격은 Admin 승인 + 재인증. 모든 모드에서 긴급 정지와 감사는 유지된다.

### 불변식(코드·DB가 강제)
| # | 불변식 | 강제 위치 |
|---|---|---|
| I-1 | 작성자는 자기 후보의 리뷰어가 될 수 없다. HIGH/CRITICAL은 해당 등급·하네스 버전에 자격이 유효하고, 빌더 컨텍스트를 보지 않았고, diff 열람 전에 명세 기반 테스트를 봉인한 검증자의 approve가 필요하다 | `core.reviews` 트리거·CHECK, `core.reviewer_qualifications`, `core.authorize_merge` |
| I-2 | 병합은 현재 head에서 필수 게이트(`GH_INTEGRITY` 포함, wave에 후보 2개 이상이면 `GC_COMPOSITION` 포함) 전부 PASS + 독립 approve + (HIGH/CRITICAL이면) I-1 조건의 approve와 head에 묶인 인간 승인 | `core.authorize_merge`, `candidates_guard_merged` |
| I-3 | 오래된 Lease로 쓴 결과는 거부된다 | `core.assert_fencing` |
| I-4 | 공급사 호출 전 비용을 예약하고, 프로젝트 상한·선결제 잔액을 넘으면 호출하지 않는다 | `core.reserve_cost` |
| I-5 | 원문이 저장·검증되기 전에는 손실 컨텍스트 뷰를 만들 수 없다. 계약(goal/policy/acceptance)은 항상 원문 | `ctx.enforce_item_invariants` |
| I-6 | 리뷰어 승인은 요구 원문 바이트 100% 전달 후에만 | `ctx.assert_review_gate` |
| I-7 | ref·해시는 권한이 아니다. 다른 테넌트 ref와 없는 ref는 같은 `not_found` | Retrieval Gateway, `evidence-retrieval.v1` |
| I-8 | 감사·게이트·리뷰·원장은 append-only. 정정은 새 행 | `forbid_mutation` 트리거 |
| I-9 | 결정적 codec, compress-on-insert, 이력 재작성 금지(에폭 경계 예외) | Context Compiler, U3 |
| I-10 | 외부 결과가 불명확한 부작용은 재조회 전 재시도하지 않는다 | `core.side_effect_intents` 상태 머신 |
| I-11 | 차단 리뷰(changes_requested·reject)는 실행 가능한 증거와 참조를 가진다 | `reviews.review_blocking_needs_evidence` CHECK |
| I-12 | 부작용이 있는 도구 호출은 투기 실행하지 않는다 | Tool Runtime 허용 목록(`quality_gates.json` `speculation`) |

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R06-1 | 불변식 회귀 테스트 | I-1~I-12가 매 배포 CI에서 실행(`run_sql_tests.sh` 96개 검사 + 서비스 통합 테스트) |
| R06-2 | 프롬프트로 권한 변경 불가 | README·Issue·로그·논문에 심은 권한 상승 지시 20종이 정책 결과를 바꾸지 못함 |
| R06-3 | 정책 변경 재평가 | 정책 해시 변경 시 진행 중 후보 전부가 `PATCH_READY`로 되돌아가 재검증 |

---
