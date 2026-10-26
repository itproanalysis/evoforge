<!-- PAGE:40/50 -->

# 40. 상태·기억·스냅샷·복구

> **목적:** 무엇을 기억하고, 언제 꺼내 보여주며, 장애 뒤에 어떻게 중복 없이 이어가는지 정한다. · **결정:** D-005, D-030, D-033, D-052 · **계약:** `contracts/sql/core_DRAFT.sql`, `contracts/sql/context_plane_DRAFT.sql`

### 저장 상태
`RunState`, `AgentPresence`, `TaskLease`, `ObjectiveVersion`, `MessageCursor`, `Candidate SHA`, `CIStatus`, `ProviderUsage`, `ReviewDecision`, `FeedbackLink`. 재실행 가능한 단위로 나누고, 스냅샷은 이벤트 로그의 재구성 지점을 표시한다. 외부 모델의 숨은 내부 상태는 옮길 수 없으므로, 재개는 **API 중립 작업 스냅샷**으로 한다.

### 기억 저장소(정본 4종; Prompt 레이어와 다른 개념)
| 저장소 | 내용 | 승격 조건 |
|---|---|---|
| `M-CONTRACT` | 목표·권한·안전 정책·Acceptance | 사람이 승인한 버전만 유효 |
| `M-EVIDENCE` | 출처 있는 관측 사실, 시도 에피소드, 실패/성공 증거, 원본 SHA, 테스트 지표, 원문 ref | 원문·출처·시점·테넌트·신뢰도 필수 |
| `M-GRAPH` | Goal ↔ Task ↔ Code ↔ Outcome 관계 | 이벤트 ID로만 간선 생성 |
| `M-PLAYBOOK` | 검증된 재사용 접근법·Skill | 검증 근거 + 승인자. `bad_pattern`은 자동 지시로 승격 금지 |
내용이 충돌하면 원본이 이긴다. 고객 기록의 자동 전사·다른 테넌트 전이는 금지한다. 삭제 요청은 인덱스·파생 요약·임베딩까지 추적한다(p.46).

### 경험 기억의 회상(TRIAL)
저장보다 **언제 보여줄지**가 성능을 가른다. 2610.27377(REM)에서 요약이나 원 trajectory를 통째로 넣는 것은 정답 회상이어도 효과가 없었고, 단계 구조 + 게이트 회상 + 1회 노출 후 퇴출이 해결률을 올리고 비용을 17% 줄였다. EvoForge 규칙(`reference_impl/memory_policy.py`):
- 적재: `M-PLAYBOOK`/`M-EVIDENCE`의 교훈은 Verified Improvement에서만 만든다. 자기보고·실패 미검증 trace는 적재하지 않는다.
- 구조: 단계(`localize`, `reproduce`, `fix`, `verify`)별 문서, 출처 Run ID 보존.
- 회상: 같은 테넌트·같은 단계·태그 Jaccard ≥ 0.3인 것만, 최대 3개. 과제당 1회 노출 후 그 과제에서는 퇴출한다.
- 삭제: 출처 Run을 crypto-shred하면 파생 교훈도 함께 지운다.

### 복구 절차
워커 장애 감지 → Lease TTL 만료 → 진행 중 외부 호출의 결과·과금 여부 조회 → 이전 커밋·아티팩트 참조 재검증 → 재배정(새 epoch) → 같은 명령의 중복 실행 방지. 결과가 불명확한 `provider.call`, `github.create_pr`, `github.merge`, `billing.charge`는 `UNKNOWN_EXTERNAL_OUTCOME`으로 두고 조회 API로 확인한 뒤에만 진행한다. 이미 PR이 생겼으면 새로 만들지 않고 기존 ID로 상태를 수렴시킨다. `pause`(결과 보존) · `cancel`(신규 실행 차단) · `rollback`(독립 작업)은 서로 다른 이벤트다. 하네스 상태는 `HarnessVersionManifest`(5개 variant_id, config hash, tool scope, skill/memory 인덱스 버전, 평가 manifest SHA, 빌드 커밋, 승인 이벤트)로 고정한다.

### 보존
대형 로그는 암호화 Object Storage에 두고 content hash로 참조한다. 보존 기간·삭제는 플랜·법적 의무·계약에 맞춘다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R40-1 | 장애 시뮬레이션 | API 타임아웃, A2A 끊김, 폴더 중복 작성, 워커 SIGKILL, GitHub 웹훅 중복, DB failover, 정지 중 `CANCEL`에서 상태·비용·병합 불일치 0 |
| R40-2 | 미완료 표시 | 복구 후 미완료 단계가 사용자에게 명확히 표시 |
| R40-3 | 불명확 결과 | UNKNOWN 상태에서 조회 없는 재시도 0 (C-12) |
| R40-4 | 기억 회상 | 미검증 교훈 적재 0, 다른 테넌트·다른 단계 회상 0, 과제당 같은 교훈 2회 노출 0, 출처 삭제 후 잔존 0 (CR-73) |

---
