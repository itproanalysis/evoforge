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

## 2026-10-27 Builder preflight 지원

`codex/builder-preflight`의 `094b4aa`에서 Builder 패킷·동의·agent/task lease·목표/정책을 확인하고
예약과 불변 바인딩을 함께 저장한다. SENT 전 재검증과 바인딩된 정본 영수증 정산도 연결했다.
상위 round4를 보존해 동기화한 뒤 API 317 passed·1 skipped, 실제 DB 77 passed,
참조 112·SQL 96·패키지 검사와 웹 빌드가 통과했다.
마이그레이션·설정·남은 통합은 [BUILDER_PREFLIGHT.md](BUILDER_PREFLIGHT.md), main 반영 기록은 STATUS를 따른다.
`0551fbe`로 main에 반영했다. main의 API 시작/health/OpenAPI·패키지 검사·웹 빌드도 통과했다.

## 2026-10-27 요청 증거 PostgreSQL 영속화

`codex/evidence-persistence`의 `69add6e`는 기존 요청·비공개 봉인 리뷰·이벤트/체인을 선택 모드에서 PostgreSQL로 저장한다.
실제 Runner 실행 후 새 API 프로세스에서도 복원하며, HTTP 봉인 마스킹과 tenant/project RLS를 유지한다.
API 403 passed·1 skipped, 실제 DB 81 passed, 참조 112·SQL 96·패키지 검사·웹 빌드 통과.
명령·공개 원장은 아직 메모리이고, 운영 DB 적용·전체 P0-2 완료는 별도다.
[설정과 경계](EVIDENCE_PERSISTENCE.md), main 반영 기록과 원본 로그는 STATUS를 따른다.
`1554547`로 main에 반영했고 main API 시작/health/OpenAPI도 확인했다. 선택 모드는 운영에 자동 활성화하지 않았다.

## 2026-10-27 Canonical 명령 저장 지원 준비

`codex/commands-persistence` (`C:\evo_forge_codex`)의 `9bfe0bc`는 정본 명령 접수·상태 전이,
확장 004의 이력·완료 응답과 단일 dispatch를 실제 PostgreSQL에서 검증했다.
API 403 passed·1 skipped, 실제 DB 91 passed, 참조 112·SQL 96·패키지 검사·웹 빌드 통과.
검증 manifest는 해당 브랜치의 `b94a16a`, 원본은 main `.local/evidence/api-commands-20261027-9e7itreq`에 보존했다.

상위 Muse round7의 main/mission 편집과 겹치지 않도록 현재는 별도 모듈 단계다.
상위 작업을 먼저 main에 반영한 후 `commands.py` 위임과 Generate의 예약 전 dispatch·성공 응답 저장을 연결한다.
이미 전송된 미완료 명령은 재호출 없이 409/대사 대상으로 유지하고, memory 기본 모드는 보존한다.
공개 경로 연결·main 병합·운영 DB 적용·canonical 비용/mission 영속화는 완료되지 않았다.

## 2026-10-27 Runner 실행 증거와 core 후보/G2 지원

`codex/runner-core-evidence` (`C:\evo_forge_codex` 현재 체크아웃)의 `3526ae0`는 정산된 Builder 바인딩과
커밋된 head의 실제 Runner 재실행 증거를 대조해 G2_REQUIRED를 원자적으로 기록하는 내부 경로다.
필수 증거가 없는 `core.authorize_merge` 거부를 유지하며 후보 상태·다른 게이트·승인을 만들지 않는다.
API 414 passed·1 skipped, 실제 DB 91 passed, 참조 112·SQL 96·패키지 검사·웹 빌드 통과.
인증 경계 회귀 테스트는 `21707ed`, manifest는 `75ca7f8`, 원본은 main `.local/evidence/runner-core-20261027-m9gl2ykz`에 있다.
실제 로컬/번들 Runner를 사용하되 Critic·영수증·image 식별자는 합성 fixture다. Docker/운영 배포·실청구 검증은 하지 않았다.

