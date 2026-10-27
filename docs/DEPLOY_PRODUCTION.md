# EvoForge 정식 서비스 배포 (GCP Cloud Run, asia-northeast3)

프로젝트: `evoforge-prod-4ff3` (결제 연결, 조직 없음). 비밀 값은 Secret Manager에만 있고 저장소·로그·채팅에 쓰지 않는다.

## 구성

| 서비스 | 공개 여부 | 서비스 계정 | 비밀 | 역할 |
|---|---|---|---|---|
| `evoforge-web` | 공개(앱 로그인) | `evoforge-web@` | `EVO_SESSION_SECRET`, `EVO_OWNER_PASSWORD_HASH` | 로그인·세션, `/api/evoforge/*` 프록시(메타데이터 ID 토큰으로 API 호출) |
| `evoforge-api` | 비공개(web SA만 invoker) | `evoforge-api@` | `MODEL_API_KEY`, `GITHUB_TOKEN` | Broker·게이트·증거·PR, GitHub 체크아웃, Runner 호출 |
| `evoforge-runner` | 비공개(api SA만 invoker) | `evoforge-runner@` (역할 없음) | 없음 | base-only 번들로 후보·봉인 테스트 실행, 결과 수치만 반환 |

- API: `EVO_REQUIRE_ID_TOKEN=1`, `EVO_API_URL`=자기 URL, `EVO_WEB_SERVICE_ACCOUNT`=web SA, `EVO_ALLOW_LOCAL_REPOS=0`,
  `GITHUB_REPO`=대상 저장소, `EVO_RUNNER_URL`/`EVO_RUNNER_AUDIENCE`=Runner URL, CORS 허용 출처 없음(동일 출처 프록시만).
- API는 요청 경로가 Cloud SQL로 옮겨질 때까지 `min=max=1` 인스턴스(메모리 증거·원장 일관성).
- 소유자 로그인: 사용자 `itproanalysis`. 비밀번호는 `EVO_OWNER_PASSWORD`(어떤 서비스 계정도 읽을 수 없음)에서 소유자만 조회:
  `gcloud secrets versions access latest --secret=EVO_OWNER_PASSWORD --project=evoforge-prod-4ff3`

## 배포

```bash
PROJECT=evoforge-prod-4ff3 TAG=$(git rev-parse --short HEAD) bash infra/gcp/deploy_prod.sh
```

`cloudbuild.prod.yaml`이 `requirements.txt`만으로 만든 깨끗한 환경에서 API 테스트를 통과해야 이미지 3개를 만든다.

## 운영 전 남은 조치

- `GITHUB_TOKEN`: 현재 소유자 `gh` 로그인 토큰(전 저장소 권한). 대상 저장소 한정 fine-grained 토큰 또는 GitHub App으로 교체.
- Cloud SQL 연결(P0-2, Codex 범위) 후 API 인스턴스 수 제한 해제.
- Runner는 Cloud Run gen2 샌드박스 + 무권한 SA. 네트워크 egress 차단은 미적용(VPC egress 제어 필요).
