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
- [x] 정본 v1 영수증 검증·원자적 보존·저장 금액 정산 내부 경로. round3 동기화 후 API 291개, 실제 DB 46개 통과.
- [x] Next 15.5.28·PostCSS 8.5.32로 웹 의존성 수정. npm audit 0건, 프로덕션 빌드와 standalone HTTP 검사 통과.
- [x] Builder 전용 패킷·공급사 동의·agent/task fencing과 비용 예약 원자적 연결을 main에 반영·검증. 실제 전송기 연결은 남아 있다.

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

> **실 Meta 키 통합 검증 (Claude, 2026-10-27, main `12b9c47`):** 소유자 키를 gitignore된 `services/api/.env`에 두고
> `uvicorn main:app --env-file .env`로 실행(테스트는 키를 쓰지 않음). 실호출 결과: Builder(muse-spark-1.3) diff+강한 테스트 3개 →
> Critic 봉인 스위트 3종·리뷰 PASS → 실 샌드박스 visible 3/3·held-out 3/3 → GH_INTEGRITY/GC_COMPOSITION/G2_REQUIRED 전부 PASS →
> `/v1/pr/create`는 `GITHUB_TOKEN/GITHUB_REPO` 없음으로만 400. 원장 실지출 240¢, UNKNOWN 0.
> 실호출로 발견·수정(T13, Builder Muse Spark): 추론 모델이 `max_tokens=1500`을 추론에 다 써 빈 응답 → 봉인 없음으로 오인되던 버그.
> 남은 항목(다음 라운드 후보): 실제 GitHub PR(토큰·대상 저장소 필요), Builder에 저장소 파일 문맥 제공(현재 목표 문장만 전달),
> run 증거 체인에 Review 단계 연결, layout 하단 "추정치" 문구.

> **Round 3·4 main 병합 완료 (Muse Spark 계획·구현, Claude Critic, 2026-10-27, `9887efe`):**
> R3: T7 증거 체인, T8 봉인 스위트 형식(≥3, compositional·negative·boundary), T9 Mission Control 실제 원장.
> R4(Critic 지적 F1–F3 반영, 계획은 Muse): T10 `/v1/runs`는 서버 저장 Critic 리뷰(`review_evidence_id`)의 봉인 스위트만 실행 —
> 클라이언트 `heldout_tests` 422, stub·비리뷰·형식 위반 409(클라이언트 3×`assert 1==1`로 PR 열던 우회 차단);
> T11 `GET /v1/events/{id}` 단계 요약 + Evidence 페이지 드릴다운; T12 모든 HTTP 응답에서 봉인 코드 제거({kind, code_sha256, code_len}), 원본은 서버 저장소만.
> Codex 테스트 조정(Critic, 단언 유지): provider-accounting 봉인 픽스처 3종화, HTTP 응답 형태만 마스킹 형태로.
> 근거: API 310 passed·1 skipped, validate 0 failure, tsc·next build, 브라우저(드릴다운, Lab 마스킹, stub 리뷰 409).
> 남은 메모(Muse 다음 라운드 후보): layout 하단 "추정치" 문구가 T9 이후 사실과 다름; 키 없는 오프라인 모드는 stub 리뷰라 Run 불가(의도된 동작).

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
- [ ] FastAPI의 canonical 명령·비용 예약·패킷·영수증을 요청 경로 전체에 연결. 증거는 PostgreSQL 선택 모드, 명령·공개 원장은 아직 메모리다.
- [x] 소유자 로그인·web BFF·Google ID 토큰의 워크플로 권한 경계(R6). 다중 사용자·프로젝트 멤버십은 별도 범위다.
- [ ] 개발 Muse Builder CLI의 프로젝트 비용 예약·정식 영수증 연결. 현재 CLI를 플랫폼 예산 통제가 완료된 경로로 사용하지 않는다.
- [ ] Broker 전송 전에 packet/call 사전 바인딩·유효 상태·공급사 허용 목록·가격표를 확인하고 실제 Runner 증거를 core 후보·게이트와 영속 연결.
- [ ] 정본을 우회하지 않는 0원 정산과 추정 영수증→실청구 정정·대사 정책 구현. 현재 0원은 문서만 보존하고 예약 정산은 거부한다.
- [x] Muse Spark 실제 호출·원격 저장소·분리 Runner·GitHub PR의 GCP 통합 검증(R6, SERVICE_STATUS 참조). canonical 비용 DB 통합은 별도다.
- [ ] 배포·통합 검증 결과와 남은 요구사항을 대조하고 완료 근거 기록.

## 외부 연결 확인 범위

초기 Codex 로컬 프로세스 점검에서는 자격 증명 환경변수와 API `.env`가 없었다.
이후 소유자 설정을 사용한 실 Meta·GitHub·GCP 검증은 상단과 `SERVICE_STATUS.md`에 기록되었다.
별도 Codex 프로세스와 운영 런타임의 설정이 같다고 가정하지 않는다.
PostgreSQL 증거 저장의 운영 적용에는 확장 003과 사전 생성한 프로젝트·서버 스코프 설정이 필요하다.
비밀 값은 문서·채팅·로그에 기록하지 않는다.

