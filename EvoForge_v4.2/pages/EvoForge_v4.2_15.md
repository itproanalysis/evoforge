<!-- PAGE:15/50 -->

# 15. Collective Graph — AI 협업의 실시간 가시성

> **목적:** 좌석·역할·작업·핸드오프를 사실대로 그린다. · **결정:** D-003, D-024 · **계약:** `contracts/vocabulary.json`

### 노드와 엣지
- 노드: `Seat/Agent`, `Task`, `Artifact`, `Review`, `Decision`, `User Command`. 기본 보기는 좌석과 Task만, 상세 보기에서 관계를 펼친다. 공급사 로고보다 상태와 권한을 먼저 보인다.
- 엣지: `dependency`, `review`, `handoff`, `conflict`, `approval`, `produces`. 메시지 양이 아니라 실제 이벤트 ID가 있는 관계만 그린다. 근거가 없는 모델 추정 관계는 점선 + `근거 미확인`.

### 상태 표현(4차원, p.21)
좌석 배지는 `join / connection / execution / credential` 4차원을 분리해 보여준다. 예: `AUTHORIZED · READY · WAITING_FOR_CLIENT · VALID`. Chat 좌석은 *비상주* 배지를 달고, heartbeat가 끊기면 예약 작업만 TTL 만료 후 재배정한다. `HUMAN_RELAYED`(사람이 참여 JSON을 붙여넣은 경우) 플래그는 항상 표시한다.

### Topology Board
현재 토폴로지(`SINGLE`, `RACE_2`, `DAG_PARALLEL`, `PIPELINE`, `HIGH_RISK`), 좌석별 기능 역할·선택 이유·실제 수행 상태·Lease·핸드오프, 대기 원인(dependency/provider/chat/ci/merge/budget). 좌석별 Context Footprint: 읽은 evidence manifest 버전, 마지막 복원 이벤트, 입력/캐시 토큰, 차단된 복원 요청 수. 좌석 간 공유는 `artifact_id + evidence_version + allowed_fields`로만 하며 모델 대화·내부 상태는 전파하지 않는다.

### 성능
50개 이상 노드는 작업 단위로 묶고 가상화한다. 애니메이션이 완료를 암시하지 않도록 이벤트 확정 후에만 상태를 바꾼다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R15-1 | 2클릭 추적 | API 작성자 → Chat 리뷰어 → 테스트 → PR 관계를 2클릭 안에 추적 |
| R15-2 | 정직한 상태 | 비상주 Chat·수동 참여가 자동 실행처럼 보이는 표시 0건(시각 회귀 테스트) |
| R15-3 | 관계의 근거 | 화면의 모든 실선 엣지가 event_id로 해석됨 |

---