상위 round7을 먼저 main에 반영한 후 두 지원 브랜치를 통합한다. `commands-persistence`는 별도 브랜치로 보존했다.
공유 Codex DB 테스트 끝부분은 두 브랜치의 새 테스트를 모두 보존해 병합해야 한다.
상위 T19는 `_generate_core`/`_review_core`/`_run_core`/`_pr_core`를 웹·mission이 공유하도록 리팩터링했다.
명령 dispatch/완료 연결은 endpoint만이 아니라 이 공유 core 호출 경로를 기준으로 검토한다.
공개 canonical 후보 생성·실제 요율/청구·다른 게이트/독립 리뷰·운영 DB/Runner 설정은 계속 미완료다.

## 2026-10-27 PostgreSQL 지원 통합과 Worker 인증

현재 `C:\evo_forge_codex`는 `codex/pg-integration`이다. 두 원 지원 브랜치를 합쳤고(`edffa84`),
상위 round7 `d347b56`이 먼저 main에 반영된 뒤 `911c41d`에서 동기화했다.
이후에는 통합 브랜치 하나를 기준으로 이어간다. 두 테스트 끝부분·Runner base fixture·두 환경 설정을 모두 보존했다.

`83798f9`: 내부 명령 HTTP 접수/dispatch/완료/조회, 같은 scope의 생성 증거 FK와 candidate/gates 일치,
응답 없는 APPLIED 커밋을 거부하는 지연 제약과 core_app/RLS 검증.
`b29c3a9`: Google ID 인증을 유지하며 내부 비밀값을 X-Evoforge-Kernel-Token으로 분리한다.
API 463 passed·1 skipped, 실제 DB 107 passed, 참조 112·SQL 96·패키지 검사·round7 웹 빌드 통과.
인증 35개는 API 집계에 포함되며 Google 서명 검증은 fixture다.
manifest는 `9ce7093`, 원본은 main `.local/evidence/pg-integration-20261027-wm8m7mca`에 있다.

Muse T22가 새 `muse/round8`에서 main을 편집 중이므로 main.py·commands.py의 공개 접점은 아직 수정하지 않았다.
T22를 main에 먼저 반영한 뒤 통합 브랜치에 동기화하고, facade 위임과 `_generate_core`/mission의 명시적 dispatch·완료를 연결한다.
통합 코드의 main 병합·공개 비용/상태·정본 전체 승인·실제 모델 청구·운영 배포는 계속 미완료다.

## 2026-10-27 Mission 상태 PostgreSQL 저장 지원

통합 브랜치 `codex/pg-integration`의 `50ffc5b`는 mission facade와 확장 006에 상태·단계 증거를 저장한다.
입력·HIGH 확인·상태 전이·증거 불변성과 scope 격리를 DB에서 검사한다.
완료 출력과 전체 이벤트가 한 개이면 조회가 복원하고, 불완전/중복 출력은 409로 대사를 기다린다.
모델을 재전송하지 않으며 취소된 상태는 앞으로 복원하지 않는다. 기본 memory 모드는 유지했다.

API 463 passed·1 skipped, 실제 DB 118 passed(mission 신규 11개 포함), 참조 112·SQL 96·계약 0 failure·웹 빌드 통과.
새 API 프로세스 복원과 실제 로컬 Runner를 검증했고 Builder/Critic/GitHub는 합성 fixture다.
manifest는 지원 브랜치의 `docs/validation/2026-10-27-mission-persistence.json`,
원본은 main `.local/evidence/mission-persistence-20261027-04hrzi1i`, 범위는 `docs/MISSION_PERSISTENCE.md`에 있다.

이 코드는 main 미반영이다. Muse T22의 main/평가/UI·봉인 테스트를 보존하고 상위 병합 후 동기화한다.
공유 `_generate_core`·mission의 호출 전 실행권·canonical 명령/비용·UNKNOWN 대사와 원자적 Objective 기록은 후속 작업이다.
공개 command/ledger/performance 저장, 전체 승인·실제 청구·운영 마이그레이션/배포도 계속 미완료다.
API min=max=1·Muse Spark `muse-spark-1.3`과 현재 채팅의 자동 재개를 유지한다.

