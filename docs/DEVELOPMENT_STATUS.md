# EvoForge 개발 진행 상태

갱신: 2026-10-27 (Asia/Seoul). **전체 개발 상태: 미완료.**

## 사용자의 개발 지시

- EvoForge의 메인 모델은 **Muse Spark**다.
- 현재 저장소의 모델 식별자 `muse-spark-1.3`을 Builder·Critic의 기본값으로 유지한다.
- 다른 모델로의 자동 대체는 하지 않는다. Critic의 독립성·명세 선행 검증은 유지한다.
- 작업이 완료되지 않았는데 개발 세션이 끝나면 자동으로 다시 깨어나 실제 구현과 검증을 이어간다.

## 확인된 완료 항목

- [x] Builder·Critic 코드, `.env.example`, GCP Cloud Run 설정의 Muse Spark 기본값 확인.
- [x] 생성 경로와 전체 무결성 게이트의 판정 통일, 누락·오류 테스트 증거 처리 보강.
- [x] 회귀 테스트 20개 추가. API 테스트 27개, 참조 테스트 112개 통과.
- [x] 현재 채팅의 자동 재개 활성화. 자동화 ID: `evoforge`, 확인 간격: 15분.
- [x] CI 검증 의존성·PostgreSQL 15 테스트 환경·웹 빌드 검사 구성. 새 가상환경의 참조 112개·API 93개·웹 프로덕션 빌드 통과. 컨테이너 실행은 미검증.
- [x] 후속 Windows 임시 PostgreSQL 15.19 실제 실행: SQL 96개·참조 112개·계약 C1–C9 전체 통과. 컨테이너/배포 실행은 미검증.
- [x] PostgreSQL 어댑터의 예약·영수증 정산·병합 승인과 실제 DB 수용 테스트 21개 통과. Generate/Review 요청의 DB 연결은 남아 있다.
- [x] SDK 자동 재시도 비활성화·Critic 호출별 예약·부분 실패 비용 보존·서버 메타데이터·Phase A 테스트 보존. API 116개와 관련 신규 23개 검증 통과.
- [x] 서비스 토큰·서버 소유 스코프의 내부 FastAPI DB 경로 연결. API 139개, 실제 PostgreSQL HTTP 포함 25개 통과.

## 이어서 수행할 작업

> **완료 (Claude, 2026-10-27, `eff542f` main 병합):** 아래 앞의 4개 항목 + 웹→API CORS 누락 수정.
> 근거: API 93 passed(Critic 수용 테스트 `tests/test_critic_t1~t4_*.py` 61개·CORS 5개 포함), 참조 112 passed,
> `validate_package.py` 0 failure(`--pg` 미실행), `next build` 성공, 패치 적용기 퍼징(difflib 3000건·git diff 150건) 불일치 0.
> 브라우저 E2E(로컬): Mission Control Generate → Lab Evaluate(실행 통계 입력) → INCONCLUSIVE 시 PR 버튼 비활성 확인.
> 미검증: 실제 Muse Spark 호출(키 없음), 실제 GitHub PR 생성(토큰 없음), Cloud Run 배포 환경의 CORS.
> Muse Spark Builder 루프: `tools/muse_improve.py` + `tools/muse_tasks/*.json` (`MODEL_API_KEY`를 `services/api/.env`에 두면 사용).

> **CI 구성 완료 (Codex, 2026-10-27, `560a5ef`):** API 변경과 분리해 검증 의존성, PostgreSQL 테스트 환경,
> 웹 빌드 검사, Docker 웹 컨텍스트와 빈 `public/` 경로를 보강했다.
> 검증 근거와 실제 SQL·컨테이너 실행의 남은 항목은 [CI_VALIDATION.md](CI_VALIDATION.md)에 기록했다.

> **SQL 검증 완료 (Codex, 2026-10-27, `71ed84f`):** `tools/validate_local_pg.py`로 Windows용 임시 PostgreSQL 15.19에서
> `validate_package.py --pg`를 실행했다. SQL 96개·참조 112개·C1–C9 전체 통과, 서버 종료와 클러스터 정리 확인.
> 재현 명령과 범위는 [LOCAL_POSTGRES_VALIDATION.md](LOCAL_POSTGRES_VALIDATION.md)에 기록했다.

