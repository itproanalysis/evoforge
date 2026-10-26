# CI 계약 검증과 웹 빌드

2026-10-27. API 개발과 분리해 검증 환경을 보강했다. 계약 정본은 변경하지 않았다.

## 수정한 실행 경로

- GitHub Actions `contracts`: 검증기에 필요한 `jsonschema`를 명시적으로 설치하고,
  일회용 PostgreSQL 15 서비스에 `validate_package.py --pg`를 실행한다.
  기존 설정에는 의존성 설치와 SQL 검사가 없었다.
- Cloud Build `validate`: `python:3.12-slim-bookworm` 컨테이너 안에 Git과 PostgreSQL 15를 설치하고
  자체 클러스터를 시작한다. 검증 종료 시 클러스터를 중지한다.
  `PGHOST`는 컨테이너의 로컬 소켓으로 고정하며 배포용 `DATABASE_URL`을 사용하지 않는다.
  기존 설정은 `pyyaml`만 설치해 `jsonschema`·Git·PostgreSQL이 없었다.
- 두 Cloud Build 설정은 동일하다. API 이미지의 컨텍스트는 저장소 루트,
  웹 이미지의 컨텍스트는 `apps/web`로 설정했다.
  웹 Dockerfile에서 복사하는 `public/`은 빈 디렉터리도 체크아웃에 남도록 `.gitkeep`을 추가했다.
- GitHub Actions `web`: `npm ci` 후 프로덕션 빌드를 검사한다.
- Muse Spark의 모델 설정은 유지했다.

## 로컬 검증 근거

- 시스템 패키지를 상속하지 않는 임시 Python 3.12 가상환경에서 검증 의존성을 새로 설치했다.
  계약 패키지 검사 C1–C7·C9가 통과했고, 참조 테스트 112개가 통과했다.
- `npm run build`: 페이지·타입 검사와 프로덕션 빌드 성공.
- `python -m pytest services/api -q`: `eff542f` 기준 API 테스트 93개 통과.
- Bash 문법 검사, YAML 파싱, Cloud Build 설정 일치, Dockerfile·컨텍스트 경로 확인 통과.
- 최초 CI 구성 시에는 PostgreSQL C8 검사와 컨테이너 이미지를 실행하지 못했다.
  후속 작업에서 Windows용 임시 PostgreSQL 15.19 실행기로 C8 SQL 96개와 참조 112개,
  C1–C9 전체의 실제 통과를 확인했다. [로컬 SQL 검증 절차](LOCAL_POSTGRES_VALIDATION.md)를 참고한다.
- Docker 이미지, GitHub Actions, Cloud Build의 실제 실행 결과는 아직 확인하지 않았다.

## 다음 실행에서 확인할 명령

Docker가 있는 Windows 개발 환경에서 SQL 검증 컨테이너 전체 실행:

```powershell
docker run --rm --mount "type=bind,source=C:\evo_forge,target=/workspace,readonly" --workdir /workspace python:3.12-slim-bookworm bash infra/ci/validate_contracts.sh
```

저장소 루트에서 배포 이미지 빌드 확인:

```powershell
docker build -f services/api/Dockerfile -t evoforge-api:check .
docker build -f apps/web/Dockerfile -t evoforge-web:check apps/web
```

SQL 테스트는 역할과 임시 데이터베이스를 생성·삭제하므로 전용 테스트 서버에서 실행한다.
배포 SQL 마이그레이션의 권한·연결 및 실제 비용 예약·병합 승인 통합은 별도 검증 항목이다.
