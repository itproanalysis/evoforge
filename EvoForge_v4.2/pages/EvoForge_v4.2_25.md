<!-- PAGE:25/50 -->

# 25. A2A Gateway — 외부 에이전트 연결

> **목적:** 다른 시스템의 에이전트를 내부 상태 모델을 해치지 않고 연결한다. · **결정:** D-004 · **계약:** —

### 위치
A2A는 외부 연동 어댑터다. 내부 작업 엔진을 A2A로 바꾸지 않는다. 기준은 A2A 1.0(2026-03-12 공개; 서명된 Agent Card, 다중 테넌트 엔드포인트).

### 연결 순서
`Agent Card URL 등록 → HTTPS·허용 도메인·스키마 검증 → 서명/신뢰 목록 확인 → 프로젝트 승인 → Capability Probe → Registry → Task dispatch → poll/stream → 결과 검증`. Agent Card 서명은 메타데이터 신뢰에 도움이 되지만 프로젝트 접근 권한을 대신하지 않는다. 다중 테넌트 엔드포인트라도 인증 주체와 `tenant_id`는 서버에서 묶는다.

### 보안
등록 URL의 SSRF 방지: DNS 재확인, 사설·링크로컬 IP 차단, 리다이렉트 검증, egress 제한. 원격 응답은 비신뢰: 서명·입력 크기·산출물 해시·권한·외부 전송 정책을 다시 검사한다. 원격 에이전트의 코드 쓰기 범위는 정책으로 제한한다.

### 상태 매핑
외부 A2A Task 상태와 내부 Task를 매핑하되 억지로 같게 만들지 않는다. A2A 종료 상태(`completed/failed/canceled/rejected`)는 같은 ID로 되돌리지 않으므로, 재시도는 새 A2A Task ID + `retry_of`로 기록한다. `contextId`, A2A `taskId`, 내부 `run_id/task_id`를 별도 컬럼에 둔다. 원격 취소 신호의 즉시 성공을 가정하지 않는다. 배정 점수에 원격 주체의 `available_capacity`, `latency_p95`, `historical_verified_rate`, `privacy_scope`를 반영한다.

### 모듈
`A2AClientAdapter`, `AgentCardVerifier`, `TaskStatusMapper`, `ArtifactValidator`, `RemoteCancellationAdapter`.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R25-1 | 통합 테스트 | 테스트 A2A 에이전트와 메시지·산출물 왕복, 취소 요청, 시간 초과, 잘못된 Card 거부 |
| R25-2 | SSRF | 사설 IP·리다이렉트·DNS rebinding 시나리오 100% 차단 |
| R25-3 | 재시도 추적 | 모든 재시도가 새 외부 ID와 `retry_of`로 연결 |

---
