# 요청 경로의 PostgreSQL 증거 저장

`EVO_STATE_BACKEND=postgres`에서 실제 `/v1/*` 요청이 기록하는 증거, 비공개 Critic 스위트,
단계 이벤트와 체인 링크를 PostgreSQL에 저장한다. API 인스턴스나 작업 프로세스가 바뀌어도 같은 서버 스코프에서 조회한다.
모델 기본값 `muse-spark-1.3`과 기존 HTTP 봉인 코드 마스킹은 유지한다.

## 설정

기존 context/core 스키마와 확장 001·002 다음 `services/api/migrations/003_api_evidence.sql`을 적용한다.
마이그레이션 계정에는 core_owner/ctx_owner 역할, 런타임 로그인에는 core_app/ctx_gateway 멤버십이 필요하다.
API는 DDL이나 프로젝트·예산·크레딧을 자동 생성하지 않는다.

서버 환경에 다음을 설정한다:

- `EVO_STATE_BACKEND=postgres`
- `DATABASE_URL`: 런타임 DB 로그인 연결 정보
- `EVO_TENANT_ID`, `EVO_PROJECT_ID`: 미리 생성한 서버 소유 프로젝트 UUID

범위는 요청 본문이나 모델 출력으로 선택하지 않는다. 데이터에는 tenant와 project RLS를 모두 적용한다.
기본값 memory는 기존 로컬 동작을 보존한다. DB URL이 있다는 이유만으로 모드를 자동 변경하지 않는다.
알 수 없는 모드·누락 설정·DB 장애는 503이며 메모리로 우회하지 않는다.
이미 메모리에 있던 증거를 자동 이전하지 않는다.

## 저장 동작

- `main._evidence`의 실제 생성·리뷰·평가·Runner·PR 증거를 `runtime.api_evidence_records`로 연결한다.
- 봉인 원본은 이 비공개 레코드에 남는다. `/v1/evidence`, 리뷰 응답과 이벤트 뷰는 기존 공개 마스킹을 사용한다.
- `runtime.api_evidence_events`는 단계 요약을, `runtime.api_evidence_links`는 단계별 event ID를 보존한다.
  PR이 원본 실행의 이벤트를 공유하는 것도 지원한다. 없는 단계는 계속 null이다.
- 기록과 링크는 append-only이며 동일 재전송은 멱등이다. 다른 내용으로 덮어쓰기·단계 재연결·일괄 clear를 거부한다.
- 각 기록/링크는 별도 트랜잭션이다. 요청 전체를 한 번에 커밋하지 않으며, 중간 실패에서 누락된 단계를 완료로 만들지 않는다.
- Generate의 명령 생성 전, 각 공급사 예약 전에 프로젝트와 저장 테이블 가용성을 확인한다.
  처음부터 DB가 불가한 요청은 모델을 호출하거나 명령 멱등 키를 소비하지 않는다.
  요청 도중의 DB 장애도 성공이나 메모리 저장으로 가장하지 않는다.

## 검증 범위

실제 PostgreSQL 테스트는 합성 Critic 결과를 저장하고 실제 로컬 Runner로 visible/held-out을 실행한 뒤,
별도 Python/API 프로세스에서 리뷰·실행 수치·체인·이벤트를 복원한다.
봉인 원본은 서버 내부에 남고 HTTP에는 canary 코드가 나오지 않는 것을 확인한다.
RLS, 불변·멱등 링크, 공유 이벤트, 저장 장애 시 공급사 호출/메모리 우회 거부도 검사한다.
DB는 일회용이고 실제 Meta 호출이나 운영 데이터는 사용하지 않는다.

재현은 `tools/validate_local_pg.py --kernel-tests`와 전체 API 테스트를 사용한다.
마이그레이션 001–003은 실제 DB bootstrap에서 두 번 적용한다.

## 남은 P0-2

명령 lifecycle과 공개 요청의 비용 원장은 아직 메모리 구현이다.
이 변경을 전체 Cloud SQL 연결이나 결제 영속화 완료로 취급하지 않는다.
`core` 후보·gate_results의 Runner 증거 연결, 실제 Broker 예약·가격표·영수증 정산,
명령의 canonical lifecycle, 운영 Cloud SQL 설정과 장애 중 호출 결과의 대사는 이어서 필요하다.
기존 `core.authorize_merge` 및 예약·영수증 경로는 변경하지 않았다.
