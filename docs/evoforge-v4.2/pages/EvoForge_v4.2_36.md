<!-- PAGE:36/50 -->

# 36. 변경 단위 품질 게이트

> **목적:** 후보 하나가 병합될 자격을 결정적으로 판정한다. · **결정:** D-007, D-020, D-021, D-042, D-043, D-053, D-054 · **계약:** `contracts/quality_gates.json`(`change_gates`), `contracts/sql/core_DRAFT.sql`(`core.gate_results`)

### 게이트 순서(정본)
| 게이트 | 내용 | 조기 탈락 |
|---|---|---|
| `G0_SCOPE` | 허용 디렉터리·파일·명령, 변경량, 금지 패턴, 비밀 탐지, 정적 검사·타입·린트, 의존성 취약점 | 허용 |
| `G1_IMPACTED` | 영향받는 테스트만 저비용 실행 | 허용(실패 후보만 제거) |
| `G2_REQUIRED` | 전체 필수 테스트 + 보안 스캔 + 공급망·권한·외부 네트워크 검사 | 생략 불가 |
| `GH_INTEGRITY` | **항상 필수.** ① 새 테스트의 강한 오라클 비율 ≥ 0.8, 재현 테스트는 전부 강함(미달은 분류기 측정 규모가 작은 동안 INCONCLUSIVE, D-054) ② 봉인 held-out(과제당 ≥ 3개, compositional·negative 포함) 대비 공개 검증 격차 Δ ≤ 5%p ③ 입력별 상수 반환(조회 테이블) 없음 ④ 검증기 변조 없음(보호 파일 수정·삭제, skip/xfail/only 추가, assert 삭제, 강제 성공 종료, 예외 삼킴, 타임아웃 과다 증가) | 생략 불가 |
| `GC_COMPOSITION` | 같은 wave에 살아 있는 후보 ≥ 2개일 때만 필수: 결합본 필수 테스트, 간섭 0 (p.29) | 생략 불가(해당 시) |
| `G3_BENCHMARK` | 성능 목표가 있는 과제에서만 필수: ABBA ≥ 5블록, 중앙값, 상대 개선의 95% bootstrap 하한 > 0 이고 사전 선언 MDE 이상 | — |
| `GR_REVIEW` | 비작성자 리뷰(원문 커버리지 포함) + 필요한 인간 승인 | 생략 불가 |
| `G4_MERGE_HEAD` | 병합 직전 최신 head·required checks·정책 해시 재확인 | 생략 불가 |

### 결과 계약
결과는 `PASS / FAIL / INCONCLUSIVE / SKIPPED_WITH_REASON` 중 하나다. **INCONCLUSIVE는 PASS가 아니다.** 필수 게이트의 SKIP은 예외 승인이 없으면 차단한다. 워커가 API 오류를 PASS로 바꾸거나 로그가 비면 INCONCLUSIVE. 기록 필드: `gate`, `result`, `head_sha`, `policy_hash`, `runner_image_digest`, `evidence_sha256`, `recorded_at`(append-only). 병합 판정은 현재 head·현재 정책 해시에서 게이트별 **최신** 결과가 모두 PASS인지로 한다.