> **DB 어댑터 검증 완료 (Codex, 2026-10-27):** `postgres_kernel.py`에서 정본 예약·정산·병합 승인 함수를 호출하고,
> 실제 PostgreSQL 수용 테스트 21개를 통과했다. 동시 요청·UNKNOWN·영수증 바인딩·RLS와 병합 승인 거부/허용을 확인했다.
> 상세·재현: [POSTGRES_KERNEL.md](POSTGRES_KERNEL.md). 기존 API 테스트도 93개 통과(DB 미지정 시 DB 테스트 모듈 1개 skip).

> **호출 경계 검증 완료 (Codex, 2026-10-27):** SDK의 자동 재시도를 끄고, 실제 Critic의 두 호출을 각각 예약한다.
> A 성공 뒤 B 실패에도 A 지출·응답 근거가 남고, B의 거부/UNKNOWN을 구분한다.
> Phase B의 테스트 덮어쓰기와 모델 JSON 메타데이터 위조도 막았다. [상세 검증](PROVIDER_CALL_ACCOUNTING.md).

> **내부 DB HTTP 검증 완료 (Codex, 2026-10-27):** `/v1/kernel`의 인증·입력·상태/오류 매핑과 실제 DB 연결을 검증했다.
> 스코프는 서버 소유이며 DB 오류 시 메모리로 대체하지 않는다. [설정·경로·검증](INTERNAL_KERNEL_API.md).
> Generate/Review의 패킷·영수증 연결과 브라우저 사용자 인증은 별도 미완료다.

> **우선권 (프로젝트 소유자 지정, 2026-10-27): Muse Spark 1 > Claude 2 > Codex 3.** 규칙은 [`AGENTS.md`](../AGENTS.md).

> **main 병합 완료 (Claude + Muse Spark, 2026-10-27, `f421bd2` fast-forward):** 우선권에 따라 먼저 병합했다.
> Codex의 미커밋 변경은 보존했다: `main.py`의 `kernel_router` 2줄은 3-way 병합으로 새 `main` 위에 다시 적용했고 나머지 파일은 건드리지 않았다.
> 병합 후 main 작업 트리(Codex WIP 포함) API 200 passed·1 skipped.
> 이전 기록 — 브랜치 `refs/heads/muse/round2` @ `f421bd2`, main `dd4c106` 병합 포함:
> Builder = Muse Spark 1.3(OpenCode `tools/muse_improve.py --via opencode`), Critic = Claude 봉인 테스트·리뷰.
> T6 영수증 대사(`ledger.reconcile`, `POST /v1/ledger/reconcile`, `GET /v1/ledger`) — Muse 1라운드 통과.
> T5 서버 Runner(`evoforge/runner.py`, `POST /v1/runs`, PR은 서버 실행 증거 필수, `/v1/eval/sandbox` 저장소 허용 목록) — Muse 3라운드 통과 후
> Critic 수정: `G2_REQUIRED`=필수 테스트 실제 실행·전부 통과(p.36), held-out 격리(conftest·pytest.ini·visible 테스트의 held-out 변조 3/3 위조 → 차단).
> 근거: API 177 passed·1 skipped(실 DB 없음), 참조 112, validate 0 failure, tsc·next build, 브라우저 E2E(실 샌드박스 실행 → PR 차단).
> 잔여 위험(마이크로VM 전까지): held-out 테스트가 import하는 후보 모듈은 같은 프로세스에서 실행, 백그라운드 프로세스 미종료, 네트워크·메타데이터 서버 접근 가능 → 비밀이 있는 호스트에서는 `EVO_REPO_ROOTS` 미설정 유지.

