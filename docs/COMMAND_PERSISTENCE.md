# Canonical 명령 저장 지원

`postgres_commands.CommandStore`는 정본 `core.accept_command`와 `core.commands` 상태 전이 제약을 사용한다.
확장 004는 상태 이력과 완료 응답만 보존한다. frozen core SQL은 수정하지 않는다.

## 서버 설정과 의미

기존 확장 001–003 뒤 `004_api_commands.sql`을 마이그레이션 계정(core_owner/ctx_owner)으로 적용한다.
런타임은 core_app/ctx_gateway와 서버의 tenant/project 범위를 사용한다.
새 명령의 `actor_user_id`는 서버 설정 `EVO_COMMAND_ACTOR_ID`의 UUID다.
이는 소유자 계정의 고정 식별자이며 요청 본문으로 선택하지 않는다. 누락이면 새 접수를 거부한다.

API의 BUILD는 canonical ASK의 payload에 `api_kind=BUILD`로 기록한다.
긴/Unicode 멱등 키는 SHA-256 식별자로 접수하고 원래 값은 비공개 payload에 보존한다.
merge·예산 승인 명령은 이 호환 경로로 만들 수 없다. 해당 structured confirmation 경로가 필요하다.
HIGH/CRITICAL 목표의 기존 확인 규칙도 유지한다.

프로젝트 버전은 DB가 기준이다. 같은 키·같은 요청은 재조회하고 다른 요청으로 키를 재사용하면 거부한다.
같은 키의 동시 접수를 직렬화하고, canonical 명령 행을 잠근 뒤 상태와 이력을 함께 저장한다.

## 생성 실행의 중복 방지

`dispatch`는 RECEIVED→VALIDATING→PLANNED→DISPATCHED를 한 트랜잭션으로 진행한다.
이미 DISPATCHED이거나 종료된 명령을 다시 dispatch하지 않는다.
프로세스가 응답 저장 전에 끝나면 실행 여부가 불명확하므로 같은 명령으로 공급사를 다시 호출하지 않는다.

`complete`는 APPLYING→APPLIED와 완료 응답 저장을 한 번에 커밋한다.
`CommandView['served']` 쓰기는 이 메서드로 연결한다. 완료 응답은 불변이며 동일 재전송은 멱등이다.
응답의 `evidence.id`에서 만든 generated FK는 같은 tenant/project의 서버 증거를 요구한다.
DB도 APPLIED인 명령과 같은 command_id·candidate·gates를 가진 증거에 연결된 응답만 허용한다.
없는 증거, 다른 명령/프로젝트의 증거, PASS로 바꾼 게이트나 바꿔 끼운 후보는 완료를 만들지 못한다.
이전 캐시를 조회할 때도 저장 증거를 재대조한다.
API BUILD 명령의 지연 제약 트리거는 트랜잭션 종료 시 완료 응답 존재를 확인한다.
앱 역할이 SQL로 상태만 APPLIED로 바꿔 커밋해도 거부하며, 일반 canonical 명령의 계약 전이는 보존한다.
일반 `advance` 입력만으로 APPLYING/APPLIED를 만들 수 없으며 서버 응답을 저장하는 `complete`가 필요하다.
완료 저장 중 실패하면 상태·히스토리·응답을 모두 롤백한다.
조회는 명령 행의 공유 잠금을 유지하므로 완료 트랜잭션 전후의 상태와 이력을 섞어 반환하지 않는다.
반환되는 명령·히스토리·응답은 API 인스턴스가 바뀌어도 유지된다.
DB 실패 시 메모리 응답으로 대체하지 않는다.
BUILD 호환 명령은 ASK에 대한 생성 응답의 완료를 뜻한다. 패치 병합·배포 완료는 별도의 증거와 승인 경로를 따른다.

## 내부 Worker HTTP 경로

기존 `/v1/kernel` 서비스 토큰과 서버 소유 scope를 그대로 사용한다. 이 경로는 `EVO_STATE_BACKEND`와 독립적으로 PostgreSQL을 사용한다.
브라우저에는 토큰을 제공하지 않으며 web BFF의 내부 커널 차단 정책을 유지한다.
운영에서 Google ID 인증을 켜면 `Authorization: Bearer <approved ID token>`과
`X-Evoforge-Kernel-Token: <internal service token>`을 함께 보낸다. 기존 Google audience/서비스 계정 검사를 우회하지 않는다.
신뢰된 Worker는 배포에서 이미 허용한 서비스 identity와 호출 권한도 갖춰야 한다.
ID 인증을 끈 로컬 환경의 기존 `Authorization: Bearer <internal token>`도 호환한다.
명시한 커널 헤더가 틀리면 다른 헤더로 자동 대체하지 않는다.

