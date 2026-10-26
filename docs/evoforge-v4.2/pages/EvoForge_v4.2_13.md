<!-- PAGE:13/50 -->

# 13. Command Center — 즉시 반응하는 명령

> **목적:** 사람의 지시를 즉시 접수하고, 실제 적용 여부를 정직하게 보여준다. · **결정:** D-031, D-009 · **계약:** `contracts/sql/core_DRAFT.sql`(`core.commands`, `core.accept_command`)

### 명령 종류(정본: `vocabulary.json` `command_kind`)
- 일반: `ASK`, `FEEDBACK`, `CHANGE_GOAL`, `REPRIORITIZE`, `REQUEST_REVIEW`, `REASSIGN`, `RESUME`, `CONTEXT_OVERRIDE`(예: "요약 말고 전체 Diff로 다시 리뷰").
- 안전·제어(fast lane): `STOP_ALL`, `PAUSE`, `CANCEL`, `BUDGET_DECREASE`, `REPRIORITIZE`, `REASSIGN`.
- 위험(확정 필요): `APPROVE_MERGE`, `APPROVE_DEPLOY`, `BUDGET_INCREASE`, `ENABLE_AUTOMERGE`, `PERMISSION_CHANGE`, `ROLLBACK_HARNESS`.
- 연구(M6): `SEARCH_RESEARCH`, `PROPOSE_HARNESS_EXPERIMENT`, `REQUEST_PROMOTION_REVIEW`, `PAUSE_RESEARCH`. 실험·승격은 `research:execute`/`harness:promote` 권한.

### 처리 규칙
- 자연어 입력은 구조화된 명령 + 영향 미리보기로 변환된다. "해줘"를 감지했다고 배포·병합하지 않는다. 위험 변경이 추출되면 `AWAITING_CONFIRMATION`에서 권한자가 다시 확정한다.
- `CHANGE_GOAL`은 새 `ObjectiveVersion`을 만들고 미시작 Task에는 즉시, 실행 중 Task에는 안전 체크포인트를 거쳐 적용한다. 진행 중 컨텍스트 패킷은 STALE이 된다(p.29).
- `PAUSE`: 신규 배정 중지 + Runner 체크포인트 요청. `CANCEL`: 신규 배정 금지 + 진행 중 프로세스 종료 + 잔여물 정리. `STOP_ALL`: 조직 전체 dispatch·merge 차단 스위치(오케스트레이터보다 상위, p.30).
- 외부 Chat 작업 중지는 상대 세션을 강제 종료할 수 없으므로 `request_sent → acknowledged → stopped`를 구분 표시한다.
- `CONTEXT_OVERRIDE`는 새 컨텍스트 정책 버전과 새 평가 작업을 만든다. 원문 복원이 끝나기 전에는 완료로 표시하지 않는다.
- 오래 걸리는 연구 명령은 `202 + status_url`로 추적하고, 즉시 적용하지 않고 *제안 카드 + 위험 + 예산 + 평가 계획*으로 응답한다.

### 예시
"성능보다 보안 우선, 기존 패치는 병합하지 마" → `REPRIORITIZE` + 병합 게이트 잠금(fast lane) → 진행 중 실험은 체크포인트에서 안전 중단 요청 → 우선순위 재계산 → 기존 리뷰에 재검토 요청. UI는 접수/검증/중지 요청/실제 중단을 따로 보여준다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R13-1 | ACK 지연 | 명령 접수 p95 < 2초(정상 네트워크), 모델·CI 부하와 무관 |
| R13-2 | 멱등성·버전 | 20회 재전송 → 1회 실행, 오래된 버전 → 409 (C-02) |
| R13-3 | 안전 명령 우선 | `STOP_ALL`은 상태 버전이 어긋나도 접수되고 fast lane으로 처리 (C-02) |
| R13-4 | 허위 성공 금지 | 실행 확인 전 `APPLIED` 표시 0건(E2E 테스트) |

---
