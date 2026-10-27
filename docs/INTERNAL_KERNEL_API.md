# 인증된 PostgreSQL 내부 API

2026-10-27. `/v1/kernel`에 PostgreSQL Trust Kernel 어댑터를 연결했다.
실제 PostgreSQL 15.19에서 HTTP 요청을 포함한 DB 수용 테스트 **25개**를 통과했다.
키·스코프가 없는 기본 환경에서는 경로가 503으로 닫힌다.

## 서버 설정

`DATABASE_URL`, `EVO_TENANT_ID`, `EVO_PROJECT_ID`, `EVO_KERNEL_TOKEN`을 서버에 설정한다.
토큰은 무작위 32자 이상의 ASCII 비밀 값이어야 한다. 토큰과 DSN은 브라우저 번들에 넣지 않는다.
서버 DB 로그인에는 `core_app`, `ctx_gateway` 역할 멤버십과 사전 생성한 프로젝트·예산·크레딧이 필요하다.
API가 스키마나 크레딧을 자동 생성하지 않는다.

로컬 API 폴더에서 `.env`를 사용하는 경우:

```powershell
uvicorn main:app --env-file .env --reload --port 8080
```

Google ID 인증을 켠 배포에서는 `Authorization: Bearer <approved Google ID token>`과
`X-Evoforge-Kernel-Token: <service token>`을 함께 보낸다. 기존 audience·허용 서비스 계정 검사와
내부 토큰 검사를 모두 통과해야 한다. 이 변경은 Google/IAM 인증이나 web BFF의 커널 경로 차단을 우회하지 않는다.
로컬에서 ID 인증을 끈 기존 호출은 `Authorization: Bearer <service token>`도 호환한다.
명시한 커널 헤더가 틀리면 유효한 다른 헤더로 대체하지 않는다.
스코프는 서버 환경에서만 결정하며 요청의 `tenant_id`, `project_id`, `dsn` 필드를 거부한다.
이 서비스 토큰은 내부 호출용이다. 브라우저 사용자 로그인·프로젝트 멤버십 연결은 남아 있다.

## 경로

| 메서드·경로 | 동작 |
|---|---|
| `POST /v1/kernel/reservations` | UUID `call_id`, `period_start`, 양의 int64 `amount_micros`로 예약 |
| `GET /v1/kernel/reservations/{call_id}` | 해당 서버 스코프의 예약·외부 결과 상태 조회 |
| `POST .../{call_id}/sent` | provider 호출 전 SENT 기록 |
| `POST .../{call_id}/unknown` | 결과 불명 기록, 금액 계속 예약 |
| `POST .../{call_id}/release-not-accepted` | 확실한 미접수 예약만 해제 |
| `POST .../{call_id}/settle` | `receipt_id`, `customer_micros`로 바인딩된 영수증 정산 |
| `POST /v1/kernel/merge-authorizations` | 후보·현재 head·policy hash를 DB 승인 함수로 확인 |
| `POST /v1/kernel/receipts` | 정본 영수증 문서 검증·원자적 저장 |
| `GET /v1/kernel/receipts/{receipt_id}` | 해당 스코프의 문서와 원장 entry ID 조회 |
| `POST /v1/kernel/receipts/{receipt_id}/settle` | 본문 `{}`, 저장 금액으로 정산 |
| `POST /v1/kernel/builder-calls` | 기존 패킷·동의·lease 검증과 예약의 원자적 바인딩 |
| `GET /v1/kernel/builder-calls/{call_id}` | Builder 바인딩·예약 상태 조회 |
| `POST /v1/kernel/commands` | BUILD/ASK canonical 접수·멱등 키·위험 확인 |
| `GET /v1/kernel/commands/{id}` | 서버 증거에 바인딩된 명령·이력·완료 응답 조회 |
| `POST /v1/kernel/commands/{id}/dispatch` | 단일 실행권 기록, 본문 `{}` |
| `POST /v1/kernel/commands/{id}/complete` | 같은 scope/명령의 생성 증거와 일치하는 응답 저장 |
| `POST /v1/kernel/candidate-runs` | 정산된 Builder 바인딩·커밋 head의 서버 Runner 증거로 G2 기록 |
| `GET /v1/kernel/candidates/{id}/runner-evidence/{evidence_id}` | 해당 후보의 G2 증거 연결 조회 |

위의 `...`는 `/v1/kernel/reservations`다. 병합 승인은 후보 상태나 GitHub를 변경하지 않는다.
현재 head·정책·증거가 바뀌면 실제 병합 직전에 다시 DB 승인을 거쳐야 한다.

인증 실패는 401, 입력 오류는 422, 예산/크레딧 거부는 402,
없는 자원과 다른 스코프 자원은 같은 404, 상태·영수증 위반은 409,
서버 설정 또는 DB 연결 문제는 503이다. 오류 본문에는 DSN·토큰 원문을 넣지 않는다.
DB 오류를 메모리 원장으로 대체하지 않는다.

영수증 확장 마이그레이션·계약·저장 금액 정산의 범위와 제한은
[영수증 문서 연결](RECEIPT_PERSISTENCE.md)을 따른다. 스키마와 digest는 공급사 청구 입증이 아니다.

Builder 바인딩은 `EVO_PRICE_TABLE_VERSION`과 확장 002를 요구한다.
전송 전 재검증과 정확한 범위는 [BUILDER_PREFLIGHT.md](BUILDER_PREFLIGHT.md)를 따른다.
명령의 actor 설정·확장 004·응답/증거 FK는 [명령 저장](COMMAND_PERSISTENCE.md),
Runner 빌드 식별자·확장 005·G2만 기록하는 범위는 [Runner/core 연결](RUNNER_CORE_EVIDENCE.md)을 따른다.

## 검증

```powershell
& '.\.local\venv-api\Scripts\python.exe' -m pytest services/api/tests -q
& '.\.local\venv-api\Scripts\python.exe' tools/validate_local_pg.py --kernel-tests
```

- API 테스트 139개 통과. DB 미지정 시 실제 DB 모듈 1개 skip.
- 일회용 DB에서 25개 통과: HTTP 예약·조회·UNKNOWN·정산·중복 방지·스코프 격리,
  예산 402·연결 실패 503·DB 병합 승인 거부/허용 포함.
- 참조 112개·SQL 계약 96개·패키지 검사 통과.
- PostgreSQL Python 드라이버가 없는 기존 기본 환경에서도 앱 시작·기존 health와 비활성 경로의 503을 확인했다.
  드라이버는 실제 DB 작업에서만 로딩한다.

## 남은 통합

기존 Generate/Review 요청은 계속 메모리 추정 원장을 사용한다.
인증된 워크플로의 컨텍스트 패킷·영수증을 연결해 새 DB 경로를 사용하도록 이어야 한다.
기존 Muse/GitHub·분리 Runner·GCP 검증과 소유자의 로그인 생략 설정은 [서비스 상태](SERVICE_STATUS.md)를 따른다.
새 내부 DB HTTP 경로와 두 인증 헤더의 운영 배포 검증은 별도로 남아 있다.

Muse Spark 기본 모델과 API 주소는 유지했다. Meta의 [공식 Chat Completions 안내](https://dev.meta.ai/docs/cookbook/quickstart-chat-completions)에서도
`muse-spark-1.3`과 `https://api.meta.ai/v1` 구성을 확인했다. 계정 접근과 실제 호출 성공은 별도 검증이 필요하다.
