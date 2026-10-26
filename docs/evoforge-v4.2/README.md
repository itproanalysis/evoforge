# EvoForge v4.2 통합 구현 패키지 (실행 계약 마감판)

v4.0 통합 정본에 논문 33건(31건은 2025-12 ~ 2026-10 공개)과 공개 벤치마크 자료의 검토 결과를 반영한 패키지다. 채택분은 기획서의 해당 페이지와 계약(DB·스키마 규칙·품질 수치·참조 구현)에 직접 들어갔고, 덧붙인 버전 절은 없다. 무엇을 왜 바꿨는지는 `review/EvoForge_v4.1_Research_Upgrade_Report.md`, 논문별 근거 등급·채택 고리·수용 테스트는 `research/Technology_Radar_2026-10.md`에 있다. v4.2는 v4.1이 미구현·미측정으로 남긴 항목(오라클 분류기 정확도, 평가 샌드박스 위생, 압축 경계 판정, M6 최적화 규율)을 실행 가능한 계약으로 닫았다: `review/EvoForge_v4.2_Closure_Report.md`.

| 경로 | 내용 |
|---|---|
| `EvoForge_Blueprint_50pages_v4.2.md` | 50페이지 통합 기획서(정본). 결정 레지스터 D-001~D-057 |
| `pages/` | 위 문서의 50개 분리본(바이트 동일, `tools/split_pages.py`로 생성) |
| `research/Technology_Radar_2026-10.md` | 논문 33건 + 벤치마크 자료: 제출일·근거 등급(A~D)·논문 보고치·고리(ADOPT/TRIAL/ASSESS/HOLD)·반영 위치·수용 테스트 |
| `contracts/quality_gates.json` | Quality Gate Framework v1.2(정본). v4.2: 오라클 분류기 정확도·잠정 규칙, 평가 위생 감사·scaffold 필드, 압축 경계 판정 수치, 최적화기 상태·보호 경로. v4.1 섹션: 독립성·리뷰 신호·분할·결합·오라클·보상 해킹·선택·투기·cascade·PPI·기억·캐시 배치·압축 평가·평가 위생·최적화기 |
| `contracts/vocabulary.json` | 모든 열거값·상태·이벤트·도구명 + 폐기 용어 대응표(v4.2) |
| `contracts/Context_Mesh_Spec.md` | 컨텍스트 계층 구현 계약(S11 캐시 배치, 경계 단위 평가 포함) |
| `contracts/Architecture_Decisions.md` | ADR-035~065 |
| `contracts/Acceptance_Test_Matrix.md` | CR-01~79과 실행 근거 |
| `contracts/schemas/` | `context-packet.v2`, `evidence-retrieval.v1`, `provider-usage-receipt.v1`(플랫폼 키), `provider-capability.v1`, `harness-patch.v1`(M6 변이 단위) |
| `contracts/examples/` | valid 7개, invalid 33개 + `contracts/examples/invalid/EXPECTATIONS.json` |
| `contracts/registry/provider_capabilities.seed.json` | 공급사 캐시 규약 시드(2026-10-25, 14일 만료) |
| `contracts/sql/core_DRAFT.sql` | 테넌시·명령·상태 머신·Lease fencing·병합 승인(무결성·결합 게이트, 명세 선행 독립 검증, 리뷰어 자격)·이벤트·부작용·예산·크레딧·원장 |
| `contracts/sql/context_plane_DRAFT.sql` | Evidence Vault 메타데이터·패킷·ref·접근 로그·커버리지·삭제 |
| `contracts/sql/run_sql_tests.sh` | 두 스키마 + 96개 검사를 임시 DB에서 실행 |
| `reference_impl/` | 결정적 codec, Fidelity Gate, 비용 모델, 품질 판정 + v4.1 성능 모듈(`reference_impl/partitioner.py`, `reference_impl/composition_gate.py`, `reference_impl/oracle_strength.py`, `reference_impl/reward_hack.py`, `reference_impl/selection.py`, `reference_impl/review_policy.py`, `reference_impl/speculative.py`, `reference_impl/cascade.py`, `reference_impl/ppi.py`, `reference_impl/memory_policy.py`) + v4.2 모듈(`reference_impl/oracle_ast.py`, `reference_impl/integrity_gate.py`, `reference_impl/eval_hygiene.py`, `reference_impl/compaction_eval.py`, `reference_impl/harness_optimizer.py`)과 오라클 말뭉치(`reference_impl/fixtures/oracle_corpus.json`, `reference_impl/fixtures/oracle_holdout.json`) — 테스트 112개, stdlib만 사용(평가 위생 시험은 `git` CLI 필요) |
| `tools/validate_package.py` | C1–C9 검사(스키마·예시·의미 규칙 S1–S11·어휘·페이지·README·참조 구현·SQL·추적성) |
| `build/CLAUDE_CODE_BUILD_PROMPT.md` | M0~M3 Phase 0~7 실행, 기법별 플래그·절제 실험, Diff 보고, 확인 대기 |
| `review/` | v4.0 통합 보고서, v4.1 연구 반영 보고서, v4.2 마감 보고서 |
| `legacy/` | v3.5 계약, v3.6 기획서·계약·검토 보고서, v4.0·v4.1 기획서(수정하지 않음) |
| `reference/` | v3.4 참조 자료(원본, 누락 파일 주석만 추가) |

## 검증
```bash
python3 -I tools/validate_package.py                                   # jsonschema 필요
PGHOST=... PGUSER=<superuser> python3 -I tools/validate_package.py --pg  # 임시 DB 생성·삭제
```

## 상태
설계 패키지다. 프로덕션 코드, 공급사 실호출, 실제 마이그레이션, 부하·침투 시험, 공급사 캐시 실측, v4.1 기법의 실제 성능 측정은 하지 않았다. v4.2의 오라클 분류기 정확도는 직접 만든 소규모 말뭉치(78건)에서 잰 값이고 외부 벤치마크가 아니다. 실행해서 통과한 것은 계약 수준 검사다. **논문 수치는 각 논문 설정의 결과이며 EvoForge 성과가 아니다.** SLO·가격·일정·10X는 제안값 또는 목표다.