## 2026-10-27 Critic 호출 증거 복구 보강

지원 브랜치 `codex/pg-integration`의 `4bbbf6d`는 완료된 리뷰의 provider_evidence_ids를
mission 단계 포인터와 같은 버전에 복원한다. SQL도 호출 레코드의 scope·kind·phase·mission_id와 ID 누락을 검사한다.
수정 전 집중 회귀 8개 실패, 수정 후 API 463 passed·1 skipped·실제 DB 131 passed(신규 13개)·
참조 112·SQL 96·계약 0 failure·웹 빌드 통과. 공식 SDK+모의 HTTP로 리뷰 API 연결 중단 세 지점을 확인했다.
실제 모델 청구·운영 배포 검증은 수행하지 않았다.

manifest: 지원 브랜치의 `docs/validation/2026-10-27-review-recovery.json`.
원본 로그 8개: main `.local/evidence/review-recovery-20261027-qvkgnfg8`.
이전 확장 006 초안을 적용한 테스트 DB에는 해당 SQL을 재적용한다. 과거 snapshot은 그대로 보존한다.

집계 리뷰 출력이 없는 UNKNOWN은 모델 호출 전 mission/command 바인딩과 대사가 필요하다.
이 기록은 기존 추정 원장 감사 자료이며 canonical 정산으로 계산하지 않는다.
T22의 상위 병합 뒤 공유 core·공개 명령/비용 연결을 이어가고, 그 전까지 같은 main 파일을 편집하지 않는다.
지원 코드의 main 반영·전체 개발·운영 DB/실청구 통합은 미완료이며 자동 재개를 유지한다.

## 2026-10-27 테넌트 전체 선불 예약 보호

지원 브랜치 `codex/pg-integration`의 `5b5b253`은 프로젝트 RLS 때문에 다른 프로젝트 예약이 숨겨져
테넌트 선불을 초과하던 문제를 확장 007의 비공개 hold 합계로 차단한다. 정본 함수와 프로젝트 RLS는 변경하지 않았다.
UNKNOWN을 유지하고 정상 종료에만 hold를 해제하며, 가드가 실행되지 않으면 새 예약을 503으로 거부한다.
기존 예약 백필과 반복 적용, FORCE RLS 복원, 실제 core_app 세션의 private 테이블 접근 거부도 확인했다.

API 463 passed·1 skipped, 실제 DB 139 passed(신규 8개), 참조 112·SQL 96·계약 0 failure·웹 빌드 통과.
수정 전 재현 1 failed, 병렬 24건 중 10건만 잔액 내 예약을 허용했다.
manifest는 지원 브랜치 `docs/validation/2026-10-27-tenant-credit-guard.json`, 원본 8개는
main `.local/evidence/tenant-credit-guard-20261027-ezvkqtpw`, 범위는 `docs/TENANT_CREDIT_GUARD.md`에 있다.

DB에 확장 007을 먼저 적용한 뒤 새 API를 배포해야 한다. 이번 검증은 운영 DB/실청구/배포를 수행하지 않았다.
Muse T22를 먼저 main에 반영한 다음 지원 브랜치에 동기화한다. 공개 명령/비용·전체 승인 연결은 계속 미완료이며,
기본 Muse Spark와 자동 재개를 유지한다.

## 2026-10-27 canonical Builder 후보 등록 연결

지원 브랜치 `codex/pg-integration`의 `e947cbf`는 내부 Worker 후보 POST/GET을 연결한다.
정산된 call·영수증/원장·SDK request ID·서버 출력과 reserved base→head의 전체 Git 변경/visible 테스트를 확인한 뒤,
PROPOSED 후보와 확장 008 binding을 함께 저장한다. Git 확인 후 fencing/출력을 재검사하고 binding 실패 시 후보도 롤백한다.
등록 후 head drift는 Runner/G2와 과거 PASS 재전송을 차단한다. 다른 게이트·리뷰·승인을 만들지 않는다.

