# Codex 개발 참여 기록

2026-10-27 (Asia/Seoul). 첫 작업 범위는 API의 검증 게이트와 회귀 테스트다.
웹·인프라·비용 원장 등이 함께 변경되는 작업 트리에서 해당 구현을 보존하고,
`docs/evoforge-v4.2/`의 계약·참조 구현은 변경하지 않았다.

## 반영한 변경

- `services/api/evoforge/gates.py`: 생성 경로도 전체 무결성 판정기를 사용한다.
  봉인 held-out 증거가 없으면 강한 테스트 코드만으로 `GH_INTEGRITY=PASS`를 주지 않는다.
- 한 코드 조각에 있는 모든 테스트 함수를 오라클 강도 비율에 포함한다.
- 문법 오류, 테스트 함수 없음, 누락·빈 값·문자열이 아닌 `code`를 집계에서 버리지 않는다.
  해당 증거는 무결성 통과를 막고 `G2_REQUIRED=FAIL`로 기록한다.
- 생성 경로에서도 assertion 삭제, skip 추가, 강제 성공 종료, 보호된 CI 파일 변경을 탐지한다.
- 오라클·held-out·보상 해킹 판정에 동일하게 로드한 `quality_gates.json`을 전달한다.
  사람 라벨 holdout 199/200건의 잠정 규칙 경계도 이 설정을 따른다.
- `services/api/tests/test_integrity_contract.py`: 계약 경계와 실패 사례 20개를 추가했다.

게이트 변경은 현재 저장소의 `4f74b02`에, 회귀 테스트는 `cfad8dd`에 포함되어 있다.

## 검증 근거

저장소 루트에서 실행:

```powershell
python -m pytest services/api -q
python -I docs/evoforge-v4.2/tools/validate_package.py
```

- API: 기존 7개 + 회귀 20개 = **27 passed**.
- 수정 전 새 회귀 테스트: **14 failed, 6 passed**. 수정 후 전체 통과.
- 패키지 검증: C1–C7·C9 통과, 참조 테스트 **112개** 통과.
- TestClient 추가 확인: `code=null`을 포함한 증거는 HTTP 200으로 판정을 반환하며
  `GH_INTEGRITY=INCONCLUSIVE`, `G2_REQUIRED=FAIL`이다.
- PostgreSQL 검사(`--pg`), 실제 공급사 호출, 클라우드 배포는 이번 검증 범위에 포함하지 않았다.
  정적 게이트 판정은 테스트 실행·병합 승인 증명이 아니다.

## 다음 개발자가 바로 이어갈 항목

1. **모델 호출 실패 시 비용 예약 처리.** `main.generate`에서 Builder 예외를 주입하면
   HTTP 500 이후 `ledger.snapshot()`에 `reserved_cents=120`이 남는다.
   공급사 접수 전 실패와 접수 후 결과 불명의 상태를 구분하고,
   예약 해제 또는 영수증 대사 정책을 적용해야 한다. 결과가 불명확한 호출을 일괄 환불하지 않는다.
2. **실행 통계 입력 검증.** `/v1/gates/evaluate`에 `vis_pass=2, vis_n=1`을 주면 HTTP 500이다.
   성공 수·전체 수의 범위와 관계를 요청 경계에서 검증하고 HTTP 422로 거부할 필요가 있다.
   0건 실행도 임의의 1건으로 바꾸지 말고 증거 부족으로 처리해야 한다.
3. **실제 diff 적용과 검증 PR 연결.** `evoforge/github.py`는 diff의 추가 행만 모아
   파일 전체 내용으로 업로드한다. 기존 파일 수정 시 문맥과 유지할 행을 잃을 수 있다.
   기준 SHA에 unified diff를 적용·검증한 결과를 업로드하고,
   PR에 기록하는 게이트도 서버가 저장한 후보·증거와 연결해야 한다.
4. **실행·저장 계층 연결.** 현재 실행 수치는 요청 입력이고 명령·증거·원장은 메모리에 있다.
   실제 Runner 결과와 봉인 테스트, 공급사 영수증, PostgreSQL의 예약·승인 경로를 연결하는 작업이 남아 있다.

위 항목의 실패 주입은 별도 Python 프로세스와 mock Builder로 수행했으며 외부 API를 호출하지 않았다.

## 후속 사용자 지시와 자동 재개

사용자는 Muse Spark를 메인 모델로 유지하고, 미완료 상태에서 작업이 끝나면 다시 깨어나
마무리하도록 지시했다. 현재 채팅에 자동화 `evoforge`를 활성화했으며 15분마다 이어서 확인한다.
최신 작업 목록과 완료 근거는 [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md)를 기준으로 갱신한다.

## 2026-10-27 자동 재개: CI 환경 보강

Claude의 API 수정은 `eff542f`로 병합되었고 API 테스트 93개가 통과한 것을 재확인했다.
동일 API 파일을 변경하지 않고 CI의 의존성 설치·PostgreSQL 서비스·웹 빌드를 보강하고 `560a5ef`에 반영했다.
새 가상환경의 참조 테스트 112개와 웹 프로덕션 빌드도 통과했다.
실제 SQL 검사와 컨테이너 실행은 로컬 도구가 없어 미검증이며,
자세한 변경과 재현 명령은 [CI_VALIDATION.md](CI_VALIDATION.md)에 남겼다.