- [x] 모델 호출 실패 후 비용 예약을 접수 전 실패(환불)·결과 불명(`UNKNOWN` 보류)으로 처리. 영수증 대사로 UNKNOWN을 settle/refund하는 잡은 미구현.
- [x] 실행 성공 수·전체 수의 입력 관계 검증(422)과 0건 실행의 증거 부족(INCONCLUSIVE) 처리.
- [x] 기준 브랜치 파일에 unified diff를 엄격 적용해 문맥을 보존하는 PR 생성 경로 구현·검증(mock transport).
- [x] PR은 서버가 저장한 게이트 평가(`evidence_id`)가 전부 PASS일 때만 생성. 웹 Lab도 Evaluate → PR 순서로 변경.
- [x] 실제 Runner와 봉인 테스트 결과 연결 (로컬 subprocess Runner, `f421bd2` main 병합; microVM 아님).
- [x] PostgreSQL SQL 계약의 비용 예약·원장·RLS·병합 승인 등 96개 검사 실제 실행.
- [x] 정본 함수·micro-USD 단위의 PostgreSQL 어댑터와 int cents 변환 구현. 잘못된 `project_budgets` 스텁 제거.
- [x] 내부 FastAPI 요청에서 PostgreSQL 예약·정산·병합 승인 호출과 인증/스코프·연결 오류의 차단 검증.
- [ ] FastAPI에서 인증된 프로젝트 컨텍스트·컨텍스트 패킷·영수증 저장을 새 PostgreSQL 어댑터에 연결. 현재 요청 경로는 메모리 원장을 사용한다.
- [ ] 브라우저 사용자 로그인·프로젝트 멤버십과 워크플로 호출 권한 연결. 내부 서비스 토큰을 브라우저로 전달하지 않는다.
- [ ] 개발 Muse Builder CLI의 프로젝트 비용 예약·정식 영수증 연결. 현재 CLI를 플랫폼 예산 통제가 완료된 경로로 사용하지 않는다.
- [ ] Muse Spark 실제 호출과 저장소 연결을 포함한 통합 경로 검증.
- [ ] 배포·통합 검증 결과와 남은 요구사항을 대조하고 완료 근거 기록.

## 외부 연결 확인 범위

현재 Codex의 로컬 프로세스에서는 `MODEL_API_KEY`, `DATABASE_URL`, `GITHUB_TOKEN`이
설정되지 않은 것을 확인했다. 저장소 루트와 API 폴더에도 `.env`가 없었다.
다른 세션이나 Secret Manager의 설정 여부는 이 확인만으로 판단하지 않는다.
실제 연동을 완료하려면 해당 실행 환경의 자격 증명과 접근 권한을 확인해야 한다.
비밀 값은 문서·채팅·로그에 기록하지 않는다.

## 자동 재개의 완료 판단

자동화는 현재 채팅과 `C:\evo_forge`에서 미완료 개발을 이어간다.
기존 변경을 먼저 확인하고, 수정·검증 결과와 남은 작업을 이 문서에 갱신한다.
stub 또는 정적 게이트·단위 테스트 통과만으로 실서비스 통합 완료를 선언하지 않는다.
상태가 그대로면 반복 알림을 보내지 않으며, 중요한 진척·완료·실패 또는 사용자 조치가 필요할 때 알린다.
요구사항이 모두 충족되고 검증 근거가 기록되면 자동화를 비활성화한다.
로컬 파일 작업이므로 PC와 Codex 앱이 실행 중이어야 한다.

## 현재 작업 클레임

- **Codex 지원 / `codex/receipt-support` / `C:\evo_forge_codex`:** Muse round3의 T7(main/evidence)·T8(critic)·T9(web)와 분리해,
  PostgreSQL의 정식 영수증 JSON 계약 검증·저장·스코프/예약 바인딩과 실제 DB 검증을 맡는다.
  파일: `evoforge/postgres_receipts.py`, `postgres_kernel.py`, `services/api/migrations/`,
  `services/api/requirements.txt`, Codex 소유 `test_postgres_kernel.py`·`test_receipt_contract.py`, 관련 문서·CI 검증 연결.
  T8 수용을 위해 Codex 소유 `test_provider_accounting.py`의 양성 suite fixture를 3종 계약에 맞추되 비용·실패 검증은 유지한다.
  내부 영수증 수신·조회·저장 금액 정산을 위해 Codex 소유 `kernel_api.py`·`test_kernel_api.py`도 지원 범위에 포함한다.
  상위 우선권 브랜치가 먼저 main에 반영된 뒤 동기화·통합한다. 상위 클레임과 겹치면 해당 파일 편집을 중단한다.
  T8 양성 provider fixture 지원 커밋: `92cc047` (`codex/receipt-support`), 기존 비용·실패 검증 유지.
  round3의 봉인 suite 강화와 함께 채택할 수 있다. 영수증 기능은 별도 검증 진행 중이다.
