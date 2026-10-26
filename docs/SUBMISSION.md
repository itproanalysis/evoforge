# Submission — EvoForge (Indie, Push the Frontier)

## 60초 요약
여러 AI를 묶는 게 아니라, **검증된 PR 1건**을 만드는 기계. Builder(Muse Spark 1.3) → 독립 Critic(명세-선행 봉인) → 결정적 게이트(GH_INTEGRITY/GC_COMPOSITION + authorize_merge) → Evidence. 약한 테스트·보상 해킹은 병합 차단.

## Live
- Web (Cloud Run): $WEB_URL
- API (Cloud Run): $API_URL/healthz
- Demo repo PR: $PR_URL (Evidence 첨부)

## 3분 데모 스크립트
1. Mission Control에 목표 입력 ("Fix flaky login retry") → Generate (0:30)
2. Gates INCONCLUSIVE/FAIL이면 왜 막혔는지 oracle_strength 수치로 설명 (1:00)
3. Lab에서 Critic 봉인 테스트 → PASS → PR 생성, Evidence Timeline에서 간선 추적 (1:00)
4. Budget 초과 시 402 fail-closed, 위생 러너 audit 7항목 (0:30)

## 아키텍처 1p
`Next.js (Run) → FastAPI (Run) → Meta Model API (muse-spark-1.3) / GitHub / Cloud SQL PG (core+context_plane, RLS) / GCS evidence (CMEK) / Secret Manager`. 모든 모델 호출: allowlist → reserve_cost → side_effect_intents → 호출 → receipt → settle. 금액 정수 cents. LiteLLM 없음, BYOK 없음.

## 재현
```bash
python -I docs/evoforge-v4.2/tools/validate_package.py
pytest -q services/api/tests
curl $API_URL/healthz
```

## 사용 모델
- muse-spark-1.3 (Builder/Critic), muse-wonder-1.0 (HIGH/CRITICAL 옵션), Base https://api.meta.ai/v1
