# EvoForge v4.2 마감 보고서

대상: `legacy/v4.1/EvoForge_Blueprint_50pages_v4.1.md`와 v4.1 패키지 · 작성일 2026-10-25

## 1. 무엇을 닫았나

v4.1 보고서 §6 "한계"에 남은 네 항목을 실행 가능한 계약으로 바꿨다.

| v4.1 한계 | v4.2 처리 | 근거 |
|---|---|---|
| 오라클 분류·심볼 비교가 정규식 휴리스틱이고 정확도 미측정 | Python은 AST로 교체, 말뭉치 2종으로 측정, 측정 규모가 작은 동안 잠정 규칙 적용 | D-053, D-054, ADR-062, CR-77~79 |
| CR-74 평가 위생 미구현 | base 도달 객체만으로 샌드박스 재구성 + 감사 7항목, 실제 git으로 시험 | D-055, ADR-063 |
| CR-75 압축 경계 평가 미구현 | 4조건 판정기 + 수치 확정 | D-056, ADR-064 |
| CR-76 최적화기 규칙 미구현 | 상태 머신 + `harness-patch.v1` 스키마 + 패치 검사기 | D-057, ADR-065 |

`tools/validate_package.py --pg` 결과는 §5에 있다.

## 2. 측정값: 오라클 분류기

말뭉치는 직접 만들었고 외부 벤치마크가 아니다. 그래서 "분류기가 정확하다"가 아니라, 우리 분류 규칙과 얼마나 일치하는지, 어떤 방향으로 틀리는지를 보여주는 값이다.

| 말뭉치 | 건수 | 작성 시점 | AST 정확 일치 | AST 강/약 일치 | 정규식(v4.1) 정확 | 정규식 강/약 |
|---|---:|---|---:|---:|---:|---:|
| dev (`reference_impl/fixtures/oracle_corpus.json`) | 58 | 분류기 개발 중(튜닝에 사용) | 100% | 100% | 67% | 74% |
| holdout (`reference_impl/fixtures/oracle_holdout.json`) | 20 | 분류기 확정 후(튜닝 금지) | 85% | 85% (Wilson 95% 0.64–0.95) | 70% | 90% |
| 합계 | 78 | — | 96% | 96% | 68% | 78% |

**holdout 오분류 3건(수정하지 않고 보고):**
- ho008 `m.call_args == call(1)`: 라벨 value_equality, AST mock_only. 라벨 기준 자체가 애매하다(호출 인자 일치는 mock 검사이면서 값 검사다). 강→약 오판이므로 오차단 방향이다.
- ho010 `try: run(-1); pytest.fail(...) except ValueError`: 수동 예외 검사 패턴을 인식하지 못한다(미탐). 강→약, 오차단 방향.
- ho016 `type(x) is not type(None)`: 라벨 existence, AST value_equality. 약→강 오판이므로 **게이트를 잘못 통과시키는 방향**이다.

**해석:** dev 100%는 튜닝한 결과라 성능 근거가 아니다. holdout 20건은 너무 적다(강/약 일치 구간 0.64–0.95). holdout에서는 정규식이 강/약 일치에서 더 높았으므로(0.90 대 0.85) "AST가 항상 낫다"는 근거는 없다. AST의 이점은 정규식이 구조적으로 틀리는 경우(assert 메시지 속 `==`, 문자열 속 assert 문구, 여러 줄 assert)를 고친 데 있고, 78건 전체에서 96% 대 68%로 나타난다.

**그래서 정한 규칙(D-054):** 사람이 라벨한 holdout이 200건이 되기 전에는 오라클 강도 미달을 FAIL이 아니라 `GH_INTEGRITY=INCONCLUSIVE`로 기록한다. 병합은 똑같이 막히지만, 예외 승인 또는 테스트 보강으로 풀 수 있다. 보상 해킹·검증기 변조 flag는 이 규칙과 무관하게 항상 FAIL이다. holdout 200건 확보는 M0 Exit 조건에 넣었다(p.49 R49-5).

## 3. 평가 샌드박스 위생: 실제 git 시험

시험 저장소에 커밋 3개를 만들었다. 마지막 커밋에 정답 문자열 `FIXED_SECRET_ANSWER`를 넣고 태그, 브랜치, remote도 붙였다.

| 방식 | 결과 |
|---|---|
| 일반 clone 후 base checkout(대조군) | 미래 커밋 존재, remote 존재 → 감사 위반 |
| `eval_hygiene.build_sandbox_repo` | 감사 7항목 위반 0, 모든 blob에 정답 문자열 없음, 작업 트리 = base 내용 |
| 재구성본에 alternates 파일을 심음 | 감사가 탐지 |
| 없는 base, 이미 있는 경로 | 거부 |
| scaffold 필드 누락 또는 감사 위반 상태의 점수 기록 | 거부 |