## 자동 재개의 완료 판단

자동화는 현재 채팅과 `C:\evo_forge`에서 미완료 개발을 이어간다.
기존 변경을 먼저 확인하고, 수정·검증 결과와 남은 작업을 이 문서에 갱신한다.
stub 또는 정적 게이트·단위 테스트 통과만으로 실서비스 통합 완료를 선언하지 않는다.
상태가 그대로면 반복 알림을 보내지 않으며, 중요한 진척·완료·실패 또는 사용자 조치가 필요할 때 알린다.
요구사항이 모두 충족되고 검증 근거가 기록되면 자동화를 비활성화한다.
로컬 파일 작업이므로 PC와 Codex 앱이 실행 중이어야 한다.

## 현재 작업 클레임

- **Codex (증거 단계 완료·클레임 해제) / `codex/evidence-persistence` / `C:\evo_forge_codex`:** P0-2 중 서버 증거·비공개 봉인 리뷰·이벤트/체인의 PostgreSQL 영속화를 실제 요청 경로에 연결한다.
  `postgres_state.py`, `evidence.py`, main의 저장소 선택/오류 경계·예약 전 가용성 확인, 확장 003, Codex DB 테스트와 관련 문서·환경 예제를 수정한다.
  상위 Muse round6의 인증·원격 checkout·Runner·Builder/PR 구현은 보존한다. 명령·비용 원장의 PG 요청 연결은 별도 잔여 항목이다.
- **Codex 지원 (완료·클레임 해제) / `codex/builder-preflight` / `C:\evo_forge_codex`:** Builder 호출의 기존 패킷·공급사 동의·agent/task lease 검증과 비용 예약의 원자적 바인딩을 맡는다.
  `evoforge/postgres_builder.py`·`postgres_kernel.py`·`kernel_api.py`, 확장 마이그레이션 002, Codex 소유 DB/API 테스트와 관련 문서·환경 예제를 수정한다.
  전송 직전 재검증과 영수증 packet/model/가격표 버전 일치를 확인한다. 가격 계산·실제 모델 실행 완료를 주장하지 않는다.
  Muse round4 T10–T12의 main/critic/runner/gates/evidence/web와 봉인 수용 테스트는 편집하지 않는다. 상위 작업이 먼저 main에 반영된 뒤 동기화한다.
- **Codex 추가 지원 (완료·클레임 해제) / `codex/receipt-support`:** npm 설치에서 확인한 Next.js 중대 취약점 수정.
  `apps/web/package.json`·`package-lock.json`만 수정해 Next 15 계열 보안 릴리스와 필요 전이 의존성을 고정하고 빌드·audit를 검증한다.
  Muse의 T9 화면 코드는 보존한다.
- **Codex 지원 (완료·클레임 해제) / `codex/receipt-support` / `C:\evo_forge_codex`:** Muse round3의 T7(main/evidence)·T8(critic)·T9(web)와 분리해,
  PostgreSQL의 정식 영수증 JSON 계약 검증·저장·스코프/예약 바인딩과 실제 DB 검증을 맡는다.
  파일: `evoforge/postgres_receipts.py`, `postgres_kernel.py`, `services/api/migrations/`,
  `services/api/requirements.txt`, Codex 소유 `test_postgres_kernel.py`·`test_receipt_contract.py`, 관련 문서·CI 검증 연결.
  T8 수용을 위해 Codex 소유 `test_provider_accounting.py`의 양성 suite fixture를 3종 계약에 맞추되 비용·실패 검증은 유지한다.
  내부 영수증 수신·조회·저장 금액 정산을 위해 Codex 소유 `kernel_api.py`·`test_kernel_api.py`도 지원 범위에 포함한다.
  상위 우선권 브랜치가 먼저 main에 반영된 뒤 동기화·통합한다. 상위 클레임과 겹치면 해당 파일 편집을 중단한다.
  T8 양성 provider fixture 지원 커밋: `92cc047` (`codex/receipt-support`), 기존 비용·실패 검증 유지.
  round3가 main에 먼저 반영되어 `89dbc71`에서 동기화했고, 상위 provider fixture를 채택했다.

## Codex 영수증 지원 검증 (main 반영 완료)

`codex/receipt-support`에서 정본 v1 영수증 문서 검증·원자적 보존·서버 스코프/예약/패킷 확인과
저장 금액 정산의 내부 HTTP 경로를 구현했다. 동시 정산 응답의 이전 intent 혼합과 RFC3339 검사 누락도 수정했다.
동기화 전 API **269 passed·1 skipped**, 동기화 후 **291 passed·1 skipped**.
실제 PostgreSQL **46 passed**, 참조 **112개**·SQL **96개**·기본/실제 PG 계약 검사 전체 통과.
확장 마이그레이션과 정확한 미완료 경계는 [RECEIPT_PERSISTENCE.md](RECEIPT_PERSISTENCE.md)에 기록했다.
상위 구현과 봉인 테스트·정본은 변경하지 않았다. `228c272`로 main에 fast-forward 반영했다.
Generate/Review·개발 CLI·인증된 프로젝트·공급사 청구 증거·실배포 완료를 뜻하지 않는다.

