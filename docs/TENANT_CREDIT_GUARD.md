# 테넌트 전체 미정산 예약 검사

프로젝트별 RLS 아래에서 정본 `core.reserve_cost`가 보는 다른 프로젝트의 예약은 숨겨진다.
선불 credit_balance는 테넌트 전체인데 open 예약 합계는 일부 프로젝트만 포함해,
잔액 20,000,000µUSD에 두 프로젝트가 각각 12,000,000µUSD를 예약하는 문제가 재현됐다.

## 확장 007

`services/api/migrations/007_tenant_credit_holds.sql`은 기존 reserve/settle 함수 정의와 RLS 정책을
유지하면서 비용 예약 INSERT/상태 종료에 추가 DB 트리거를 적용한다. 공개 API 코드는 변경하지 않았다.

- 비공개 `runtime.tenant_credit_hold_events`에 원래 예약 금액의 RESERVE/RELEASE를 append-only로 기록한다.
- 새로운 예약은 정본과 같은 테넌트 advisory lock 아래에서 전체 잔액과 미정산 예약을 검사한다.
- 잔액과 hold를 한 SQL statement snapshot에서 읽어 동시 정산의 이전/이후 상태를 섞지 않는다.
- SENT/UNKNOWN은 원래 hold를 유지한다. 정본 경로가 예약을 COMMITTED/RELEASED로 닫을 때만 hold를 해제한다.
- 예약·hold 기록·영수증 정산·원장 기록은 호출자의 기존 트랜잭션에 속하며 실패하면 함께 롤백한다.
- 닫힌 예약의 재개방을 거부하고, 재전송이 hold를 두 번 해제하지 않는다.

금액은 정수 micro-USD다. 새 청구·영수증·환불을 만들지 않으며 기존 정산 함수를 우회하지 않는다.
실제 정산액이 예약액보다 큰 경우에는 기존 계약의 초과 사용 기록을 유지하고 이후 예약을 제한한다.

## 권한과 적용

`core_app`은 hold 테이블의 SELECT/INSERT/UPDATE/DELETE 권한이 없다.
현재 테넌트의 합계만 반환하는 `runtime.tenant_open_reserved_micros()`를 실행할 수 있다.
SECURITY DEFINER 트리거는 정본 예약 테이블에서 온 호출과 현재 tenant를 검사한다.
프로젝트 RLS를 넓히거나 다른 프로젝트의 원본 예약을 앱에 공개하지 않는다.

기존 확장 001–006 다음에 007을 적용한다. 기존과 같이 ctx_owner/core_owner DDL 권한이 필요하다.
어댑터는 새 가드가 없거나 비활성화되면 새 예약을 503으로 거부하며 예약/intent를 남기지 않는다.
DB에 007을 먼저 적용한 뒤 새 API 버전을 배포한다. 트리거가 실행되지 않는 replica 연결도 거부한다.
마이그레이션은 원본 테이블 쓰기 잠금 아래서 소유자에게만 FORCE RLS를 일시 해제해 전체 기존 예약을 백필한다.
같은 트랜잭션에서 원본/hold 테이블에 FORCE RLS를 복원한 뒤 커밋한다. 함수 정의와 프로젝트 정책은 바꾸지 않는다.
반복 적용은 기존 이벤트를 중복 생성하지 않는다. BACKFILL 시각은 실제 호출/정산 시각을 증명하지 않는다.
과거 예약이 이미 잔액을 초과해도 임의 환불하거나 재전송하지 않고 신규 예약을 거부한다.

## 검증 범위

실제 PostgreSQL에서 다른 프로젝트 예약 차단, UNKNOWN 보존과 영수증 정산,
롤백·재개방 금지·병렬 예약·테넌트 격리·실제 core_app 세션의 비공개 테이블 접근 거부,
기존 데이터 백필·반복 적용·FORCE RLS와 정본 함수 정의 보존을 검증한다.
집계와 원본 로그·해시는 `docs/validation/2026-10-27-tenant-credit-guard.json`에 보존한다.

수정 전 초과 예약 회귀 **1 failed**를 확인했다. 수정 후 API **463 passed·1 skipped**,
실제 PostgreSQL **139 passed**(새 회귀 8개 포함), 참조 **112개**·SQL **96개**·계약 **0 failure**,
웹 프로덕션 빌드를 통과했다. 24개 병렬 요청에서는 잔액 20,000,000µUSD에 맞는 10개 예약만 허용했다.

지원 브랜치의 DB 경로 보강이며 운영 DB 적용·실제 Muse 청구·전체 비용 통합 완료를 뜻하지 않는다.
공개 Generate/Review는 여전히 메모리 원장을 사용한다. T22가 상위 main 파일을 편집 중이므로 그 코드는 보존했다.
Muse Spark 기본값과 자동 대체 금지, 전체 미완료 상태와 자동 재개를 유지한다.