API 465 passed·1 skipped·실제 DB 144 passed(신규 5개)·참조 112·SQL 96·계약 0 failure·웹 빌드 통과.
실제 Git/로컬 Runner/DB를 사용했고 Builder/Critic/영수증/checkout transport는 합성 fixture다.
동시 등록 8회·재시작 조회·G2 연결·병합 거부·metadata/Git/fence/원자적 롤백을 확인했다.
manifest: 지원 브랜치 `docs/validation/2026-10-27-candidate-registration.json`.
원본 7개: main `.local/evidence/candidate-registration-20261027-u3iva17t`.
경로와 제한: `docs/CANDIDATE_REGISTRATION.md`. 새 API 전 DB 확장 008까지 적용해야 한다.

T22의 상위 main 반영을 먼저 기다리고 지원 브랜치에 동기화한다. 현재 main/commands.py의 공개 접점은 그대로다.
공개 Broker 전송·비용/명령·후보 등록 호출·PR base 전달·독립 리뷰/전체 승인·실청구/운영 반영은 계속 미완료다.
Muse Spark 기본값과 자동 재개를 유지한다.

## 2026-10-27 정산/예약 경합의 프로젝트 cap 보호

지원 브랜치 `codex/pg-integration`의 `c479487`은 기존 호출의 정산이 초기 cap 확인 뒤 커밋되는 경합을 재검사한다.
확장 007이 INSERT 시점에 현재 프로젝트 사용액/cap과 테넌트 잔액/hold를 같은 snapshot에서 확인한다.
기존 실제 정산은 유지하고 한도를 넘는 새 예약만 거부한다. 정본 함수·RLS·승인 경계는 보존했다.

수정 전 회귀 1 failed, 수정 후 API 465 passed·1 skipped·실제 DB 145 passed·참조 112·SQL 96·계약 0 failure·웹 빌드 통과.
초기 예약 100→정산 900µUSD(cap 1000) 경합에서 신규 900을 거부하고 잔여 100을 허용했다.
manifest는 지원 브랜치 `docs/validation/2026-10-27-project-cap-race.json`, 원본 8개는
main `.local/evidence/project-cap-race-20261027-4io029zf`에 있다. 이전 지원 초안의 007을 쓴 테스트 DB는 재적용한다.

T22의 Muse runner가 실행 중인 것을 확인해 중복 실행하거나 main 파일을 변경하지 않았다.
상위 T22를 먼저 main에 반영한 뒤 지원 브랜치에 동기화한다. 공개 명령/비용·실청구/운영 통합은 미완료이며 자동 재개를 유지한다.

## 2026-10-27 병합 승인 정책/자격 시점 보강

지원 브랜치 `codex/pg-integration`의 `1441518`은 현재 run의 head/policy를 공유 잠금으로 확인하고,
정본 core.authorize_merge 호출 뒤 HIGH/CRITICAL 자격을 clock_timestamp()로 재검사한다.
정책이 바뀌었거나 지연 중 만료된 자격은 거부한다. 승인·게이트·리뷰를 만들거나 실제 merge를 실행하지 않는다.

수정 전 회귀 2 failed, 수정 후 API 465 passed·1 skipped·실제 DB 147 passed(신규 2개)·
참조 112·SQL 96·계약 0 failure·웹 빌드 통과. 새 유효 자격의 정상 승인도 함께 확인했다.
합성 게이트/리뷰/사람 승인/자격 DB fixture이며 실제 운영 승인은 아니다.
manifest: 지원 브랜치 `docs/validation/2026-10-27-merge-freshness.json`.
원본 8개: main `.local/evidence/merge-freshness-20261027-jomlv8hr`. 검사 한계는 `docs/POSTGRES_KERNEL.md`를 따른다.

