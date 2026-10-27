# PostgreSQL 영수증 문서와 정산 연결

2026-10-27. `PostgresKernel.record_receipt`는 정본
`provider-usage-receipt.v1.schema.json`으로 검증한 문서와 `ctx.provider_usage_receipts`를
한 트랜잭션에 저장한다. 이는 내부 Broker/대사 서비스의 저장 경로다.
스키마 검사와 SHA-256은 실제 공급사 청구를 입증하지 않는다.

## 설치와 내부 API

`services/api/requirements.txt`를 설치한다. JSON Schema 검사 외에 RFC3339 검사도 필수다.
선택 의존성이 없어 날짜 검사가 생략되는 상황을 허용하지 않는다.

이미 정본 context/core 스키마와 역할이 설치된 DB에 마이그레이션 계정으로 실행한다.
PG 연결 환경변수는 비밀 저장소에서 주입하며 로그에 출력하지 않는다.

```powershell
psql -v ON_ERROR_STOP=1 -f services/api/migrations/001_receipt_documents.sql
```

확장 마이그레이션은 재실행 가능하다. 정본 SQL 파일을 수정하지 않는다.
런타임 로그인에는 `core_app`, `ctx_gateway` 멤버십이 필요하다.
API가 DDL·예산·크레딧을 자동 생성하지 않는다.
GitHub Actions와 로컬/Cloud Build DB 테스트는 이 마이그레이션을 두 번 적용해 검증한다.
Cloud Build 배포 단계에도 확장 적용을 추가했으나 실제 클라우드 실행은 미검증이다.
기존 배포 스크립트의 정본 스키마 최초 설치와 이후 버전별 업그레이드 분리는 별도 과제다.

인증과 서버 소유 스코프 설정은 [내부 API](INTERNAL_KERNEL_API.md)를 따른다.

| 메서드·경로 | 동작 |
|---|---|
| `POST /v1/kernel/receipts` | 정본 v1 문서를 저장. tenant/project는 서버 스코프와 같아야 함 |
| `GET /v1/kernel/receipts/{receipt_id}` | 해당 스코프의 문서와 실제 원장 entry ID 조회 |
| `POST /v1/kernel/receipts/{receipt_id}/settle` | 본문 `{}`. 저장된 고객 청구액으로 정본 정산 함수 호출 |

금액·스코프를 추가한 정산 본문은 422다. 기존 `reservations/{call_id}/settle`도
해당 영수증 문서가 있으면 저장된 고객 청구액과 다른 금액을 409로 거부한다.
기존 ctx 행만 사용하는 호환 정산 경로는 별도로 남아 있으며 문서 저장 경로를 사용한 완료 증거가 아니다.
이 서비스 토큰을 브라우저나 모델에 넘기지 않는다. 모델 JSON을 영수증으로 간주하지 않는다.

## 보존과 검증

- 금액과 토큰 수는 음수가 아닌 int64다. bool·float·문자열의 자동 변환을 하지 않는다.
  UUID, 날짜·시간, 공급사·통화·호출 목적과 필수 원시 usage 필드도 확인한다.
- `reservation_key`는 해당 call UUID다. 이미 전송 중이거나 UNKNOWN인 예약만 새 문서를 받는다.
  없는 call이나 다른 프로젝트의 문서, 미전송·해제된 예약, 사후 생성한 패킷을 거부한다.
- 패킷의 provider/model이 같고 `issued_at <= 예약 시각 < expires_at`이어야 한다.
  전송 직전 패킷 상태·공급사 허용 목록 검증과 packet/call 사전 바인딩은 아직 연결되지 않았다.
- 문서는 `runtime.provider_receipt_documents`에 append-only로 보존한다.
  `json` 형식을 사용해 지수 표기와 음수 0 등 JSONB가 정규화하는 원시 숫자도 digest와 함께 복원한다.
  RLS는 tenant와 project 양쪽을 적용한다. call당 문서 하나와 provider reference 중복 제한을 유지한다.
