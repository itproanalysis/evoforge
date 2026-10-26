<!-- PAGE:29/50 -->

# 29. Task DAG·Lease·충돌 관리

> **목적:** 한 작업에는 한 작성자만, 늦게 온 결과는 거부, 따로 통과하고 같이 깨지는 변경은 병합 전에 잡는다. · **결정:** D-032, D-043, D-046, D-053 · **계약:** `contracts/sql/core_DRAFT.sql`(`core.claim_task`, `core.assert_fencing`)

### Task 모델
`task_id, run_id, objective_version, dependencies, priority, risk_level, expected_write_set, acceptance_criteria, budget, status, version, lease_holder, lease_epoch, lease_expires_at, base_sha`. 시작 가능 조건 = 의존성 충족 ∧ 예산 예약 가능 ∧ 좌석 권한 ∧ write set 충돌 없음(또는 충돌 없는 분할).

### Claim과 Fencing
- `core.claim_task`는 `READY`이거나 만료된 `CLAIMED`일 때만 성공하고 `lease_epoch`를 1 올린다. 두 좌석이 동시에 요청해도 한 명만 이긴다.
- 모든 쓰기·PR 생성·병합 요청은 `(task_id, lease_epoch)`를 제시하고 `core.assert_fencing`을 통과해야 한다. 만료됐거나 epoch가 다르면 `STALE_WRITE`로 거부하고 경보와 원본 증거를 남긴다.
- Task Attempt에는 `context_packet_version`, `repo_base_sha`, `policy_version`, `evidence_manifest_hash`도 고정한다. 목표·정책·base SHA가 바뀌면 `ctx.mark_task_packets_stale`로 해당 작업의 컨텍스트 패킷이 STALE이 되고 재검토가 걸린다. STALE은 되살릴 수 없다.
- Lease TTL 기본 10분(제안), heartbeat로 연장. Lease는 작업 독점의 편의일 뿐, 병합 직전 검증(p.33)을 대신하지 않는다.

### 충돌 최소화
정적 분석으로 write set을 추정 → 파일·디렉터리·심볼 단위 겹침 확인 → 같은 파일을 고치는 Task는 기본 직렬화, API 계약만 공유하면 병렬 허용. 종료 후 실제 Diff와 예측 write set을 비교해 예측 정확도와 실제 충돌률을 기록하고, 과도한 잠금을 줄인다. 압축으로 파일 충돌을 해결할 수 없다.

### 응집도 분할과 wave(D-046)
- 변경 예상 파일의 의존 그래프에서 **허브**(touched 파일의 절반 이상과 연결되고 중앙값 차수의 1.5배 이상)를 떼어 wave 0에 둔다. 허브는 인터페이스를 먼저 바꾸고 직렬로 처리한다. 나머지는 결정적 label propagation으로 커뮤니티를 만들고 builder 좌석 수 이하로 병합한다(wave 1).
- 병렬화 조건: 파티션 2개 이상, 응집도(파티션 내부 의존 가중치 ÷ 비허브 전체) ≥ 0.75, 예상 속도(`총 작업량 ÷ (허브 작업량 + 최장 파티션 + 0.5 × 교차 가중치 + 고정 오버헤드)`) ≥ 1.3. 하나라도 미달이면 SINGLE. 근거: 2606.00953(교차 의존이 컨텍스트 전달 비용을 만든다). 우리 임계값은 제안값이며 실측으로 조정한다.
- 각 wave의 후보는 `candidates.wave_id`를 가진다.

### 결합 게이트와 동시 변경 통지(D-043)
- 같은 wave에 살아 있는 후보가 2개 이상이면 **결합본**(모든 후보를 base에 적용)으로 필수 테스트를 한 번 더 돌린다. 기준선과 각 패치 단독에서 통과한 테스트가 결합본에서 실패하면 간섭이다. `GC_COMPOSITION=FAIL`이면 병합하지 않고, 쌍 단위 재실행으로 원인 쌍을 찾아 해당 Builder들에게 돌려준다. DB가 게이트 누락을 거부한다(C-17).
- 작업 중에는 다른 Builder가 바꾸거나 지운 **공개 심볼**(함수·클래스·export) 중 자기가 참조하는 것만 즉시 통지받는다(`reference_impl/composition_gate.py`). Python 파일은 변경 전후 소스를 AST로 비교한다(`notices_from_sources`: 기본값·타입 주석까지 포함한 인자 목록, 클래스는 기반 클래스 + 공개 메서드 시그니처). 본문만 바뀐 함수와 비공개 심볼은 통지하지 않는다. 그 외 언어는 diff 휴리스틱을 쓴다(D-053). 추가된 심볼은 통지하지 않는다. 근거: 2609.25396(구성 과제에서 간섭 97%, 완료된 동시 변경 통지로 82% 회복). 실제 병합 PR 쌍에서는 드물었다는 같은 논문의 결과도 함께 기록한다 — 게이트 비용은 결합 실행 1회이므로 드물어도 켠다.

### 스케줄링
Ready Task 정렬: `user_urgency + critical_path_remaining + unblock_count + expected_verified_impact − collision_penalty − runner_backlog − cost_penalty`. 유휴 좌석은 권한·역량 조건을 만족하는 준비된 작업을 work-stealing으로 가져갈 수 있다. DAG에 사이클이 생기면 Task 추가를 거부한다. 대기 초과·Chat 미응답·워커 장애는 재배정 또는 포기 제안으로 사용자에게 보인다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R29-1 | 단일 승자 | 동시 Claim 2건 중 1건만 성공 (C-05) |
| R29-2 | 늦은 쓰기 거부 | 만료 Lease의 제출·병합 요청 차단 (C-05) |
| R29-3 | 상태 머신 | 허용되지 않은 Task 전이 0건 (C-06) |
| R29-4 | 결합 실패 차단 | 같은 wave 후보 2개 이상에서 `GC_COMPOSITION` PASS 없이 병합 0건, 간섭 시 원인 쌍 기록 (C-17, CR-60) |
| R29-5 | 동시 변경 통지 | 시그니처 변경·삭제가 참조 Builder에게만 전달, 자기 변경·추가 심볼 통지 0 (CR-61) |
| R29-6 | AST 통지 | Python 메서드 시그니처 변경은 통지, 본문만 바뀐 함수·비공개 심볼은 통지 0 (CR-78) |

---