상위 Git 설치 CI/test collection 수정은 동기화했고 T22·Agy 소유 파일은 보존했다.
T22 main 반영 뒤 공개 경로 연결을 이어간다. 실제 모델/비용·전체 승인·운영 연결은 미완료이며 자동 재개를 유지한다.

## 2026-10-27 상위 변경을 포함한 지원 통합 재검증

지원 브랜치 `codex/pg-integration`의 `41949da`에서 main `2cb3627`까지 동기화했다.
CR 모듈/수용 테스트(`ebfeb95`), Critic 16k 출력 예산(`fa02e57`), 웹 배포(`25480fd`),
Git 설치/CI collection·배포 인프라 변경과 Codex PostgreSQL 지원/승인 시점 보강을 함께 보존했다.

API 485 passed·1 skipped·실제 DB 147 passed·참조 112·SQL 96·계약 0 failure·웹 빌드 통과.
manifest: 지원 브랜치 `docs/validation/2026-10-27-upstream-sync.json`(source 33개·로그 6개 SHA-256).
원본: main `.local/evidence/upstream-sync-20261027-n32bxlnp`. 기존 manifest는 각 과거 revision의 근거로 보존한다.

실제 DB/Git/Runner를 사용했고 모델/영수증·승인/자격은 합성 fixture다. 실 KMS·청구·Docker/운영 배포는 미검증이다.
T22의 main 반영이 먼저다. 이후 공개 command dispatch/완료·Broker 비용/영수증·후보/전체 승인 접점을 연결한다.
전체 개발은 미완료이고 Muse Spark 기본값·자동 재개를 유지한다. 지원 코드는 아직 main에 합치지 않았다.

## 2026-10-27 영수증 저장 후 예약 해제 보호

지원 브랜치 `codex/pg-integration`의 `61c608b`는 정산 전 기록된 영수증이 있는데도 미접수로 예약을 해제하던 경로를 차단한다.
같은 scope/call의 ctx 영수증을 예약 잠금 뒤 새 statement로 검사하며 추정/0원·문서/공급사 참조 누락도 대사를 기다린다.
다른 호출/프로젝트의 정상 미접수 해제·멱등성과 정상 견적 정산은 유지했다.

수정 전 회귀 7 failed·1 passed, 수정 후 신규 8 passed·API 485 passed·1 skipped·실제 DB 155 passed·
참조 112·SQL 96·계약 0 failure·웹 빌드 통과. 저장 트랜잭션의 실제 행 잠금 대기 후 해제 거부도 확인했다.
manifest: 지원 브랜치 `docs/validation/2026-10-27-receipt-release.json`(source 36개·로그 8개 해시).
원본: main `.local/evidence/receipt-release-20261027-tp1nltz3`. 정본 함수/RLS와 기존 금전 기록은 보존했다.

외부 영수증 적재 서비스에도 같은 예약 잠금 규약이 필요하다. 실제 청구/배포는 미검증이고 0원·실청구 정정 정책은 계속 미완료다.
T22 Muse/OpenCode 실행이 동작 중이므로 중복 실행하지 않았다. 상위 main 반영 후 공개 명령/Broker 비용·전체 승인 연결을 이어간다.
전체 개발은 미완료이고 Muse Spark 기본값·자동 재개를 유지한다. 지원 코드는 main 미반영이다.

## 2026-10-27 PR 기준 커밋과 작업 브랜치 보호

지원 브랜치 `codex/pg-integration`의 `f11f0ae`는 `expected_base_sha`가 있으면 그 커밋에서만 파일을 읽고
기준 브랜치가 검증한 SHA인지 전후로 확인한다. 기존 ref 호출도 이동을 감지하고 이미 존재하는 작업 브랜치는 재사용하지 않는다.
기존 ref 호출의 중간 이동 후 원복은 감지하지 못하므로 공개 `_pr_core`는 서버 기준 SHA 전달 연결이 필요하다.

