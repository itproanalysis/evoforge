<!-- PAGE:24/50 -->

# 24. Folder Bridge — 파일로 참여하는 AI Chat

> **목적:** 파일 기반 참여를 중복·부분 업로드·사칭에 견디게 만든다. · **결정:** D-003, D-033 · **계약:** `contracts/schemas/evidence-retrieval.v1.schema.json`

### 원칙
파일은 **인터페이스**이지 정본이 아니다. 정본은 서버 DB다. 파일 수정·삭제를 상태 변경으로 믿지 않는다.

```text
workspace/<project-id>/
  participation/requests/
  agents/<agent-id>/inbox/   outbox/   ack/
  artifacts/<task-id>/
  protocol/README.md
```

### 메시지 계약(`evoforge.folder/1`)
필수 필드: `schema`, `message_id`, `project_id`, `agent_id`, `task_id`, `type`, `created_at`, `expires_at`, `idempotency_key`, `nonce`, `content_sha256`, `auth_binding`(서버가 발급한 단기 토큰의 참조), `payload`. `type`에 `GET_EVIDENCE`(본문 = `evidence-retrieval.v1` 요청)가 있다. 비밀키를 공유 폴더에 두지 않는다.

### 처리 순서
1. 업로드 임시 파일 → checksum 확인 → `ready manifest`(Object Storage는 원자적 rename을 보장하지 않을 수 있음). 로컬 브리지는 temp → atomic rename.
2. 저장소 접근 주체와 연결 토큰을 대조하고, 대상 프로젝트 권한을 DB에서 다시 확인.
3. `UNIQUE(tenant_id, message_id)`와 `content_sha256` 검사 후 inbox 행과 Outbox를 같은 트랜잭션에 기록.
4. 크기·확장자·악성 페이로드·데이터 등급 검사 후 작업 큐로 전달. 디렉터리 정렬 순서를 우선순위로 쓰지 않는다.
5. DB commit 후 `ack` 파일 게시. 업로드 성공 ≠ 작업 성공.
감시 이벤트는 놓칠 수 있으므로 주기적 reconciliation을 돌린다. heartbeat TTL과 Chat별 작업 정원으로 backlog를 막는다. `OFFLINE` Chat에는 새 작업을 주지 않는다. 경로·ref·파일 내용은 path traversal·symlink 검사 대상이며 원문 응답 파일의 임시 URL은 짧게 유지한다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R24-1 | 정확히 한 번의 효과 | 같은 파일 10회 재전송·네트워크 단절·부분 업로드·브리지 재시작 후에도 처리 1회 |
| R24-2 | 사칭 차단 | 다른 좌석의 `agent_id`를 적은 파일은 `auth_binding` 불일치로 거부 + 보안 이벤트 |
| R24-3 | 전송 고지 | 코드·산출물이 외부 Chat으로 가는 위치·보존기간·열람 범위를 등록 시 표시 |

---
