# PostgreSQL Builder 호출 준비와 전송 전 검사

`PostgresKernel.prepare_builder_call`은 기존 Gateway 패킷과 비용 예약을 원자적으로 연결한다.
모델 호출이나 가격 계산을 수행하지 않는다. 기본 모델은 Meta **muse-spark-1.3**이며 자동 대체하지 않는다.

## 설정과 경로

정본 context/core 스키마가 설치된 DB에 확장 001 다음
`services/api/migrations/002_builder_call_bindings.sql`을 적용한다.
DDL 계정에는 `core_owner`, `ctx_owner` 멤버십이 필요하다. 확장은 컨텍스트 소유자에게
지정한 core 열의 REFERENCES 권한을 주며, 런타임은 `core_app`, `ctx_gateway`만 사용한다.
정본 SQL 파일은 변경하지 않는다.

기존 [내부 API 인증·스코프](INTERNAL_KERNEL_API.md) 설정에 `EVO_PRICE_TABLE_VERSION`을 추가한다.
이는 서버가 승인한 가격표 버전의 식별자다. 이 값의 설정만으로 요율이나 청구 검증이 구현되는 것은 아니다.
`MODEL_BUILDER`의 기본값은 `muse-spark-1.3`이며 요청 본문으로 바꿀 수 없다.
버전이 미설정이면 새 준비 경로는 예약 없이 503을 반환한다.

| 메서드·경로 | 동작 |
|---|---|
| `POST /v1/kernel/builder-calls` | `call_id`, `packet_id`, `period_start`, 양의 int64 `amount_micros`로 준비 |
| `GET /v1/kernel/builder-calls/{call_id}` | 서버 스코프의 바인딩과 예약 상태 조회 |
| `POST /v1/kernel/reservations/{call_id}/sent` | 바인딩된 Builder 호출을 재검증한 뒤 SENT 기록 |

요청 본문에는 모델·공급사·가격표·tenant/project 변경을 허용하지 않는다.
기존의 패킷 없는 예약 API는 호환 경로로 남는다. 모든 모델 워크플로에 새 검사가 연결된 상태는 아니다.

## 준비 시 검증

- 패킷이 같은 tenant/project에 존재하고 `ISSUED`, 미만료, API 채널의 Builder 역할이어야 한다.
  Critic/verifier 패킷은 별도의 원문 전달·리뷰 coverage 검사가 필요하므로 이 경로를 사용할 수 없다.
- 패킷의 provider/model은 Meta와 서버의 Builder 모델에 일치해야 한다. 다른 모델로 재시도하지 않는다.
- core run은 RUNNING, task는 CLAIMED 또는 RUNNING이어야 한다.
  base SHA, policy hash, objective/contract 버전과 패킷을 비교한다.
- agent는 실제 `provider_api`이고 `core.agent_can_work`를 통과해야 한다.
  `core.assert_fencing`으로 lease holder/epoch를 확인하고, 만료는 잠금 대기 후 `clock_timestamp()`로 추가 검사한다.
- 프로젝트의 해당 공급사 동의가 미취소이며 `model_glob`이 모델과 일치해야 한다.
  glob은 대소문자를 구분하는 Python fnmatch 형식이며 미래 시각의 동의는 인정하지 않는다.
- 패킷이 예약 이전에 발행되어 있어야 한다. 이미 SENT인 호출에 패킷을 사후 연결하지 않는다.

동일 트랜잭션에서 정본 `core.reserve_cost`와 provider intent, 불변 `runtime.builder_call_bindings`를 기록한다.
검사 거부·예산 부족 시 새 예약·intent·바인딩이 함께 롤백된다.
같은 호출의 재시도는 금액·기간·패킷·모델·가격표 버전이 일치해야 한다.
이미 SENT인 호출의 준비 재전송은 기존 상태를 반환할 뿐이며 다시 보낼 수 없다.

## 전송과 영수증

`mark_sent`는 실제 전송 직전에 호출한다. 예약 이후 패킷 취소, agent 비활성화,
작업/목표/정책 변경, lease 만료/교체, 공급사 동의 취소, 서버 모델 변경을 재검증한다.
관련 DB 행을 잠그고 확인한다. 실패하면 SENT로 바꾸거나 임의 환불하지 않는다.
아직 전송하지 않은 호출은 기존 `release_not_accepted`로 명시적으로 해제할 수 있다.

바인딩된 호출의 영수증은 해당 packet/provider/model/가격표 버전과 `task_turn` 목적에 일치해야 한다.
정본 문서 없이 ctx 행만 만든 호환 정산은 이 호출에서 거부된다.
정산은 계속 [영수증 문서](RECEIPT_PERSISTENCE.md)와 정본 `core.settle_reservation`을 사용한다.
전송 이후 도착한 영수증은 당시의 불변 바인딩과 비교하며 현재의 새 호출 권한으로 재분류하지 않는다.

## 검증과 남은 범위

`test_postgres_kernel.py`는 실제 일회용 PostgreSQL에서 core claim/fence·동의·패킷을 만들고
준비→SENT→영수증 저장→정산과 재시작·동시 재전송을 검증한다.
권한/패킷/lease/목표/정책·가격표 변경, RLS, 사후 바인딩, 호환 정산 우회와 예약 롤백도 확인한다.
고의로 tenant 예약 잠금을 기다리게 한 뒤 lease를 만료시켜, 트랜잭션 시작 시각만으로 통과하지 않는지도 검사한다.
확장 001·002는 테스트 bootstrap에서 순서대로 두 번 적용한다.

지원 브랜치의 초기 검증은 API **298 passed·1 skipped**, 실제 PostgreSQL **77 passed**다.
참조 **112개**·SQL **96개**, 기본 및 `--pg` 패키지 검증이 통과했다.
API 모듈 컴파일·시작·health/OpenAPI도 확인했다. 잠금 대기 회귀는 live `pg_locks`로 동기화했다.
상위 Muse round4를 `0851454`에서 보존해 동기화한 뒤 **API 317 passed·1 skipped**, 실제 DB **77 passed**,
참조 112·SQL 96·전체 계약 검증과 Next 15.5.28 프로덕션 빌드를 통과했다.
검증 로그 해시와 정확한 미검증 플래그는 `docs/validation/2026-10-27-builder-preflight.json`에 저장했다.
`0551fbe`로 main에 반영했고 main의 API 시작/health/OpenAPI, 패키지 검사와 웹 빌드도 통과했다.
컨테이너 이미지·외부 모델·배포 실행은 미검증이다.

아직 기존 Generate/Review와 개발 CLI의 메모리 추정 원장을 교체하지 않았다.
실제 SDK 전송기는 바인딩된 모델과 call ID를 사용해 이 경계를 호출하도록 연결해야 한다.
브라우저 로그인·프로젝트 멤버십, 실제 요율 계산·공급사 청구 입증, Critic coverage 경로,
Runner/core 후보·게이트 영속 연결과 실제 Muse/GitHub·클라우드 검증은 남아 있다.
이 내부 API의 서비스 토큰은 서버용이다.