수정 전 새 회귀 9 failed, 수정 후 기존 Critic 포함 34 passed·API 508 passed·1 skipped·실제 DB 166 passed·
참조 112·SQL 96·계약 0 failure·웹 빌드 통과. 실제 Git 커밋과 합성 GitHub transport이며 실제 PR/배포는 아니다.
첫 DB 실행은 180초 제한으로 종료돼 원본을 보존했고, 도구 제한을 300초로 조정한 `912ea9d`에서 221초에 통과했다.
manifest: 지원 브랜치 `docs/validation/2026-10-27-pr-snapshot.json`, 원본 9개: main `.local/evidence/pr-snapshot-20261027-6wq9831x`.

검증은 main `3495cdc`까지 포함한다. 이후 main `dca4709`의 증거별 테스트 파일명과 canonical 후보 등록 검증을 동기화한다.
상위 T22·다른 개발 작업을 보존한다. 공개 비용/승인·운영 통합은 미완료이고 Muse Spark 기본값·자동 재개를 유지한다.

## 2026-10-27 DB 영수증 적재/해제 경합 보호

지원 브랜치 `codex/pg-integration`의 `afecb31`·확장 009가 별도 ctx_gateway 적재와 직접 core_app 해제를
같은 예약 행 잠금으로 직렬화한다. 양방향 경합에서 충돌하는 두 번째 작업을 거부하며 실패 변경을 원자적으로 롤백한다.
가드 삭제/비활성/replica 설정이면 새 예약·전송·실제 해제는 503이다. 정본 함수/정책·RLS·기존 금전 기록은 보존했다.

수정 전 10 failed, 수정 후 집중 11 passed·API 485 passed·1 skipped·실제 DB 166 passed·
참조 112·SQL 96·계약 0 failure·웹 빌드 통과. 실제 분리된 DB 계정과 행 잠금 대기·반복 DDL/권한 보존을 검증했다.
manifest: 지원 브랜치 `docs/validation/2026-10-27-db-usage-guard.json`(source 38개·로그 8개 해시).
원본: main `.local/evidence/db-usage-guard-20261027-ur5bi8s3`. 적용/범위: 지원 브랜치 `docs/USAGE_RELEASE_GUARDS.md`.

새 API 전에 확장 009까지 적용해야 한다. 운영 DB/실청구·Docker 이미지/배포는 미검증이며 기존 충돌 청구·0원/정정 정책은 별도다.
상위 T22 main/평가/UI·봉인 테스트를 보존했다. 상위 main 반영 뒤 공개 명령/Broker 비용·전체 승인 연결을 이어간다.
전체 개발은 미완료이고 Muse Spark 기본값·자동 재개를 유지한다. 지원 코드는 main 미반영이다.

## 2026-10-27 후보 실행 증거·CLI 청구 근거·Muse capability

`9bbc7c2`가 `b243426`까지 main에 통합했다. 서버 실행 증거와 후보 Git tree/증거별 테스트 파일명 연결,
확장 010, 청구액 미확인 시 UNKNOWN 예약 유지가 포함된다. 실제 PostgreSQL·Git·Runner 169개,
SQL 96·참조 112·CLI 집중 29개·정본 검사 0 failure를 통과했다. 모델/청구/리뷰/HTTP는 합성 fixture다.
원본: `.local/evidence/tagged-candidate-20261027-q6zgkkht`, `.local/evidence/cli-billing-20261027-3tagslmg`.
소스·로그 해시: `docs/validation/2026-10-27-candidate-cli-followup.json`.
전체 API 538개(1 skipped)도 통과했다. 실제 provider 출처 확인, 공개 명령과 DB 경로의 연결, 운영 배포는 미완료다.

별도 `codex/muse-capabilities`의 `e9a1168`은 Meta 공식 직접 API·Muse Spark의 보수적인 capability를
정본 schema와 S1–S11에 연결하고 만료·프록시·미확인 캐시 모드를 차단한다. 집중 22개·계약 검사는
통과했고 전체 API 검사가 진행 중이다. main 미반영; 원본 `.local/evidence/muse-capability-20261027-a799ryo1`.
T22와 다른 작업을 보존하고 완료 전 현재 채팅의 자동 재개를 유지한다.