### 테스트 조작 방지(GH_INTEGRITY의 근거)
- 후보는 공개 테스트를 고칠 수 있지만 hidden suite·평가기·보호된 CI 정의는 고칠 수 없다. 테스트 삭제·skip 증가·mock 남용은 전후 비교로 탐지한다(`reference_impl/reward_hack.py` `tampering`).
- **오라클 강도.** 테스트가 있다는 것은 검증이 아니다. 에이전트가 쓴 테스트 패치의 80.2%가 오라클이 약하거나 없었다(2606.18168, 86,156건). 분류(`reference_impl/oracle_strength.py`): none·tautology·existence·boolean·mock_only·snapshot(약함) / value_equality·exception·property(강함). 테스트 함수의 강도는 가장 강한 assertion으로 정한다.
- **분류기와 그 정확도(D-053).** Python은 AST로 분류한다(`reference_impl/oracle_ast.py`). v4.1의 줄 단위 정규식은 assert 메시지 안의 `==`, 문자열 속 assert 문구, 여러 줄 assert를 잘못 읽었다. 측정(직접 만든 말뭉치, 외부 벤치마크 아님): 개발 말뭉치 58건 정확 일치 100%(회귀 기준), 분류기 확정 후 작성한 holdout 20건 정확 일치 85%(강/약 일치 85%, Wilson 95% 0.64–0.95), 강하지 않은 테스트를 강하다고 본 비율 5%(1/20). 같은 holdout에서 정규식은 강/약 일치 90%였다 — AST가 모든 면에서 낫다는 근거는 아직 없다. 개발+holdout 78건 전체로는 AST 96% 대 정규식 78%다. 알려진 미탐: try/`pytest.fail` 수동 예외 검사, 테스트가 호출하는 헬퍼 안의 assert. JS/TS는 정규식이다.
- **잠정 규칙(D-054).** 사람이 라벨한 holdout이 200건이 되기 전에는 오라클 강도 미달을 `GH_INTEGRITY=INCONCLUSIVE`로 기록한다. INCONCLUSIVE도 병합을 막지만 FAIL과 달리 예외 승인 또는 테스트 보강으로 풀 수 있다. 보상 해킹·검증기 변조 flag는 항상 FAIL이다. 판정 함수: `reference_impl/integrity_gate.py`.
- **보상 해킹.** 공개 검증만 통과하고 봉인 held-out에서 떨어지는 후보는 명세가 아니라 테스트를 맞춘 것이다(2605.21384: 격차가 크고 과제가 클수록 커짐). 후보 단위로는 점추정 Δ > 5%p면 flag, arm 단위 집계로는 Newcombe 95% 하한 > 2%p면 flag. LLM 보상 해킹 모니터는 보조 신호다(2610.10947: 다회차 transcript에서 약함).
- 테스트 구성·검증 스크립트를 바꾼 후보는 그 변경 자체를 새 정책 버전으로 승인받기 전에는 새 기준을 쓰지 않는다.
- 평가 세트는 `reference patch pass`·`empty patch fail` 양면 검사를 통과한 과제만 쓰고, 에이전트 diff를 깨끗한 이미지에서 다시 채점한다(SWE-bench Pro V2 방식 참고). 하네스 후보가 테스트 파일을 본 순간 그 평가 세트는 사용 불가.

### Flaky 테스트
기준선에서 10회 재실행해 1회 이상 실패하면 flaky로 격리한다. flaky 테스트는 단독 근거가 될 수 없고, 1회 재시도 성공만으로 회귀 없음을 판정하지 않는다. 검증 환경을 구성하지 못한 고객은 자동 병합이 꺼진다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R36-1 | 결함 패치 차단 | 정상 패치 + 4종 결함(테스트 삭제·비밀 노출·성능 회귀·권한 우회) 패치에 대해 기대 게이트 결과 재현 |
| R36-2 | INCONCLUSIVE 차단 | 필수 게이트 INCONCLUSIVE 상태 병합 0건 (C-08) |
| R36-3 | 증거 불변 | 게이트 결과 수정·삭제 불가 (C-10) |
| R36-4 | 무결성 게이트 | `GH_INTEGRITY` 누락·FAIL 상태 병합 0건 (C-16), 오라클·보상 해킹·변조 시나리오가 기대 판정 재현 (CR-62, CR-63, CR-64) |
| R36-5 | 결합 게이트 | wave 후보 2개 이상에서 `GC_COMPOSITION` 누락·FAIL 상태 병합 0건 (C-17, CR-60) |
| R36-6 | 분류기 품질 | 개발 말뭉치 100% 유지, holdout 강/약 일치 ≥ 0.85·약→강 오판 ≤ 5%, holdout 200건 전까지 오라클 미달은 INCONCLUSIVE (CR-77, CR-79) |

---
