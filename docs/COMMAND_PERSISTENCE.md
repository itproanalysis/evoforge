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
DB도 APPLIED인 명령과 일치하는 command_id의 응답만 허용한다.
일반 `advance` 입력만으로 APPLYING/APPLIED를 만들 수 없으며 서버 응답을 저장하는 `complete`가 필요하다.
완료 저장 중 실패하면 상태·히스토리·응답을 모두 롤백한다.
조회는 명령 행의 공유 잠금을 유지하므로 완료 트랜잭션 전후의 상태와 이력을 섞어 반환하지 않는다.
반환되는 명령·히스토리·응답은 API 인스턴스가 바뀌어도 유지된다.
DB 실패 시 메모리 응답으로 대체하지 않는다.
BUILD 호환 명령은 ASK에 대한 생성 응답의 완료를 뜻한다. 패치 병합·배포 완료는 별도의 증거와 승인 경로를 따른다.

## 현재 검증과 연결 상태

실제 PostgreSQL에서 접수·전송·완료·별도 프로세스 복원, 동시 접수/단일 dispatch,
버전 충돌과 safety fast lane, 변조 재시도·잘못된 상태 전이·승인 우회 거부, RLS를 확인했다.
새 경계 검증은 잘못된 확인/버전·DB 문자열, 완료 저장 롤백, 일관된 조회와 DB의 응답 상태/식별자 강제를 포함한다.
API **403 passed·1 skipped**, 실제 PostgreSQL **91 passed**, SQL 96·참조 112·패키지 검사와 웹 프로덕션 빌드 통과.
검증 결과와 로그 해시는 `docs/validation/2026-10-27-api-commands.json`에 기록한다.

상위 Muse round7이 `commands.py`와 main/mission 인터페이스를 수정 중이므로,
이 문서의 초기 단계는 별도 모듈 지원이며 공개 Generate 경로 연결 완료가 아니다.
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
