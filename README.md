# EvoForge — Verifiable AI Engineering Collective

> Meta Global AI Developer Hackathon (Indie track) · Theme: Push the Frontier
> Stack: Muse Spark 1.3 / Muse Wonder via Meta Model API (`https://api.meta.ai/v1`) · FastAPI (Cloud Run) · Next.js (Cloud Run) · Cloud SQL Postgres · GCS + KMS · Secret Manager
> Spec: `docs/evoforge-v4.2/` (v4.2-executable-closure, D-001~D-057, CR-01~79). 문서–계약 불일치 시 계약이 정본.

## 왜 이기나 (심사 기준 대응)

- **Technical ambition:** 5좌석 Adaptive Collective가 아니라 기본 1 Builder + 1 독립 Critic. HIGH/CRITICAL은 명세-선행 봉인 테스트 + 컨텍스트 독립 검증자 (Who Verifies the Builder). 모든 병합은 결정적 게이트 `G0/G1/G2/GH_INTEGRITY/GR/G4 + GC_COMPOSITION` + `core.authorize_merge` DB 강제.
- **Whether it works:** GitHub 저장소 연결 → 목표 → Builder 패치 (Muse Spark) → Critic 봉인 테스트 → 게이트 → 검증 PR. 전 간선 event_id로 드릴다운, `증거 부족`은 숨기지 않음.
- **No reward hacking:** `reward_hack.py` Δ + held-out(≥3/task, compositional+negative) + `oracle_ast.py` 강도 판정. holdout 200건 미만은 `INCONCLUSIVE` (병합 차단, 예외 승인으로만 해제).

## Repo layout

```
C:\evo_forge\
  docs/evoforge-v4.2/      # spec 정본 (복사, 수정 금지)
  services/api/            # FastAPI: broker, gates, commands, merge policy (Cloud Run)
  apps/web/                # Next.js: Mission Control, Improvement Lab, Evidence (Cloud Run)
  packages/contracts/      # quality_gates.json, schemas symlink/copy (공유)
  infra/gcp/               # Terraform: run, sql, gcs, kms, secret, vpc, build
  evals/                   # sealed set + hygiene runner
```

## Quickstart (local)

```powershell
# 1) API (Python 3.12+, stdlib gates + fastapi)
cd C:\evo_forge\services\api
python -m venv .venv; .\.venv\Scripts\Activate
pip install -r requirements.txt
copy .env.example .env  # MODEL_API_KEY, DATABASE_URL, GITHUB_APP_*
pytest -q               # 112 gates 그대로 통과해야 함
uvicorn main:app --reload --port 8080

# 2) Web
cd C:\evo_forge\apps\web
pnpm install; pnpm dev  # http://localhost:3000
```

## Contracts first

- `validate`: `python -I docs/evoforge-v4.2/tools/validate_package.py --pg` (CI 필수)
- 금지: Caveman BSL 경로 열람/복사/의존, LiteLLM 기본 의존, BYOK UI, `reserve_cost` 우회 호출, float 금액, 패킷 내 LLM 요약(M3까지), 부작용 도구 투기 실행.
- 금액은 NUMERIC(원자 단위 int), 모든 병합은 `core.authorize_merge` 경유.

## GCP (real service)

- `infra/gcp/`: `terraform apply -var project=... -var region=asia-northeast3`
- Cloud SQL Postgres 15 (private IP, `core_DRAFT.sql` + `context_plane_DRAFT.sql`을 마이그레이션으로, CHECK/트리거/RLS/GRANT 불변)
- Cloud Run: `evoforge-api`, `evoforge-web` (min 0, max 20, concurrency 80)
- GCS `evoforge-evidence-*` (uniform access, CMEK) + KMS DEK per blob
- Secret Manager: `MODEL_API_KEY`, `GITHUB_APP_*`, `KMS_*` (Broker 신원만 복호화)
- Cloud Build: `validate_package --pg` + pytest + `pnpm build` 통과해야 deploy

## Roadmap (10일)

- D1: repo + broker(Meta) + Mission Control 뼈대
- D2-3: Builder/Critic 2-seat + GH_INTEGRITY + Evidence
- D4-5: GitHub PR 실연 + cost ledger + hygiene runner
- D6-7: X_SINGLE vs X_ADAPTIVE 계측 + GCP 배포 + 데모 영상
- D8-9: 심사 제출 (repo, live URL, 3분 영상, 아키텍처 1p)
