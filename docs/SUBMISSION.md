# Submission — EvoForge (Indie, Push the Frontier)

## 60초 요약
여러 AI를 묶는 게 아니라, **검증된 PR 1건**을 만드는 기계. Builder(Muse Spark 1.3) → 독립 Critic(명세-선행 봉인) → 결정적 게이트(GH_INTEGRITY/GC_COMPOSITION + authorize_merge) → Evidence. 약한 테스트·보상 해킹은 병합 차단.

## Live (실측됨 2026-10-27)
- Web: https://evoforge-web-230852112787.asia-northeast3.run.app
- API: https://evoforge-api-230852112787.asia-northeast3.run.app (private IAM, 웹 same-origin 프록시 경유)
- Mission `msn_f74933cc7eda` ("Reject unsigned webhook payloads"): CREATED→GENERATED→REVIEWED→RAN 전 체인 실측
  - Builder: `stub:false`, muse-spark-1.3, 2736 토큰 (HMAC 서명 헬퍼 + 테스트 3종 생성)
  - Critic: Phase A sealed 3종 (negative/boundary/compositional, 6368 토큰) + Phase B review FAIL (7209 토큰) — "라우트 미연결, CI 없음" 실질 지적
  - Run (위생 샌드박스): visible 3/3 PASS, held-out 0/3 FAIL → gap +1.000 (95% LB +0.206) → GH_INTEGRITY FAIL, G2 FAIL → 병합 차단
  - Ledger: spent 360¢, unknown 0 · Dashboard: RAN 1, blocked_merges 1
- Mission `msn_db7466b500e0` ("Fix flaky login retry"): Builder 실호출 확인 (exponential backoff 패치)

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
