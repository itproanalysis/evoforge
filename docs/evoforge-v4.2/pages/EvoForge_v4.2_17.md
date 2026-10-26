<!-- PAGE:17/50 -->

# 17. Evidence Timeline — 검증된 진척

> **목적:** 무슨 일이 언제, 누구에 의해, 어떤 근거로 일어났는지 위변조 없이 보여준다. · **결정:** D-008, D-030 · **계약:** `contracts/sql/core_DRAFT.sql`(`domain_events`, `gate_results`)

### 이벤트와 카드
- 이벤트 예: `goal.created`, `task.claimed`, `candidate.proposed`, `gate.recorded`, `review.recorded`, `pr.created`, `merge.blocked`, `pr.merged`, `outcome.validated`, `feedback.confirmed`. 발생 시각과 인과(`correlation_id`/`causation_id`)를 따로 표시한다.
- 증거 카드 필수 값: 시각(UTC·사용자 시간대), 주체(인간/AI/시스템), 대상, base/head SHA, `policy_hash`, `runner_image_digest`, `harness_version`, 모델 식별자, 테스트 로그 해시, 결과와 제한사항, 대기 상태 체류시간(`WAITING_PROVIDER/AGENT/DEPENDENCY/RUNNER/REVIEW/MERGE`).
- 컨텍스트 근거: `original_blob_digest`, 뷰 해시, 복원 이벤트, 리뷰어 원문 커버리지, `model_usage_receipt`. 압축 로그를 펼치면 권한 확인 후 원문을 복원한다. 원문이 없거나 만료·권한 부족이면 감사 가능한 오류를 표시하고, 그 근거에 의존한 병합 승인을 중단한다.

### 수치 상태
`PENDING`, `MEASURED`, `VALIDATED`, `REJECTED`, `INSUFFICIENT_EVIDENCE`, `NO_CONFIDENT_IMPROVEMENT`. 벤치마크를 한 번만 돌렸으면 신뢰도 경고를 붙인다. `PR merged`와 `Outcome validated`는 다른 이벤트다.

### 증명 수준
M1~M4: append-only DB 이벤트 + Object Storage 버전 관리 + 해시. M5 이전: CI 근거에 in-toto attestation과 Sigstore 서명을 도입한다. "테스트 통과"는 반드시 같은 커밋·같은 평가 환경을 가리켜야 한다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R17-1 | 불일치 탐지 | 화면 숫자·DB·GitHub CI 결과가 다르면 `동기화 오류`를 표시하고 자동 성공 판정 0건 |
| R17-2 | 원본 접근 재검증 | 카드에서 원본으로 갈 때마다 서버가 권한을 다시 확인(서명 URL 단기·범위 제한) |
| R17-3 | 내보내기 | 증거 묶음 JSON 내보내기(M4), PDF(M5) |

---
