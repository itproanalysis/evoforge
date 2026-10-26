<!-- PAGE:26/50 -->

# 26. Agent Registry·역량·신뢰 보정

> **목적:** 누가 어떤 일을 해도 되는지를 선언이 아니라 측정으로 정한다. · **결정:** D-003, D-020, D-024, D-041, D-044 · **계약:** `contracts/quality_gates.json`(`reviewer_qualification`)

### 엔티티
`AgentIdentity`(조직별 식별자; 주체 종류 = 고객 연결/원격 운영자/모델 인스턴스), `AgentConnection`, `CapabilityDeclaration`(자기선언), `CapabilityEvidence`(프로브·실과제 결과), `AuthorizationGrant`, `Presence`, `PerformanceProfile`. 사용자·연결 계정·A2A 서비스·MCP 클라이언트·모델 ID·런타임 실행 ID는 서로 다른 엔티티다. 같은 모델 ID를 여러 조직이 써도 권한·작업·로그는 공유하지 않는다.

### 역할 ≠ 권한
`critic`이라는 기능 역할은 "리뷰 의견을 쓸 수 있다"는 뜻이지 병합 승인권이 아니다. 기능 역할은 작업마다 바뀌고, 권한은 조직 정책과 토큰 scope로 집행한다. 권한 판단은 `subject + action + resource + tenant + context + policy_version` 계약으로 구현한다.

### 역량 프로필
- task-type별(`design`, `implement`, `tests`, `review`, `research`, `integration`, `benchmark`) 실제 검증 표본 수·최근성·난도 보정 성공률을 기록한다. 작은 표본에서 특정 모델을 자동 우대하지 않는다.
- 컨텍스트 관련 프로브: `supports_native_prompt_cache`, `supports_retrieve_evidence`, `max_safe_context_bytes`, `can_inspect_full_diff`, `can_review_sensitive_change`.
- **리뷰어 자격(정본 `quality_gates.json`):** 위험 등급별로 *모델 + 컨텍스트 프로필 + 하네스 버전* 조합을 하나의 리뷰어 구성으로 보고, seeded critical defect 100건 이상에서 검출률 Wilson 95% 하한 ≥ 0.90, 깨끗한 후보 100건 이상에서 오차단율 ≤ 10%, **판정된 지적 100건 이상에서 정밀도(실제 결함에 대응하는 지적 비율) Wilson 95% 하한 ≥ 0.40**일 때만 그 등급의 승인자 풀에 넣는다. 정밀도 하한은 recall을 잡음으로 사는 리뷰어를 걸러낸다(2603.11078: 일반 리뷰 에이전트 정밀도 3–5%, 반복 탐색은 SNR을 떨어뜨림). 모델 revision·하네스·컨텍스트 프로필이 바뀌면 재자격 시험을 한다.
- 자격 결과는 `core.reviewer_qualifications`(에이전트 × 위험 등급 × 하네스 버전, 만료일, 증거 해시)에 append-only로 기록되고, HIGH/CRITICAL 병합 시 `core.authorize_merge`가 직접 조회한다. 다른 하네스 버전의 자격은 인정하지 않는다(C-18).

### 취소와 무효화
API 키 회전, 권한 회수, GitHub App 설치 삭제, `REVOKED`는 즉시 capability lease·세션 토큰·폴더 토큰·작업 Lease를 무효화한다. 이미 발급된 Runner 명령에는 만료와 fencing 검사를 적용한다. `AUTHORIZED` 이후에도 프로브와 grant 확인 전에는 코드 읽기·도구 실행을 허용하지 않는다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R26-1 | 폐기 효과 | 폐기된 Agent가 과거 inbox URL·임시 토큰으로 새 작업을 가져가거나 대기 작업을 제출할 수 없음 (C-15) |
| R26-2 | 자격 판정 재현 | `reviewer_qualification` 결과가 같은 입력에서 항상 같음, 자격 없는 구성의 HIGH/CRITICAL 병합 0건 (C-18, CR-68) |
| R26-3 | 자기선언 분리 | UI·API에서 자기선언과 측정값이 다른 필드로 제공 |

---
