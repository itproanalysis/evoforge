<!-- PAGE:16/50 -->

# 16. Improvement Lab — 과제별 실험 화면

> **목적:** 한 과제의 후보·근거·위험·비용을 비교하고 결정하는 화면을 정한다. · **결정:** D-007, D-020, D-042, D-045 · **계약:** `contracts/quality_gates.json`

### 탭
`Overview` · `Discussion` · `Candidates` · `Diff` · `Tests & Gates` · `Benchmarks` · `Review` · `Merge Decision`. 기본 탭은 "무엇을 왜 고치는가".

### Overview 필드
문제 설명, 발생 근거, 목표 KR, 위험 등급, 예상 변경 파일(write set), 담당 좌석, 현재 상태, 장애물, 사용한 크레딧, 다음 의사결정.

### 후보 비교
- 모든 후보는 같은 시작 SHA에서 만든다. 열: 후보별 `author seat`, `base/head SHA`, `write set`, 게이트 결과(G0~G4, `GH_INTEGRITY`, `GC_COMPOSITION`, GR), 리뷰 결과, 벤치마크, 추가 비용, staleness.
- **선택 근거 열(p.35):** 재현 테스트 통과(측면별: 원 증상·경계·회귀 방지), 봉인 held-out 통과, 오라클 강도(강한 비율), 보상 해킹 flag(공개/held-out 격차·조회 테이블·검증기 변조), diff 크기. 순위는 이 증거로 정해지고, 판정자(토너먼트)는 증거가 같은 후보 사이에서만 쓰였을 때 그 사실을 표시한다(`selection_method`).
- 각 후보에 `prediction`(사전 선언한 기대 효과) / `observation`(실측) / `delta` / `failure attribution` / `confidence`를 나란히 둔다. 외부 연구의 성능 수치를 기본값으로 채우지 않는다.
- 후보 수 `k`는 1에서 시작하고 adaptive k 규칙(p.35, 최대 5)으로 늘어난다: LOW는 첫 full-pass에서 멈추고, 그 외에는 행동이 같은 full-pass 2개가 나오면 멈추며, full-pass끼리 행동이 다르면 하나 더 뽑는다. 우수 후보를 고르면 나머지 후보의 안전 취소와 비용 확정을 기록한다.
- 겹치는 파일이 있으면 병합 충돌 위험을 미리 경고한다.

### 사용자 행동
`다른 접근법 요청`, `재검증`, `추가 리뷰어 지정`, `후보 거부`, `목표 기준 수정`. 검증 정책을 낮추는 동작은 Admin 정책 경로로만 가능하고, 이 화면에서는 할 수 없다. 컨텍스트 실험(M3)에서는 같은 후보를 `A_RAW`, `B_STRUCTURAL`, `C_RECOVERABLE`, `E_CACHE_AWARE` arm으로 다시 돌린 결과를 보여준다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R16-1 | 숫자의 근거 | 결과가 없는 지표 칸은 `측정 대기`, 임의 숫자 0건 |
| R16-2 | 품질 이득·새 위험 설명 | 후보별 변경 요약에 게이트 결과·리뷰 지적·위험 등급이 자동 포함 |
| R16-3 | 사전 선언 불변 | `prediction`은 실험 시작 후 수정 불가(새 실험 생성으로만 변경) |
| R16-4 | 선택 설명 | 선택된 후보마다 `selection_method`(execution_evidence / smallest_diff_tiebreak / recursive_tournament)와 탈락 후보의 탈락 사유(게이트·flag·증거 차이)가 표시됨 (CR-65) |

---