- `POST /v1/kernel/commands`: `{goal, idempotency_key, risk?, confirm?, expected_version?}`. 현재 BUILD/ASK만 접수한다.
  actor·scope·kind/승인을 본문으로 바꾸지 못한다. 확인은 strict boolean, 버전은 비음수 int64다.
- `GET /v1/kernel/commands/{id}`: 저장된 상태·히스토리·완료 응답 조회.
- `POST /v1/kernel/commands/{id}/dispatch` + `{}`: 단일 실행권을 기록한다. 모델을 직접 호출하지 않는다.
- `POST /v1/kernel/commands/{id}/complete` + `{response: {...}}`: 같은 명령의 서버 증거를 확인해 응답을 저장한다.

확인 필요/상태 충돌/증거 불일치는 409, 다른 scope·없는 id는 404,
잘못된 본문은 422, actor 미설정·DB 불가는 503이다. DB 실패 시 메모리 명령으로 대체하지 않는다.
미완료 dispatch를 다시 실행하지 않고, 이미 가진 서버 응답의 완료 저장만 재시도할 수 있다.

확장 004는 이전 미배포 초안의 빈/유효 테이블에도 generated FK를 추가한다.
이전 응답에 유효한 서버 증거가 없으면 마이그레이션 전체를 거부한다. 불변 응답을 수정하거나 증거를 만들어 넣지 않는다.

## 현재 검증과 연결 상태

실제 PostgreSQL에서 접수·전송·완료·별도 프로세스 복원, 동시 접수/단일 dispatch,
버전 충돌과 safety fast lane, 변조 재시도·잘못된 상태 전이·승인 우회 거부, RLS를 확인했다.
새 경계 검증은 잘못된 확인/버전·DB 문자열, 완료 저장 롤백, 일관된 조회와 DB의 응답 상태/식별자 강제를 포함한다.
분리 단계의 API **403 passed·1 skipped**, 실제 PostgreSQL **91 passed**, SQL 96·참조 112·패키지 검사와 웹 빌드는
`docs/validation/2026-10-27-api-commands.json`의 이전 스냅샷이다.
Runner 지원과 합친 최신 검증은 `docs/validation/2026-10-27-pg-integration.json`을 따른다.

상위 Muse round7은 `d347b56`으로 main에 먼저 반영되었고 `codex/pg-integration`이 이를 보존해 동기화했다.
후속 Muse T22가 main을 편집 중이므로 현재는 내부 서비스 HTTP 경로 지원이며 공개 Generate 경로 연결 완료가 아니다.
상위 작업 반영 후 호환 hook과 dispatch를 연결하고 전체 검증을 갱신한다.
공개 비용 원장의 canonical 예약·가격표·영수증 연결도 별도로 남아 있다.
기본 모델 `muse-spark-1.3`과 자동 모델 대체 금지는 유지한다.

## 상위 작업 병합 후 이어갈 연결

1. `commands.py`가 명시적 PostgreSQL 모드에서 이 저장소로 위임하도록 한다. 기본 메모리 동작은 기존 테스트와 호환한다.
2. Generate에서 저장된 `served` 응답을 먼저 재사용하고, 비용 예약·공급사 호출 전에 `dispatch`한다.
   이미 전송된 미완료 명령은 409로 거부하고 대사 대상으로 남긴다. DB 오류는 기존 503 경계를 따른다.
3. 성공 응답 저장은 `complete`와 묶고, 실패·UNKNOWN 비용의 보존은 명령 상태와 독립적으로 유지한다.
4. 실제 HTTP 재전송·동시 Generate·새 API 프로세스 복원을 PostgreSQL과 함께 검증한다.
   운영 확장 적용과 공개 비용 원장·mission 저장은 별도로 대조한다.
5. 상위 T19의 `_generate_core` 등 공유 core 경로를 기준으로 연결해 mission에서도 같은 보호를 적용한다.