## 2026-10-27 CLI 원본 사용량 후속

`codex/pg-integration` `545b1f6`은 CLI 원본 JSON 사용량을 그대로 보존하고 실청구 출처 명시가 없으면
UNKNOWN 예약을 유지한다. 수정 전 9 failed, 수정 후 관련 집중 38 passed. 원본은
`.local/evidence/cli-raw-usage-20261027-8igvgow9`. 실청구 인증·전체 API/DB 재검증·main 반영은 미완료다.

## 2026-10-28 preflight 신선도·권한 재검사

`codex/preflight-freshness` `8437ef5`는 실제 서버 시각의 패킷·참조·리스 만료 및 전송 직전 패킷 digest,
허용 공급사·동의·리스 소유자/에포크를 확인한다. 수정 전 7+3 failed, 수정 후 집중 77 passed·계약 0 failure.
원본: `.local/evidence/preflight-freshness-20261028-y7cky9v4`. T22가 main에 반영되어 `f69106a`에 동기화했고
해당 revision의 실제 PostgreSQL 169개·SQL 96개·참조 112개·웹 npm ci/tsc/build·전체 API 618개(1 skipped)가 통과했다.
소스 79개와 로그 24개의 해시: `docs/validation/2026-10-28-preflight-freshness.json`.
main 작업 중인 runner/승격 Critic 파일은 건드리지 않았다.

이전 `e9a1168` API 560 passed·1 skipped·실제 PostgreSQL 169 passed·SQL 96·참조 112·웹 npm ci/tsc/build,
`ca0b584` API 569 passed·1 skipped 통과. 보강은 main 미반영이며 실제 provider 출처 인증 및 공개/운영 연결은 미완료다.

## 2026-10-28 공급사 허용·동의 보강

`codex/preflight-policy` `3740307`은 빈 allowlist가 기본 허용 목록으로 대체되거나 문자열 동의가 참으로
취급되는 경로를 차단한다. 수정 전 12 failed, 수정 후 관련 집중 94 passed·계약 0 failure.
원본 `.local/evidence/preflight-policy-20261028-2noz3me8`. 실제 PostgreSQL 169개·SQL 96개·참조 112개 및
동일 웹 소스 npm ci/tsc/build가 통과했고 전체 API는 검증 중이다. main 반영은 계속 필요하다.
기존 작업 파일과 겹치지 않도록 통합 브랜치 `5d4def9`을 준비했고 집중 94개도 통과했다.

## 2026-10-28 preflight main 통합 및 남은 경계

`f07089a`까지 main에 반영했고 `3740307` 검증본과 API·웹·정본 tree가 같다.
전체 API 635 passed·1 skipped, 실제 PostgreSQL 169 passed, SQL 96·참조 112·계약 0 failure,
동일 웹 npm ci/tsc/build·집중 94 passed. 원본/해시: `docs/validation/2026-10-28-preflight-policy.json`.
다른 작업의 미커밋 runner와 승격 Critic 테스트는 보존했고 검증본에는 포함되지 않았다.
실제 공급사 청구 출처 검증, 공개 명령/Broker·DB 전체 연결 및 운영 배포는 계속 미완료다.
자동 재개와 Muse Spark 기본값을 유지한다.

## 2026-10-28 원격 Runner 기준 고정

`codex/runner-base-binding` `446e940`은 Git ref를 불변 커밋으로 고정한 bundle을 사용하고
요청 SHA와 다른 checkout 또는 응답 base를 거부한다. 수정 전 4 failed·1 passed, 수정 후 집중 17개 및
실제 Runner 서비스 포함 37개·전체 API 642개(1 skipped)·실제 PostgreSQL 169개 통과·정본 0 failure.
원본 `.local/evidence/runner-base-binding-20261028-srrygk3d`; main의 미커밋 runner/승격 테스트는 보존했다.
공개 PR 경로의 SHA 전달은 기존 승격 T17 테스트가 유효하지 않은 가짜 SHA로 성공을 요구하여 별도 조정이 필요하다.

