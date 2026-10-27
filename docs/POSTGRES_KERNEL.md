# PostgreSQL Trust Kernel 어댑터

`services/api/evoforge/postgres_kernel.py`는 정본의 `core.reserve_cost`,
`core.settle_reservation`, `core.authorize_merge`를 실제 PostgreSQL 연결에서 호출한다.
2026-10-27 PostgreSQL 15.19에서 수용 테스트 **21개**가 통과했다.
같은 실행에서 참조 테스트 112개, SQL 계약 96개와 패키지 검사도 통과했다.

## 단위와 컨텍스트

- 금액은 양의 int64 **micro-USD**다. float·bool·문자열 금액을 거부한다.
  기존 메모리 원장의 cents는 `cents_to_micros`로 정수 변환한다(1 cent = 10,000 micro-USD).
- `KernelScope(tenant_id, project_id)`는 서버의 인증된 프로젝트 컨텍스트에서 만든다.
  모델 출력이나 요청의 임의 tenant/project 값을 사용하지 않는다.
- 각 호출은 자체 연결·트랜잭션을 사용하고 `SET LOCAL ROLE core_app` 및 테넌트/프로젝트 GUC를 적용한다.
  영수증 조회 동안에는 `ctx_gateway` 역할을 사용한다. 서비스 DB 로그인에는 두 역할의 멤버십이 필요하다.
- 연결 오류의 원문·DSN은 외부 오류 메시지로 내보내지 않는다.

## 예약과 영수증

`reserve_cost(call_id, period, amount_micros)`는 UUID call ID로 예약과 provider intent를 함께 기록한다.
동일 ID의 재시도는 기존 결과를 반환하며, 금액·기간을 바꾼 재사용은 거부한다.
테넌트 단위 잠금과 정본 함수로 병렬 요청의 예산·선불 크레딧 초과를 막는다.

호출을 보내기 직전에 `mark_sent`로 기록한다.
확실한 미접수만 `release_not_accepted`로 해제한다.
같은 tenant/project/call의 영수증이 이미 있으면 정산 전에도 해제를 거부한다.
문서 없는 기존 ctx 영수증·추정 영수증·0원 견적도 대사를 기다리며 예약을 유지한다.
영수증 저장과 같은 예약 행 잠금을 사용하고, 잠금 대기 뒤 새 statement로 조회해 직전에 커밋된 영수증도 확인한다.
정상 미접수의 멱등 해제와 다른 호출/프로젝트의 영수증 격리는 유지한다.
확장 009는 별도 ctx 적재와 직접 예약 SQL도 같은 행 잠금으로 직렬화한다.
새 예약·전송·실제 해제는 두 트리거가 실행되지 않는 상태이면 503으로 거부한다.
적용 순서·권한·직접 SQL 검증은 [DB 영수증/해제 보호](USAGE_RELEASE_GUARDS.md)를 따른다.
결과가 불명확하면 `mark_unknown`으로 기록하고 금액을 계속 예약한다.
새 어댑터 인스턴스에서도 UNKNOWN이 유지되며 무조건 재전송·환불할 수 없다.

`settle_reservation(call_id, receipt_id, customer_micros)`는 같은 테넌트·프로젝트·call ID에 속한
플랫폼 영수증과 공급사 참조를 요구한다. 공급사 비용과 가격표 버전은 DB 영수증에서 읽는다.
정본 정산 함수의 원장 기록과 provider intent의 CONFIRMED 변경은 한 트랜잭션이다.
같은 영수증·금액의 재시도는 중복 청구하지 않으며, 변경된 재시도는 거부한다.
UNKNOWN도 이 영수증 경로로 정산할 수 있다.

예약보다 높은 실제 비용은 정본의 `overrun` 표시를 보존한다.
기존 테이블에 없는 상태나 잔액 열을 추가하지 않았다.

## 병합 승인

`authorize_merge(candidate_id, current_head_sha, policy_hash)`는 DB의 승인 함수를 호출한다.
게이트·독립 리뷰가 부족하거나 검증 후 head가 달라지면 거부된다.
이 메서드는 후보 상태나 GitHub 저장소를 변경하지 않는다.

## 검증 실행

