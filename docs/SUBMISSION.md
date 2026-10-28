# Submission — EvoForge (Indie, Push the Frontier)

## 60초 요약
여러 AI를 묶는 게 아니라, **검증된 PR 1건**을 만드는 기계. Builder(Muse Spark 1.3) → 독립 Critic(명세-선행 봉인) → 결정적 게이트(GH_INTEGRITY/GC_COMPOSITION + authorize_merge) → Evidence. 약한 테스트·보상 해킹은 병합 차단.

## Live (실측됨 2026-10-27)
- Web: https://evoforge-web-230852112787.asia-northeast3.run.app
- API: https://evoforge-api-230852112787.asia-northeast3.run.app (private IAM, 웹 same-origin 프록시 경유)
- **PASS 체인 → 실제 PR**: Mission `msn_5af789b9a5a4` ("calc.py add 수정") CREATED→GENERATED→REVIEWED→RAN→PR_OPENED
  - Builder 실측 1줄 패치 (`a - b` → `a + b`), Critic PASS (sealed 3종), 위생 샌드박스 visible 3/3 + held-out 3/3
  - GH_INTEGRITY/GC_COMPOSITION/G2 전부 PASS → https://github.com/itproanalysis/evoforge-target/pull/4 (MERGED, 07c19dde)
- **CLOSED LOOP (WVI=1)**: Mission `msn_a3b777e1cfcf` ("calc.py mul 수정") 전 체인 → https://github.com/itproanalysis/evoforge-target/pull/6 → MERGED (2816260d) → `POST /v1/outcomes` → `outcome_status: VALIDATED`, dashboard `validated_improvements: 1`
  - 재현 중 blind diff(`hunk does not apply`)·테스트 파일명 충돌을 잡아 `target_paths` 컨텍스트 주입·증거 기반 고유 파일명으로 수정 (둘 다 테스트 추가)
  - Outcome은 postgres evidence에서 복구되므로 재배포 후에도 WVI 유지 (복구 경로 테스트 포함)
- **FAIL 체인 (차단 증명)**: Mission `msn_f74933cc7eda` ("webhook 403") — Critic FAIL + held-out 0/3 → gap +1.000 → GH_INTEGRITY FAIL → PR 차단, Dashboard blocked_merges 1
- **X_SINGLE 베이스라인 (실측)**: `bl_a42d827d2917`, muse-spark-1.3 원샷, n=12, pass 2/12 (0.167), 비용 1440¢, 위생 7/7 전부 clean, 봉인 해시만 노출
  - 가족별: algorithmic_optimization 1/2, parallel_multi_file 1/2, 나머지 0 — 원샷의 한계가 정직하게 드러남. X_ADAPTIVE(크리틱+실행 루프) 비교의 분모
- Ledger: spent 360¢·unknown 0 · base == target main HEAD (실제 repo 실행)

## 3분 데모 스크립트
1. Mission Control에 목표 입력 → Generate: Builder 실측 패치+테스트 (0:30)
2. Review: Critic 봉인 3종 + FAIL 근거 (라우트 미연결 등) — 남이 쓴 테스트로 막는다 (1:00)
3. Run: 샌드박스 실행 visible 3/3 vs held-out 0/3, gap 수치로 GH_INTEGRITY FAIL → PR 버튼 비활성 (1:00)
4. Dashboard: spent/reserved/unknown_holds, 증거 체인 드릴다운 (0:30)

## 아키텍처 1p
`Next.js (Run, same-origin 프록시) → FastAPI (Run, private IAM) → Meta Model API (muse-spark-1.3) / GitHub / Cloud SQL PG15 (core+context_plane+001~010, RLS 강제, `EVO_STATE_BACKEND=postgres`) / Secret Manager`. 모든 모델 호출: allowlist → reserve_cost → side_effect_intents → 호출 → receipt → settle. 금액 정수 cents. LiteLLM 없음, BYOK 없음.
- 영속성 실측: 동일 이미지 재배포 후 evidence 조회 성공 (메모리 시대에는 매 배포 초기화됐음). 마이그레이션은 `infra/gcp/migrate_once.py` (ops.applied_files 추적, 1회성), 빌드 내 psql은 green-skip.

## 재현
```bash
python -I docs/evoforge-v4.2/tools/validate_package.py  # PASS
pytest -q services/api/tests                              # 450 passed
curl https://evoforge-web-230852112787.asia-northeast3.run.app/api/evoforge/v1/dashboard
```

## 사용 모델
- muse-spark-1.3 (Builder/Critic), Base https://api.meta.ai/v1