## 2026-10-28 Runner bundle 참조 보존

`codex/runner-bundle-ownership` `e8e3754`는 이름 충돌 시 기존 브랜치를 지우지 않고,
참조 이동 시 bundle을 거부하며 변경된 참조를 보존한다. 수정 전 3 failed, 수정 후 실제 Runner 서비스 포함
42 passed. 원본 `.local/evidence/runner-bundle-ownership-20261028-w4esi1fq`; 실제 PostgreSQL 169개·SQL 96개·
참조 112개 통과, 전체 API 검증 중·main 미반영.

## 2026-10-28 원격 Runner 수집 결과 보강

`codex/runner-count-binding` `f894b30`은 미전달 스위트 수집, 부족한 성공 수집, 부정확한 종료 코드 및
전달한 봉인 종류와 다른 결과를 거부한다. 수정 전 8 failed·2 passed, 수정 후 실제 Runner 서비스 포함 52 passed.
원본 `.local/evidence/runner-count-binding-20261028-svzs_kqd`; 전체 API/DB 검증 중, main 미반영.
스니펫 수 하한만으로 각 파일의 수집을 증명하지 않으며 로컬 경로도 별도 확인해야 한다.

## 2026-10-28 Runner 기준 및 bundle 보호 main 통합

`20a607e`까지 main에 반영했다. 검증본 `e8e3754`와 API·웹·정본 tree가 같고 전체 API
646 passed·1 skipped, 실제 PostgreSQL 169 passed·SQL 96·참조 112·계약 0 failure,
실제 Runner 서비스 포함 집중 42 passed다. 동일 웹 소스의 npm ci/tsc/build도 통과했다.
해시·원본: `docs/validation/2026-10-28-runner-base-bundle.json`. 기존 미커밋 runner와
Critic 테스트는 보존했고 검증본에 포함하지 않았다. 수집 수 검증은 별도 브랜치에서 진행 중이다.
공개 PR의 SHA 전달은 승격 T17 fixture 충돌로 미완료이며 우회하지 않았다. 실제 provider 청구,
공개 Broker/DB 연결·운영 배포도 미완료다. Muse Spark와 자동 재개를 유지한다.

## 2026-10-28 관리 화면 및 Runner 수집 검증 후속

`77d018c`에 관리 화면의 부분 동기화 실패와 오래된 데이터 경고, 중복 갱신 방지,
미션 선택 응답 경합 방지 및 자동 갱신 중지 처리를 반영했다. 검증본과 통합 웹 tree가 같으며
npm ci·TypeScript·프로덕션 빌드가 통과했다. 전체 통합 API/DB 검증은 별도로 필요하다.
Runner 수집 검증은 `2550dc1`에 반영됐고 검증본에서 API 656 passed·1 skipped,
실제 PostgreSQL 169 passed·Runner 서비스 포함 52 passed다. 원본 로그와 해시는
`docs/validation/2026-10-28-runner-collection.json`에 있다. 수집 수만으로 각 파일 실행이
증명되지는 않는다. 공개 PR의 기준 SHA 바인딩은 별도 브랜치에서 검증 중이다.

## 공개 PR 기준 SHA 격리 검증

`codex/pr-base-binding`의 `e3867bb`는 서버 Runner의 불변 기준 SHA를 PR 생성에 전달한다.
T17·T18의 가짜 기준 SHA를 실제 실행 기준에 맞게 교정한 격리 작업트리에서 전체 API
667 passed·1 skipped, 실제 PostgreSQL 169 passed, 정본 검사 및 웹 npm ci/tsc/build가 통과했다.
두 승격 테스트 fixture 교정은 소유권 때문에 미커밋이며 커밋 단독은 해당 fixture와 충돌한다.
소유자 반영과 최종 트리 재검증 전에는 main에 통합하지 않는다. 상세는 격리 작업트리의
`docs/PR_BASE_BINDING_CODEX.md`와 `.local/validation-pr-*-codex.log`에 있다.