```powershell
python -m venv .local/venv-api
& '.\.local\venv-api\Scripts\python.exe' -m pip install -r services/api/requirements.txt -r tools/requirements-validation.txt
& '.\.local\venv-api\Scripts\python.exe' tools/validate_local_pg.py --kernel-tests
```

PostgreSQL 바이너리 준비는 [로컬 검증 절차](LOCAL_POSTGRES_VALIDATION.md)를 따른다.
GitHub Actions와 Cloud Build에도 실제 어댑터 수용 테스트를 연결했다.
테스트용 `EVO_TEST_DATABASE_URL`은 전용 일회용 서버를 가리켜야 한다.
기존 Trust Kernel 역할이 있는 서버에서는 테스트 픽스처가 실행을 거부한다.

검증한 항목은 재시작 후 예약 유지, 동시 요청의 중복 방지·예산 준수, strict 금액,
UNKNOWN의 예약 유지, 확정 미접수 해제, 영수증 바인딩·중복 청구 방지,
테넌트/프로젝트 격리와 RLS 거부, DB의 병합 승인 거부·허용이다.

## 남은 연결 작업

기존 Generate/Review는 현재 메모리 원장을 사용한다. 새 어댑터를 해당 경로에 연결하려면 서버가 검증한
사용자/프로젝트 컨텍스트, 컨텍스트 패킷·영수증 저장, 공급사 allowlist와 Broker 호출을 연결해야 한다.
그 전에 영수증을 임의 생성하거나 DB 실패 시 메모리 원장으로 대체하지 않는다.
정본에 없는 `project_budgets`를 참조하던 미사용 `ledger.reserve_pg/settle_pg` 코드는 제거했다.
실제 Muse Spark 호출·GitHub 작업·배포 검증은 계속 별도 미완료 항목이다.

후속 작업으로 [인증된 내부 FastAPI 경로](INTERNAL_KERNEL_API.md)를 연결하고 실제 DB HTTP 포함 25개를 통과했다.
Generate/Review의 패킷·영수증 연결은 계속 남아 있다.

후속 영수증 문서 검증·원자적 보존과 저장 금액 정산은
[RECEIPT_PERSISTENCE.md](RECEIPT_PERSISTENCE.md)에 기록했다.

Builder 패킷·동의·task fencing과 예약을 함께 확인하는 지원 경로는
[BUILDER_PREFLIGHT.md](BUILDER_PREFLIGHT.md)에 기록했다.

테넌트의 여러 프로젝트가 같은 선불 잔액을 초과해 예약하는 RLS 경계는 확장 007에서 추가 검사한다.
신규 예약 어댑터는 이 가드가 없거나 실행되지 않는 설정이면 503으로 거부한다.
기존 데이터 백필과 범위는 [TENANT_CREDIT_GUARD.md](TENANT_CREDIT_GUARD.md)를 따른다.

## 병합 승인 시점의 정책과 자격

어댑터는 후보·task·run 행의 공유 잠금 아래에서 요청 head/policy가 현재 서버 run과 일치하는지 확인한다.
정본 `core.authorize_merge`로 모든 필수 게이트·독립 리뷰·HIGH/CRITICAL 사람 승인 등을 검사한다.
HIGH/CRITICAL은 같은 risk/harness의 context-independent spec-first approve 검증자 자격이 실제 DB 시각에도 유효해야 한다.
트랜잭션 시작 시각에 고정된 `now()`만으로 지연/잠금 대기 후 만료된 자격을 승인하지 않는다.
자격 시험 모듈·정본 함수·필수 증거를 변경하거나 새 승인/리뷰를 생성하지 않는다.

이 API는 검사 시점의 판정이다. 실제 외부 병합 전에 다시 검사하고 같은 expected head를 사용하는 절차가 필요하며,
이 어댑터는 GitHub merge를 실행하지 않는다. 검증 원본은 `docs/validation/2026-10-27-merge-freshness.json`을 따른다.
수정 전 새 회귀 **2 failed**, 수정 후 API **465 passed·1 skipped**·실제 PostgreSQL **147 passed**,
참조 **112개**·SQL **96개**·계약 **0 failure**·웹 빌드 통과. 만료 거부와 새 유효 자격의 정상 승인을 함께 확인했다.
게이트·리뷰·사람 승인·자격은 이 검사의 합성 DB fixture이며 실제 운영 승인이나 외부 병합 완료 증명이 아니다.