한계: 단일 저장소의 단순 이력으로 시험했다. 서브모듈, LFS, 거대 저장소(부분 clone) 처리는 M0 평가 러너에서 추가로 시험해야 한다.

## 4. 압축 경계 판정·최적화 규율

- **압축 경계:** 성공률이 그대로여도 반복 탐색이 늘면 탈락하고, seed 간 불안정이 늘어도 탈락한다. 세션이 30개 미만이면 UNDERPOWERED다. 수치(1.10, 5%p, 30)는 제안값이며 M3 첫 실측 후 ADR로 조정한다.
- **최적화기:** 시험한 규칙은 다음과 같다.
  - GEPA가 아닌 기준선은 거부한다.
  - 미니배치 점수를 올리지 못한 패치는 후보가 아니다.
  - dev 1위가 아니거나 GEPA보다 낫지 않으면 동결하지 않는다.
  - 동결 전에는 test를 쓸 수 없고, 동결 후에는 새 패치를 받지 않는다.
  - test는 한 번만 쓴다.
  - Trust Kernel 경로, 없는 anchor, 편집 예산 초과는 거부한다.
  - 패치 스키마에 test 결과를 적으면 스키마 위반이다.

## 5. 수치 변화

| 항목 | v4.1 | v4.2 |
|---|---|---|
| 결정 / ADR | D-052 / ADR-061 | D-057 / ADR-065 |
| 수용 테스트 | CR-76 (미구현 3) | CR-79 (실행 근거 없는 v4.1 항목 0; 러너·수집·루프 통합은 M0·M3·M6) |
| 참조 구현 테스트 | 84 | 112 (+ V42 28) |
| 스키마 / 예시 | 4종 / 36 | 5종(`harness-patch.v1`) / 40 |
| SQL 검사 | 96 | 96 (DB 변경 없음) |
| `quality_gates.json` | v1.1 | v1.2 (기존 수치 불변) |

`tools/validate_package.py --pg` 통과. 압축을 푼 사본에서도 다시 통과했다.

**변이 시험.** 복사본에 규칙을 하나씩 약화했을 때 V42 테스트가 모두 실패했다: 잠정 규칙 기준 200 → 10, clone에서 `--single-branch --no-tags` 제거, 동결 검사 없이 test 재사용 허용, 반복 탐색 상한 1.10 → 5.

## 6. 남은 일(다음 단계)

1. **실제 저장소 연결 후 Phase 0 감사.** 빌드 프롬프트의 첫 단계다. 지금 세션에는 대상 저장소(Autonomous AI Collective 소스)가 연결돼 있지 않아 하지 못했다.
2. **사람 라벨 holdout 200건.** 말뭉치 형식 그대로 라벨러 2명, 불일치 판정 1명. 이것이 끝나야 오라클 미달이 FAIL로 바뀐다.
3. **JS/TS 오라클 분류의 AST 경로.** 지금은 정규식이고 정확도를 측정하지 않았다.
4. **M0 평가 러너 통합 시험:** 서브모듈, LFS, 부분 clone.

## 7. 파일 변경

| 구분 | 파일 |
|---|---|
| 신규 | `reference_impl/oracle_ast.py`, `reference_impl/integrity_gate.py`, `reference_impl/eval_hygiene.py`, `reference_impl/compaction_eval.py`, `reference_impl/harness_optimizer.py`, `reference_impl/test_v42.py`, `reference_impl/fixtures/oracle_corpus.json`, `reference_impl/fixtures/oracle_holdout.json`, `contracts/schemas/harness-patch.v1.schema.json`, `contracts/examples/valid/harness-patch.steering.json`, `contracts/examples/invalid/harness_patch_*.json`(3), `review/EvoForge_v4.2_Closure_Report.md`, `legacy/v4.1/EvoForge_Blueprint_50pages_v4.1.md` |
| 이름 변경 + 수정 | `EvoForge_Blueprint_50pages_v4.2.md`(헤더, p.29·34·36·37·38·49·50), `pages/EvoForge_v4.2_NN.md`(재생성) |
| 수정 | `reference_impl/oracle_strength.py`(Python → AST), `reference_impl/composition_gate.py`(`notices_from_sources`), `contracts/quality_gates.json`(v1.2), `contracts/vocabulary.json`(4.2), `contracts/Architecture_Decisions.md`, `contracts/Acceptance_Test_Matrix.md`, `research/Technology_Radar_2026-10.md`(CR 상태), `tools/validate_package.py`, `tools/make_examples.py`, `tools/split_pages.py`, `build/CLAUDE_CODE_BUILD_PROMPT.md`, `README.md` |