웹 의존성 수정과 검증 근거는 [WEB_DEPENDENCY_SECURITY.md](WEB_DEPENDENCY_SECURITY.md)에 기록했다.
Next가 자동 생성한 `next-env.d.ts`의 route 참조도 보존했다. T9 화면 코드는 변경하지 않았다.

`C:\evo_forge` main 작업 폴더에서도 API **291 passed·1 skipped**, 실제 DB **46 passed**,
참조 **112개**·SQL **96개**·C1–C9, npm ci·audit **0건**·프로덕션 빌드를 다시 확인했다.
standalone 서버의 `/`, `/lab`, `/evidence`와 정적 JS HTTP 응답 및 검사 서버 종료도 확인했다.
검증 원본은 `C:\evo_forge\.local\evidence\receipts-20261027-f42duc14`에 별도 보존했다.
각 로그 SHA-256과 검증 revision을 기록한 manifest는 `docs/validation/2026-10-27-receipts.json`에도 저장했다.
수신·조회·저장 금액 정산 기능은 `55bb411`, 웹 의존성 수정은 `83fe38a`다.

현재 Codex 프로세스의 `MODEL_API_KEY`, `DATABASE_URL`, `GITHUB_TOKEN`, `EVO_KERNEL_TOKEN`은 모두 미설정이다.
실제 연동 시 해당 실행 환경에 Muse 접근 키, 프로젝트/예산이 준비된 DB와 내부 스코프·서비스 토큰,
대상 저장소 PR 권한을 비밀 저장소로 주입해야 한다. 다른 세션·OpenCode·클라우드의 설정 여부는 이 확인으로 판단하지 않는다.
새 비밀 값을 채팅에 붙여 넣을 필요는 없다. 독립 개발과 자동 재개는 계속한다.

## Builder 호출 전 검사 지원 (main 반영 완료)

`codex/builder-preflight`의 `094b4aa`는 기존 Gateway 패킷·run/task·agent·공급사 동의를 검증하고
정본 비용 예약·intent·불변 Builder 바인딩을 함께 기록한다. 전송 직전에 상태와 fencing을 다시 검사하며,
해당 packet/model/가격표 버전의 정본 영수증만 정산한다. 호환 ctx 행만 만든 정산으로 우회하지 못한다.
가격표 식별자는 서버 환경 `EVO_PRICE_TABLE_VERSION`에서 가져오고 요청 본문으로 바꾸지 못한다.
관련 확장 002와 정확한 미완료 경계는 [BUILDER_PREFLIGHT.md](BUILDER_PREFLIGHT.md)에 기록했다.

상위 Muse round4를 먼저 보존해 `0851454`에서 동기화한 뒤 API **317 passed·1 skipped**,
실제 PostgreSQL **77 passed**, 참조 **112개**·SQL **96개**·계약 검사와 웹 프로덕션 빌드를 통과했다.
원본 로그·해시는 `docs/validation/2026-10-27-builder-preflight.json`이 가리키는 main의 `.local/evidence` 폴더에 보존했다.
`0551fbe`로 main에 fast-forward 반영했다. main 작업 폴더에서도 API 모듈 컴파일·health/OpenAPI,
정본 패키지 검사와 웹 프로덕션 빌드가 통과했다. 상위 main/critic/runner/gates/evidence/web·봉인 테스트·정본은 그대로 보존했다.
이는 Builder 호출 준비·전송 전 상태 검사다. SDK 전송기·실제 요율/청구·사용자 인증·Runner/core 증거 연결·배포는 남아 있다.

## 요청 경로 증거 영속화 (main 반영 완료)

`69add6e`는 `EVO_STATE_BACKEND=postgres`에서 실제 요청 증거·비공개 Critic 원본·단계 이벤트와 체인을
PostgreSQL로 연결한다. 별도 API 프로세스에서도 기존 리뷰와 실제 Runner 결과를 복원하고,
공개 HTTP에는 봉인 코드가 나오지 않는 것을 확인했다. 범위·확장 003·설정은 [EVIDENCE_PERSISTENCE.md](EVIDENCE_PERSISTENCE.md).

API **403 passed·1 skipped**, 실제 PostgreSQL **81 passed**, 참조 **112개**·SQL **96개**·계약 검사와
Next 15.5.28 프로덕션 빌드가 통과했다. DB 오류 시 메모리로 우회하거나 공급사를 호출하지 않고 503으로 거부하며,
처음부터 저장소가 불가하면 명령의 멱등 키도 소비하지 않는다.
명령·공개 비용 원장은 아직 메모리이므로 P0-2 전체 완료나 운영 Cloud SQL 적용 완료를 뜻하지 않는다.
`1554547`로 main에 fast-forward 반영했으며, 상위 round6 구현·인프라·비용 리포터를 보존했다.
main의 API 모듈 컴파일·health/OpenAPI도 통과했다. 검증 원본은
`C:\evo_forge\.local\evidence\api-evidence-20261027-f29wjim1`에 별도 보존했고
`docs/validation/2026-10-27-api-evidence.json`에 각 로그 SHA-256을 기록했다.