- 동일 문서 재전송은 멱등이고 변경된 재전송은 거부한다. 두 테이블 중 한쪽만 남기지 않는다.
  추정 문서를 provider_billed 문서로 덮어쓰는 대사는 지원하지 않는다. 정정/버전 정책이 필요하다.
- `ledger_entry_id`는 호출자가 정하지 않는다. 열린 예약에서는 null이고, 정산 후 실제 원장 ID를 조회해 붙인다.
  재시작·동시 재전송에도 정본 정산 함수가 한 번만 청구한다. UNKNOWN은 영수증 없이 환불하지 않는다.
- 잠금을 기다린 뒤 최신 intent를 별도 조회한다. PostgreSQL의 조인 snapshot 때문에
  COMMITTED 예약에 이전 SENT 상태가 섞여 응답하던 동시성 문제를 회귀 검증했다.
- `source=estimated`는 그대로 유지한다. 실제 공급사 청구 입증과 측정 KPI 자격은 별도다.

## 확인 범위와 미완료 항목

`test_receipt_contract.py`는 계약 경계와 JSON 보존을 검사한다.
`test_postgres_kernel.py`는 일회용 PostgreSQL에서 문서/ctx 원자성, 정산 금액,
동시 요청·중복 방지, RLS, append-only와 인증된 HTTP 요청을 검사한다.
실행 방법은 [로컬 PostgreSQL 검증](LOCAL_POSTGRES_VALIDATION.md)을 따른다.

2026-10-27 지원 브랜치 `codex/receipt-support` 검증 결과:

- `python -m pytest services/api -q`: **269 passed, 1 skipped** (DB 환경변수가 없는 실행).
- `tools/validate_local_pg.py --pg-bin C:\evo_forge\.local\postgresql-15.19\pgsql\bin --kernel-tests`:
  PostgreSQL 15.19에서 **46 passed**, SQL 계약 **96개**, 참조 **112개**, C1–C9 전체 통과.
- SQL/DB 로그: 작업 트리의 `.local/validation-postgres.log`, `.local/validation-kernel.log`.
  임시 클러스터 종료와 전용 클러스터 디렉터리 정리를 확인했다.
- 동시 정산 회귀는 수정 전 실제 DB에서 실패했고, 예약 잠금과 intent 조회 분리 후 통과했다.
  RFC3339 경계 2건도 선택 의존성 누락 상태에서 실패를 확인한 뒤 수정했다.

상위 Muse round3의 main 반영을 확인한 뒤 `89dbc71`에서 동기화했다.
상위 provider fixture를 채택하고 상위 구현·봉인 수용 테스트·정본을 그대로 보존했다.
동기화 후 **API 291 passed·1 skipped**, 실제 DB **46 passed**, 참조 **112개**·SQL **96개**와
기본/실제 PG 패키지 검사가 다시 통과했다. 웹 보안 의존성의 빌드 검증은
[WEB_DEPENDENCY_SECURITY.md](WEB_DEPENDENCY_SECURITY.md)에 기록했다.
main 반영 기록은 [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md)를 따른다.
전체 서비스·실제 모델 실행·배포의 완료 근거는 아니다.

정본 영수증은 0원도 허용하지만 `core.usage_ledger`의 model_usage는 음수 청구만 허용한다.
0원 문서는 보존하고 정산을 거부해 예약을 열어 둔다. 가짜 청구·환불·adjustment로 우회하지 않는다.
0원 정산과 추정→실청구 정정은 정본에 맞는 정책 결정·구현이 필요하다.

Generate/Review는 아직 메모리 추정 원장을 사용한다. 개발 CLI의 비용 예약·영수증 연결도 남아 있다.
사용자 로그인·프로젝트 멤버십, 실제 Broker의 패킷·가격표·청구 증거, 영수증 대사 작업,
실제 Muse Spark/GitHub 호출과 배포 검증은 남아 있다.
모델 기본값 `muse-spark-1.3`과 모델 자동 대체 금지는 유지한다.
