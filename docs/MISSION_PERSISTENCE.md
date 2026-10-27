# Mission 상태와 증거의 PostgreSQL 저장

`EVO_STATE_BACKEND=postgres`에서 기존 mission facade가 `postgres_missions.MissionStore`를 사용한다.
main.py의 생성/리뷰/Runner/PR 코드는 수정하지 않았다. 기본 memory 모드는 기존 동작을 유지한다.
운영에서 선택 모드를 사용하려면 기존 설정과 확장 `006_api_missions.sql`까지 적용해야 한다.

## 저장과 조회

- identity와 버전별 snapshot을 append-only 테이블에 기록한다. 상태·증거·단계 포인터는 같은 트랜잭션에 저장한다.
- 입력 goal/repo/target paths/risk/확인은 불변이며 HIGH/CRITICAL의 명시적 확인을 보존한다.
- 상태 전이는 기존 CREATED→GENERATED→REVIEWED→RAN→PR_OPENED와 CANCELLED/FAILED를 유지한다.
- 진행 상태에는 같은 scope/mission의 서버 증거와 단계 이벤트가 필요하다. 다른 리뷰/run을 연결하지 못한다.
- PR 완료에는 해당 run의 모든 저장 게이트가 PASS여야 한다. 실제 병합은 별도의 core 승인 경로다.
- 버전 순서·증거 제거/교체·잘못된 상태 진행을 DB가 거부하며 core_app에 UPDATE/DELETE 권한을 추가하지 않는다.

각 읽기는 DB에서 조회한다. facade가 반환한 live dict view는 커밋 후 갱신하는 약한 참조이며,
DB 실패 시 데이터를 대신 반환하는 저장소로 사용하지 않는다. main의 기존 응답 조립 방식도 유지한다.
연결 식별자와 scope별로 view를 분리하며, 같은 단계의 병렬 attach/mark 재전송은 버전을 늘리지 않는다.
tenant/project RLS를 유지하고 다른 scope의 id는 없는 id와 같은 404다. reset은 durable 데이터를 지우지 못한다.

## 완료 출력 복원

API가 서버 출력을 저장한 뒤 attach/mark 전에 종료되었다면, 다음 조회가 같은 mission의 완료 출력을 확인한다.
한 개의 출력과 완전한 단계 이벤트가 확인되면 모델을 호출하지 않고 상태와 포인터를 복원한다.
출력의 이벤트가 미완성이거나 여러 출력이 있으면 409로 거부하고 대사를 기다린다.
터미널 상태는 앞으로 복원하지 않으며 취소가 기존 증거를 삭제하지 않는다.

이 복원은 이미 완료된 서버 출력에 한정된다. 호출 전 dispatch claim, 출력이 없는 UNKNOWN 호출,
동시에 시작하는 모델 호출의 실행권, 생성 접수와 Objective 기록의 원자성은 공유 core 연결 단계에 남아 있다.
비용 예약·영수증·명령·mission을 한 트랜잭션으로 묶은 완료 상태로 취급하지 않으며 API min=max=1을 유지한다.

## 검증과 운영 범위

실제 PostgreSQL에서 공개 mission HTTP 생성/상태·대시보드·새 API 프로세스 복원, 단일 출력 복구,
미완성/중복 출력 차단, scope 격리, 버전 불변성, 취소와 DB 실패를 검증한다.
HIGH 확인 보존, 병렬 완료의 멱등성, 서로 다른 DB 연결의 live view 분리도 검증한다.
실제 로컬 Runner를 사용한 단계 연쇄도 확인하며 Builder/Critic/GitHub는 명시적인 합성 transport다.
봉인 원본은 기존 서버 저장소에 남고 공개 응답은 기존 마스킹을 유지한다.
원본 로그·집계는 `docs/validation/2026-10-27-mission-persistence.json`을 따른다.

지원 브랜치에서 API **463 passed·1 skipped**, 실제 PostgreSQL **118 passed**(mission 신규 11개 포함),
참조 **112개**·SQL **96개**·계약 검사 **0 failure**, Next 15.5.28 프로덕션 빌드를 통과했다.

이 변경은 지원 브랜치의 구현이다. 운영 DB 적용·실제 Muse 청구·GCP 배포를 완료했다고 선언하지 않는다.
후속 Muse T22가 편집하는 main/평가/UI와 상위 봉인 수용 테스트는 변경하지 않는다.

## Review 호출 증거 복원 보강

리뷰 출력 저장 뒤 mission 연결 중 종료되면 `provider_evidence_ids`도 같은 snapshot에 복원한다.
명시적 단계 attach와 GET 복구가 동일한 검증을 사용하며, 먼저 연결된 호출 ID는 중복 추가하지 않는다.
기존 review 포인터에 빠진 호출 ID도 새 불변 버전에 보충하고 과거 버전은 수정하지 않는다.

확장 006은 같은 scope의 `provider_call` 레코드를 확인하고 다른 mission_id가 기록된 호출을 거부한다.
호출 순서는 `critic_spec` 다음 `critic_review`다. Phase A의 잘린/불완전한 응답으로 조기 종료했다면
하나의 spec 호출 기록을 보존한다. 생성된 봉인 suite를 검증하는 기존 Runner 경계는 유지한다.
누락·중복·잘못된 형식/종류·scope/mission 불일치는 409로 차단하고 복구 snapshot은 커밋하지 않는다.
DB도 review 포인터가 있는 버전에서 호출 ID를 생략하는 직접 INSERT를 거부한다.

확장 006의 이전 지원 초안을 이미 적용한 테스트 DB에는 해당 SQL을 다시 적용해야 한다.
이미 연결된 호출 기록은 기존 추정 원장의 감사 자료이며 canonical 청구 영수증이나 정산 완료 증명이 아니다.
공식 SDK에 모의 HTTP 응답을 주고, 실제 리뷰 API의 연결 전/첫 호출 연결 후/두 호출 연결 후 중단을 검증한다.
검증 원본과 집계는 `docs/validation/2026-10-27-review-recovery.json`에 별도 보존한다.

리뷰 aggregate가 저장되기 전 발생한 UNKNOWN 호출에는 이 복원이 적용되지 않는다.
호출 전 mission/command 바인딩과 그 대사는 공유 core 연결 단계에 남아 있다.

보강 후 API **463 passed·1 skipped**, 실제 PostgreSQL **131 passed**(신규 회귀 13개 포함),
참조 **112개**·SQL **96개**·계약 검사 **0 failure**, 웹 프로덕션 빌드를 통과했다.
수정 전에는 새 복구 회귀의 8개 집중 사례가 실패했다. 이 집계는 앞 절의 118개 검증 이후 결과다.
