<!-- PAGE:43/50 -->

# 43. API 계약

> **목적:** 외부 API의 경로·권한·멱등성·오류 의미를 하나로 정한다. · **결정:** D-009, D-027, D-031 · **계약:** `contracts/schemas/evidence-retrieval.v1.schema.json`, `contracts/schemas/context-packet.v2.schema.json`

### 공통 규칙
- 모든 쓰기 요청: 인증 컨텍스트의 조직 범위, `Idempotency-Key`, 상태를 바꾸는 요청은 `expected_state_version`, `traceparent`. 응답: `request_id`, `correlation_id`, `trace_id`.
- 비동기 작업: `202 Accepted + command_id + status_url + accepted_at`. 202는 접수일 뿐 성공이 아니다.
- 오류: 403 권한, 404 없음(다른 테넌트 리소스도 404), 409 상태 버전 충돌, 422 계약 위반, 402 크레딧 소진·예산 초과, 429 속도 제한(`Retry-After`).
- `approve` 계열은 자연어로 실행되지 않으며 대상의 불변 `resource_sha`, 재인증, 확인 UI가 필요하다.
- OpenAPI 문서와 계약 테스트는 M0 Phase 1에서 이 표와 스키마로부터 생성한다.

### 엔드포인트
| Method | Path | 목적 | 권한 |
|---|---|---|---|
| POST | `/v1/projects` | 프로젝트 생성 | Owner/Admin |
| PUT | `/v1/projects/{project_id}/provider-allowlist` | 공급사·모델 허용과 데이터 전송 동의 | Admin |
| PUT | `/v1/projects/{project_id}/budgets/{period}` | 프로젝트 예산 | Admin |
| POST | `/v1/billing/credits` | 크레딧 구매(결제 대행 연동) | Owner |
| POST | `/v1/agents/join-requests` | AI 참여 신청 | 인증된 연결 |
| POST | `/v1/agents/{agent_id}/approve` | 참여 승인 | Admin |
| GET | `/v1/projects/{project_id}/mission-control` | 스냅샷 + `projection_version` + `event_cursor` | Viewer+ |
| POST | `/v1/projects/{project_id}/commands` | 명령 접수(본문 `scope.run_id`/`scope.task_id`) | 역할별 |
| GET | `/v1/commands/{command_id}` | 명령 상태 | 발행자·Viewer+ |
| POST | `/v1/projects/{project_id}/collectives/{collective_id}/runs` | Run 시작(`objective_version`, `max_seats`, `max_cost`, `preferred_topology`) | Operator+ |
| GET | `/v1/runs/{run_id}/allocation` · `/bottlenecks` · `/context-metrics` | 좌석 배정·병목·컨텍스트 지표 | Viewer+ |
| POST | `/v1/tasks/{task_id}/claims` | 작업 선점(`lease_epoch` 반환) | 승인된 Agent |
| POST | `/v1/tasks/{task_id}/submissions` | 후보 제출(`lease_epoch` 필수) | 배정 Agent |
| POST | `/v1/tasks/{task_id}/reviews` | 독립 리뷰 | Reviewer scope |
| POST | `/v1/tasks/{task_id}/context-packets` · GET `/v1/context-packets/{packet_id}` | 컨텍스트 패킷 | 시스템·배정 Agent |
| POST | `/v1/evidence-refs/{ref}/retrieve` | 원문 복원(`evidence-retrieval.v1`) | 패킷 수신자 |
| GET | `/v1/context-packets/{packet_id}/review-coverage` | 리뷰어 원문 커버리지 | Reviewer·Viewer+ |
| POST | `/v1/projects/{project_id}/context-policy-preview` | 컨텍스트 정책 미리보기 | Admin |
| GET | `/v1/runs/{run_id}/evidence` | 검증 결과 | Viewer+ |
| POST | `/v1/feedback` | 피드백 | Member+ |
| GET | `/v1/events/stream` | 실시간 이벤트(SSE) | Viewer+ |
| POST/GET | `/v1/projects/{project_id}/research/...` · `/harness/...` | 연구·승격(M6) | `research:*`, `harness:*` |

### 웹훅
GitHub 이벤트: 서명·시각·전달 ID 확인, 재전송 멱등. 결제 대행 웹훅: 중복·역순·환불·부분 환불 계약 테스트. 고객 발행 웹훅: HMAC 서명, 재시도·DLQ, 회전 가능한 secret.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R43-1 | 쓰기 API 완전성 | 모든 쓰기 API에 ID·권한·멱등성·속도 제한 정의, OpenAPI와 계약 테스트 자동 생성 |
| R43-2 | 존재 오라클 차단 | 다른 테넌트 리소스 요청은 404, 응답 시간 분포가 없는 리소스와 통계적으로 구분되지 않음 |
| R43-3 | 원본 접근 | 증거 원본은 매 요청 권한 재검증, 서명 URL은 단시간·범위 제한 |

---
