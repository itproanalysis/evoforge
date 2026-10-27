# DB 영수증 저장과 예약 해제 보호

확장 `009_usage_release_guards.sql`은 별도 영수증 적재 서비스와 직접 예약 SQL도
같은 예약 행에서 직렬화한다. 정본 SQL 함수·RLS 정책·기존 금전 기록은 변경하지 않는다.
PostgresKernel의 영수증 검사에 추가되는 DB 경계이며 전체 공개 비용 연결은 별도다.

## 설치와 동작

정본과 확장 001–008이 설치된 DB에 마이그레이션 계정으로 009를 적용한 뒤 새 API를 배포한다.
009는 반복 적용 가능하며 과거 행을 수정하거나 청구·환불·예약을 자동 생성하지 않는다.

```powershell
psql -v ON_ERROR_STOP=1 -f services/api/migrations/009_usage_release_guards.sql
```

영수증 INSERT의 BEFORE 트리거는 같은 tenant/project/UUID call의 예약 행을 잠근다.
예약이 이미 RELEASED이면 INSERT를 거부한다. 연결할 canonical 예약이 없는 기존 ctx 호출은 허용한다.
예약을 RELEASED로 바꾸는 BEFORE 트리거는 같은 scope/call의 영수증이 있으면 해제를 거부한다.
문서·공급사 참조가 없는 영수증과 estimated·0원 기록도 포함한다.

영수증 저장이 먼저 잠그면 해제 요청이 기다린 뒤 커밋된 영수증을 보고 거부된다.
해제가 먼저 잠그면 적재가 기다린 뒤 RELEASED 상태를 보고 거부된다.
실패한 트랜잭션의 intent 변경·hold 해제·영수증 INSERT는 함께 롤백된다.
정상 미접수 해제와 정본 영수증 정산은 유지한다.

## 권한과 가용성

- 두 트리거 함수는 각 스키마 소유자 권한으로 자기 테이블만 읽는다. ctx_gateway에 core 테이블 권한을 추가하지 않는다.
- FORCE RLS와 현재 tenant/project GUC 검사를 유지한다. 별도 적재 서비스도 올바른 scope를 설정해야 한다.
- PUBLIC·core_app·ctx_gateway에는 새 함수 EXECUTE 권한을 주지 않는다. 트리거 설치에 필요한 소유자 권한만 허용한다.
- 임시 runtime CREATE 권한은 설치 전 상태로 돌린다. 반복 적용으로 권한이 누적되지 않는다.
- 새 예약·전송과 실제 해제는 두 트리거의 함수·시점·행 단위·활성 상태를 검사한다.
  트리거가 없거나 disabled/replica 설정 등으로 실행되지 않으면 503으로 거부하며 모델을 전송하지 않는다.
  조회와 이미 발생한 청구의 정산 경로는 유지한다.

## 검증과 한계

실제 core_app·ctx_gateway 세션을 분리해 직접 SQL의 해제/적재 거부와 양방향 행 잠금 대기를 검증한다.
트리거 삭제·비활성화·replica 모드, 반복 DDL, 정본 함수/정책 불변과 새 권한 제한도 검사한다.
테스트는 일회용 PostgreSQL의 합성 영수증을 사용하며 실제 공급사 청구나 운영 DB 적용이 아니다.

관리자에 의한 DDL/트리거 우회는 운영 권한 관리 대상이다. 과거에 이미 해제된 예약과 충돌하는 청구를
자동 복구하거나 재청구하지 않는다. 0원 정산·추정→실청구 정정 정책과 공개 Broker 비용 연결도 계속 미완료다.
Muse Spark `muse-spark-1.3` 기본값과 자동 모델 대체 금지는 유지한다.

## 검증 기록

구현 `afecb31`의 수정 전 집중 회귀는 10 failed, 수정 후 11 passed다.
API 485 passed·1 skipped, 실제 PostgreSQL 166 passed, 참조 112·SQL 96·계약 0 failure·웹 빌드 통과.
원본 로그 8개는 `C:\evo_forge\.local\evidence\db-usage-guard-20261027-ur5bi8s3`,
source·로그 해시는 `docs/validation/2026-10-27-db-usage-guard.json`에 보존했다.
