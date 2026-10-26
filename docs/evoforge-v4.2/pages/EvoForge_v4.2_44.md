<!-- PAGE:44/50 -->

# 44. 실시간 UI 동기화

> **목적:** 화면이 서버의 확정 상태와 항상 수렴하게 한다. · **결정:** D-009, D-039 · **계약:** —

### 구조
백엔드 도메인 이벤트(p.27)로 `MissionControlProjection` 같은 화면별 읽기 모델을 만든다. UI 이벤트는 도메인 이벤트의 투영이며, AG-UI의 `STATE_SNAPSHOT/STATE_DELTA`는 UI 적용 포맷이지 내부 도메인 모델이 아니다.

### SSE 계약
```text
id: 184922
event: project.state.delta
data: {"project_id":"…","projection_version":19,"changes":[{"path":"/tasks/…/status","value":"RUNNING"}]}
```
- 첫 접속: `GET /v1/projects/{project_id}/mission-control`가 `projection_version`과 `event_cursor`를 **같은 일관성 경계**에서 돌려준다 → 클라이언트는 그 커서 다음부터 SSE를 받는다.
- 버전 누락·보존 기간 초과·patch 적용 실패를 발견하면 조용히 넘어가지 않고 스냅샷을 다시 받는다. 순서를 전역 타임스탬프로 판단하지 않는다.
- 사용자별 권한 필터는 **발행 전**에 적용한다. 민감 로그·다른 조직 정보는 스트림에 들어가지 않는다.
- EvoForge UI SSE(자체 커서 재개)와 MCP Streamable HTTP(요청 단위, 구버전 `Last-Event-ID` 재개 가정 없음)는 별개다.

### 상호작용과 표시
카드 액션은 `POST /v1/projects/{project_id}/commands`로 변환되고, 버튼은 `RECEIVED` 후 `PENDING`, `APPLIED` 후 `DONE`을 표시한다. 응답이 없으면 성공으로 바꾸지 않는다. 이벤트 폭주 시 진행(progress) 이벤트는 샘플링하되 결론·승인·오류 이벤트는 절대 버리지 않는다. 토큰 스트리밍은 상세 보기에서만 요청 시 보인다. A2UI는 사전 허가된 컴포넌트 카탈로그의 선언형 제안으로만, MCP Apps는 호환 Chat 안 격리 iframe으로만 쓴다. 외부 모델이 만든 JSON이 브라우저 코드를 실행하게 하지 않는다.

### 목표(제안)
확정 이벤트의 화면 반영 p95 < 3초, 재연결 후 스냅샷 수렴 p95 < 10초.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R44-1 | 수렴 | 다중 브라우저·모바일 동시 접속과 네트워크 단절 시험에서 목표·명령·병합 상태가 수렴 |
| R44-2 | 누락 금지 | 폭주 시험(초당 1,000 이벤트)에서 승인·오류·결론 이벤트 누락 0 |
| R44-3 | 권한 필터 | 권한 없는 사용자의 스트림에 해당 이벤트 0건 |

---
