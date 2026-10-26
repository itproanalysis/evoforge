<!-- PAGE:23/50 -->

# 23. Remote MCP — AI Chat 협업

> **목적:** MCP 지원 Chat이 EvoForge 작업에 안전하게 참여하게 한다. · **결정:** D-003, D-004, D-039, D-027 · **계약:** `contracts/schemas/evidence-retrieval.v1.schema.json`

### 기준 규격
MCP 2026-07-28을 기준으로 한다(공식 공지로 확인): `initialize` 핸드셰이크와 세션 헤더 폐지, 요청마다 `_meta`에 프로토콜 버전·클라이언트 정보·능력, Streamable HTTP 요청에 `Mcp-Method`/`Mcp-Name` 헤더, Tasks는 `io.modelcontextprotocol/tasks` 확장, 중간 입력은 MRTR(`input_required`), 목록 응답의 캐시 힌트. **Roots·Sampling·Logging과 구 HTTP+SSE 전송은 사용하지 않는다**(폐지 예고). 실제 클라이언트가 지원하는 버전과 협상한다.

### 도구
협업: `join_collective`, `get_my_tasks`, `claim_task`, `post_message`, `submit_proposal`, `submit_review`, `acknowledge`, `get_project_status`, `leave_collective`. 컨텍스트: `get_task_context`, `list_evidence_refs`, `retrieve_evidence`. 핵심 도구는 기본 요청/응답으로 먼저 제공하고, Tasks 확장은 Probe로 지원이 확인된 클라이언트에만 쓴다. 장기 상태는 서버 DB가 갖고, 필요한 경우 서버가 발급한 `participation_handle`을 도구 결과로 돌려준다.

### 보안
OAuth/OIDC 위임 토큰, issuer(RFC 9207)·audience·scope 검증, `Origin` 검증, CSRF·SSRF 방지, 노출 도구 최소화, 속도 제한. 도구 인자로 들어온 `tenant_id`·`agent_id`는 믿지 않고 인증 컨텍스트에서 결정한다. `retrieve_evidence`는 닫힌 selector 문법만 받고, 다른 테넌트 ref와 없는 ref를 같은 `not_found`로 응답한다. 원문 복원을 직접 호출할 수 없는 Chat은 리뷰어 승인 자격이 없다.

### 상태
`offer → ack → result`를 따로 저장한다. 클라이언트 세션 종료는 DAG 종료가 아니다. 타임아웃 시 고객이 허용한 API 좌석으로 재배정한다. MCP 전송과 EvoForge 웹 UI의 SSE(p.44)는 별개 프로토콜이다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R23-1 | 실클라이언트 검증 | 지원 클라이언트 1개 이상에서 `join → get_my_tasks → submit_proposal → status`를 실제 도구 호출로 검증(헤더·인가·쓰기·취소·재접속 포함) |
| R23-2 | 폐지 기능 미사용 | 코드베이스에 Roots/Sampling/Logging 의존 0(정적 검사) |
| R23-3 | 지원 매트릭스 | 클라이언트명·플랜·읽기/쓰기·장기 작업·확인 UI·실측일 기록 |

---
