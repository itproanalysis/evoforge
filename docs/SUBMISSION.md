# Submission — EvoForge (Indie, Push the Frontier)

## 60초 요약
여러 AI를 묶는 게 아니라, **검증된 PR 1건**을 만드는 기계. Builder(Muse Spark 1.3) → 독립 Critic(명세-선행 봉인) → 결정적 게이트(GH_INTEGRITY/GC_COMPOSITION + authorize_merge) → Evidence. 약한 테스트·보상 해킹은 병합 차단.

## Live (실측됨 2026-10-27)
- Web: https://evoforge-web-230852112787.asia-northeast3.run.app
- API: https://evoforge-api-230852112787.asia-northeast3.run.app (private IAM, 웹 same-origin 프록시 경유)
- **PASS 체인 → 실제 PR**: Mission `msn_5af789b9a5a4` ("calc.py add 수정") CREATED→GENERATED→REVIEWED→RAN→PR_OPENED
  - Builder 실측 1줄 패치 (`a - b` → `a + b`), Critic PASS (sealed 3종), 위생 샌드박스 visible 3/3 + held-out 3/3
  - GH_INTEGRITY/GC_COMPOSITION/G2 전부 PASS → https://github.com/itproanalysis/evoforge-target/pull/4 (OPEN, +10/-1)
- **FAIL 체인 (차단 증명)**: Mission `msn_f74933cc7eda` ("webhook 403") — Critic FAIL + held-out 0/3 → gap +1.000 → GH_INTEGRITY FAIL → PR 차단, Dashboard blocked_merges 1
- Ledger: spent 360¢·unknown 0 · base == target main HEAD (실제 repo 실행)

## 3분 데모 스크립트
1. Mission Control에 목표 입력 → Generate: Builder 실측 패치+테스트 (0:30)
2. Review: Critic 봉인 3종 + FAIL 근거 (라우트 미연결 등) — 남이 쓴 테스트로 막는다 (1:00)
3. Run: 샌드박스 실행 visible 3/3 vs held-out 0/3, gap 수치로 GH_INTEGRITY FAIL → PR 버튼 비활성 (1:00)
4. Dashboard: spent/reserved/unknown_holds, 증거 체인 드릴다운 (0:30)

## 아키텍처 1p
`Next.js (Run, same-origin 프록시) → FastAPI (Run, private IAM) → Meta Model API (muse-spark-1.3) / GitHub / GCS evidence / Secret Manager`. 모든 모델 호출: allowlist → reserve_cost → side_effect_intents → 호출 → receipt → settle. 금액 정수 cents. LiteLLM 없음, BYOK 없음. Cloud SQL은 terraform 준비됨 (현재 fallback 스토어, 다음 빌드에서 마이그레이션).

## 재현
```bash
python -I docs/evoforge-v4.2/tools/validate_package.py  # PASS
pytest -q services/api/tests                              # 450 passed
curl https://evoforge-web-230852112787.asia-northeast3.run.app/api/evoforge/v1/dashboard
```

## 사용 모델
- muse-spark-1.3 (Builder/Critic), Base https://api.meta.ai/v1