## 2026-10-27 자동 재개: SQL 실제 검증

공식 Windows용 PostgreSQL 15.19 바이너리를 `.local/`에 두고, 시스템 설치 없이 일회용 클러스터에서
패키지 검증기의 `--pg`를 실행하는 `tools/validate_local_pg.py`를 `71ed84f`에 추가했다.
SQL 96개와 참조 테스트 112개, C1–C9 전체가 실제로 통과했다. 서버 종료와 임시 클러스터 정리도 확인했다.
앞 절의 SQL 미검증 상태는 해소되었으며, Docker/클라우드 실행은 계속 미검증이다.
FastAPI의 실제 DB 연결은 별도 과제로 남았다. [검증 절차](LOCAL_POSTGRES_VALIDATION.md)에 범위와 재현 방법을 기록했다.

## 2026-10-27 자동 재개: PostgreSQL 어댑터

`evoforge/postgres_kernel.py`에 정본의 예약·정산·병합 승인 함수 호출을 구현하고 실제 DB 수용 테스트 21개를 통과했다.
병렬 예산·중복 예약, 재시작 후 UNKNOWN 유지, 영수증과 call ID 바인딩, 중복 정산 방지,
RLS 거부와 독립 리뷰·게이트·head에 따른 병합 승인 거부/허용을 확인했다.
기존 API 93개도 통과했다. 정본 SQL을 수정하지 않았고, 잘못된 `project_budgets` 미사용 스텁은 제거했다.
FastAPI의 컨텍스트·패킷·영수증 연결과 실제 모델·Runner·배포는 남아 있다.
어댑터 사용·범위·CI와 로컬 검증은 [POSTGRES_KERNEL.md](POSTGRES_KERNEL.md)에 기록했다.

## 2026-10-27 자동 재개: 공급사 호출 경계

DB 요청 연결에 앞서 실제 모델 호출의 재시도·비용 경계를 보강했다.
공용 SDK 클라이언트는 자동 재시도를 하지 않으며, 실제 Critic은 두 호출을 각각 예약·정산한다.
Phase A 성공 후 B가 실패해도 A의 지출과 응답 문서를 보존한다. B의 401/429는 해당 예약만 환불하고,
timeout/5xx는 UNKNOWN을 유지한다. B가 A의 테스트를 바꾸거나 모델 JSON이 메타데이터를 위조하지 못한다.
신규 23개·API 총 116개를 통과했고 실제 공급사 호출은 하지 않았다.
금액은 현재 메모리 원장의 추정치이며 DB 요청 연결·정식 영수증·개발 CLI의 비용 예약은 남아 있다.
[호출 경계 검증 기록](PROVIDER_CALL_ACCOUNTING.md)을 참고한다.

## 2026-10-27 자동 재개: 인증된 내부 DB HTTP 경로

`/v1/kernel`에 서버 소유 tenant/project와 서비스 토큰을 사용하는 DB 요청 경로를 연결했다.
없는 토큰/스코프는 차단하며 요청 본문으로 연결·스코프를 바꾸지 못한다.
실제 DB에서 HTTP 예약·UNKNOWN·영수증 정산·중복 방지·402/404/409/503·병합 승인을 확인해 25개가 통과했다.
API 총 139개와 참조 112개·SQL 96개도 통과했다. 드라이버 없는 기본 앱의 시작도 확인했다.
기존 Generate/Review는 계속 메모리 원장을 사용하며 브라우저 사용자 인증·패킷·영수증 연결은 남아 있다.
설정과 제한은 [INTERNAL_KERNEL_API.md](INTERNAL_KERNEL_API.md)에 기록했다.

## 2026-10-27 지원 브랜치: 영수증 문서와 저장 금액 정산

`codex/receipt-support` (`C:\evo_forge_codex`)에서 정본 v1 영수증 검증, append-only 문서와 ctx 행의
원자적 저장, 예약/패킷/서버 스코프 바인딩, 저장 금액 정산과 내부 HTTP 경로를 구현했다.
동시 정산의 이전 intent 상태 혼합 문제와 선택 의존성 누락으로 생략되던 RFC3339 검사도 수정했다.
API **269 passed·1 skipped**, 일회용 PostgreSQL **46 passed**, 참조 112·SQL 96·계약 검사 전체 통과.
상위 Muse round3를 보존해 `89dbc71`에서 동기화했고 `228c272`로 main에 반영했다.
main 작업 폴더의 최종 API **291 passed·1 skipped**, 실제 DB **46 passed**, 참조 112·SQL 96·웹 빌드·audit 0건을 확인했다.
원본 로그와 SHA-256 manifest는 STATUS의 검증 기록을 확인한다.
남은 실제 공급사/워크플로/배포 연결과 0원 정산·영수증 정정 정책은
[RECEIPT_PERSISTENCE.md](RECEIPT_PERSISTENCE.md)에 구체적으로 남겼다.
