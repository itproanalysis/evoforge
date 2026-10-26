<!-- PAGE:35/50 -->

# 35. 비작성자 독립 리뷰

> **목적:** 리뷰가 실제로 독립적이고, 원문을 실제로 봤는지, 차단 근거가 실행으로 확인되는지 판정 가능하게 만든다. · **결정:** D-007, D-020, D-028, D-038, D-041, D-044, D-045 · **계약:** `contracts/sql/context_plane_DRAFT.sql`(`ctx.assert_review_gate`), `contracts/quality_gates.json`

### 독립성
- `reviewer ≠ author`는 DB가 강제한다.
- **HIGH/CRITICAL은 자격 + 컨텍스트 독립 + 명세 선행(D-041).** verifier는 해당 등급·하네스 버전 자격이 유효해야 하고, 빌더 transcript·근거·자기평가·임시 테스트를 받지 않는다(허용 입력: 목표 계약·정책·명세·diff·CI 결과·자기 테스트). Phase A에서 diff를 보기 전 명세만으로 수용 테스트를 작성·봉인하고(`spec_tests_sealed_at`), Phase B에서 diff를 연다(`diff_first_read_at`, 반드시 봉인 이후 — DB CHECK). 빌더에게는 반례(입력·기대값·관측값·테스트 참조)만 돌려준다. 다른 공급사 모델을 요구하지 않는다: 2610.28667에서 효과는 컨텍스트 독립과 명세 선행에서 나왔고 공급사 차이는 결함을 더 찾지 못했다. 인간 승인은 그대로 필요하다(C-18).
- 작성자 Runner와 리뷰 Runner의 작업 공간·비밀·평가 입력 권한을 분리한다. 리뷰어는 Diff·명세·실행 증거만 읽고 검증 셋을 바꿀 수 없다. 필요하면 작성자 주장과 모델 이름을 숨긴 블라인드 리뷰를 한다.
- 리뷰 결론은 구조화된 Issue(`severity`, `file`, `line`, `code`, `reason`, `evidence`)로 남긴다. 의견 충돌은 실행 증거로 먼저 가린다(불일치 해결: 양쪽 주장을 테스트로 실행). 그래도 남으면 세 번째 리뷰 또는 보안 담당자에게 올린다.

### 차단 근거와 신호 품질(D-044)
- `changes_requested`·`reject`는 **실행 가능한 증거**(`failing_test`, `reproducer_script`, `static_rule_hit`, `policy_violation`)와 그 참조가 있어야 기록된다(DB CHECK, C-19). 증거 없는 차단 지적은 advisory로 강등하고 후보당 심각도 순 5개만 보여준다. 근거: 2603.11078(리뷰 에이전트 정밀도 3–5%, 반복 탐색은 recall을 올리고 SNR을 떨어뜨림).
- 리뷰어 자격에 지적 정밀도 하한이 들어간다(p.26).

### 후보 선택(D-045)
여러 후보가 있으면 `reference_impl/selection.py` 규칙으로 고른다: 게이트 PASS·보상 해킹 flag 없음(하드 필터) → 재현 테스트 Wilson 하한 → 봉인 held-out Wilson 하한 → 작은 diff. 증거 차이가 0.02 이내인 후보끼리만 구조화 요약(가설·진행·실패 모드)을 놓고 재귀 토너먼트(3표 다수결)를 한다. LLM 판정자가 실행 증거를 뒤집지 못한다. 근거: 2607.00990, 2604.16529, 2610.00972. 샘플 수는 adaptive k(p.16).

### 원문 확인의 판정
`submit_review(verdict=approve)`는 `ctx.assert_review_gate`를 통과해야 기록된다: 패킷 ISSUED·미만료, critic/verifier, 비작성자, 패킷 `repo_sha` = 후보 head, `requires_original` ref(최종 Diff, 실패 Assertion, 정책 결과, 잠금파일)의 **모든 바이트가 그 리뷰어에게 전달됨**. 요약은 진입점일 뿐이다.
- 요구 원문이 리뷰어 컨텍스트 한도를 넘으면 hunk 단위 chunk 리뷰(같은 L0–L2 Prefix로 캐시 적중) + cross-chunk 패스 1회.
- 원문 합계가 **400KB(`max_reviewable_diff_bytes` = 409,600바이트)**를 넘으면 PR 분할 또는 인간 리뷰어를 요구한다.
- 바이트 전달은 필요조건일 뿐이다. 그래서 리뷰어 구성은 p.26의 seeded-defect 자격 시험을 통과해야 승인자가 된다.

### 승인권
AI 리뷰의 approve는 정책상 근거 중 하나다. 병합 가능 여부는 `core.authorize_merge`가 정한다(게이트 PASS + 독립 approve + 나중에 기록된 차단 리뷰 없음 + 고위험이면 자격·컨텍스트 독립·명세 선행 approve와 head에 묶인 인간 승인). 인증·결제·권한·개인정보·보안 정책·DB 마이그레이션·배포는 기본적으로 인간 승인이 필요하다. 원문 복원 도구가 없는 Chat은 의견은 낼 수 있지만 승인자는 될 수 없다. 리뷰 대기가 길어지면 자격 있는 다른 비작성자에게 재배정하고 변경 이력을 남긴다. 압축 때문에 중요한 결함을 놓친 사실이 확인되면 해당 codec 프로필을 즉시 비활성화한다(p.37).

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R35-1 | 자기 리뷰 차단 | 작성자의 리뷰 INSERT 거부 (C-07) |
| R35-2 | 원문 커버리지 | 요구 원문 100% 전달 전 approve 기록 0건 (T12) |
| R35-3 | 차단 리뷰 우선 | approve 뒤에 기록된 changes_requested가 있으면 병합 불가 (C-09) |
| R35-4 | 자격 | 자격 미달 리뷰어 구성의 approve가 병합 근거로 쓰인 건수 0 (C-18) |
| R35-5 | 명세 선행 순서 | diff 열람 후 봉인된 명세 테스트를 가진 approve 0건, 빌더 컨텍스트를 본 HIGH/CRITICAL approve 0건 (C-19, CR-66) |
| R35-6 | 증거 있는 차단 | 증거 없는 changes_requested·reject 기록 0건, advisory 노출 ≤ 5 (C-19, CR-67) |
| R35-7 | 증거 우선 선택 | 실행 증거가 더 나쁜 후보가 판정자 표로 선택된 건수 0 (CR-65) |

---
