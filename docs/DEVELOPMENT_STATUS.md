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
- [x] Context Mesh(L1–L5 로그 게이트·Vault·Folder 복원·Packet v2 컴파일러·캐시 네임스페이스 솔트·온라인 결정 규칙), 400KB 대형 Diff 분할·Review Coverage 원장·리뷰어 자격 시험 풀, 공급망/BSL-1.1/SBOM 스캐너·테넌트 공정 큐·플랫폼 키 KMS 격리 가드(`ebfeb95`) main 반영·검증. API 465개·참조 112개·신규 CR 15개 통과.

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

- **Codex (영수증 저장 후 예약 해제 경합 보강) / `codex/pg-integration` / `C:\evo_forge_codex`:**
  Codex 소유 `postgres_kernel.py`·`test_postgres_kernel.py`와 관련 문서/검증 manifest를 수정한다.
  정산 전 영수증이 이미 저장된 호출을 미접수로 예약 해제하는 경로를 실제 DB에서 재현하고 차단한다.
  정본 reserve/settle·RLS·모델 기본값과 상위 T22의 main/평가/UI·봉인 테스트는 변경하지 않는다.
- **Codex (병합 정책/자격·상위 동기화 검증 완료·T22 상위 병합 대기) / `codex/pg-integration` / `C:\evo_forge_codex`:** Codex 소유 postgres_kernel.py와
  test_postgres_kernel.py·관련 문서에서 현재 policy와 HIGH/CRITICAL 자격을 대조한다(`1441518`).
  상위 main `2cb3627`까지 합친 `41949da`에서 API 485개·실제 DB 147개·SQL 96개·참조 112개·계약·웹 빌드 통과.
  관련 문서·검증 manifest의 근거를 정리했으며 지원 코드는 main 미반영이다.
  정본 core.authorize_merge는 그대로 호출하고 추가 거부 조건만 보강한다. main/상위 T22·Agy 자격 시험 모듈·봉인 테스트는 수정하지 않는다.
- **Antigravity (완료·클레임 해제·main 반영 `ebfeb95`) / `agy/cr-closure`:**
  상위 Muse T22(`muse/round8`) 및 Codex(`codex/pg-integration`) 파일과 전혀 겹치지 않는 독립 모듈로 수용 매트릭스(`Acceptance_Test_Matrix.md`)와
  `SERVICE_STATUS.md` P1의 미구현 항목을 구현·검증하고 main에 fast-forward 반영했다.
  반영 파일: `services/api/evoforge/context_mesh.py`, `services/api/evoforge/review_qualification.py`, `services/api/evoforge/runtime_guards.py`,
  `services/api/tests/test_context_mesh_cr.py`, `services/api/tests/test_review_qualification_cr.py`, `services/api/tests/test_runtime_guards_cr.py`,
  `docs/CR_CLOSURE_ADVANCEMENT.md`. `main.py`·웹·DB 마이그레이션·정본(`docs/evoforge-v4.2/`)은 수정하지 않았다.
- **Codex (프로젝트 cap 경합 검증 완료·T22 상위 병합 대기) / `codex/pg-integration` / `C:\evo_forge_codex`:** 확장 007·Codex DB 테스트·관련 문서에서
  정본 함수의 한도 검사 뒤 기존 호출이 정산되는 경합을 재현하고 `c479487`에서 저장 시점의 cap을 재검사한다.
  API 465개·실제 DB 145개·SQL 96개·참조 112개·계약·웹 빌드 통과. 지원 코드는 main 미반영이다.
  상위 T22 프로세스는 실행 중이므로 main/평가/UI·봉인 테스트를 편집하지 않는다. 정본 SQL 파일과 정산/승인 함수는 유지한다.
- **Codex (후보 등록 검증 완료·T22 상위 병합 대기) / `codex/pg-integration` / `C:\evo_forge_codex`:** 새 `postgres_candidates.py`·확장 008·
  Codex 소유 kernel_api.py/test_kernel_api.py/test_postgres_kernel.py·관련 문서를 수정한다.
  저장된 Builder 출력과 정산된 call/receipt/request ID를 대조하고, 기준 SHA에 적용한 diff/visible 테스트가 실제 head의 Git tree와
  일치할 때만 PROPOSED 후보를 원자적으로 만든다. Runner 연결 모듈도 등록 후 head drift를 거부하도록 보강한다.
  main/상위 평가/UI/봉인 테스트·정본은 변경하지 않는다. 나머지 게이트·리뷰·병합 승인은 생성하지 않는다.
  구현 `e947cbf`: API 465개·실제 DB 144개(신규 5개)·SQL 96개·참조 112개·계약·웹 빌드 통과. 지원 코드는 main 미반영이다.
- **Codex (테넌트 비용 예약 가드 검증 완료·T22 병합 대기) / `codex/pg-integration` / `C:\evo_forge_codex`:** 프로젝트 RLS가 다른 프로젝트의 open 예약을 숨겨
  선불 20,000,000µUSD에서 24,000,000µUSD를 허용하던 실패를 재현하고 `5b5b253`의 확장 007로 차단했다.
  정본 reserve/settle 함수와 RLS 정책은 보존하고 모델/main/T22 파일은 변경하지 않는다.
  새 SQL 확장·postgres_kernel.py의 가드 준비 검사·Codex 테스트·환경 예제/관련 문서만 변경했다.
  API 463개·실제 DB 139개(신규 8개)·SQL 96개·참조 112개·계약·웹 빌드 통과. 지원 코드는 main 미반영이다.
- **Codex (mission 호출 증거 복구 검증 완료·공유 core 연결 대기) / `codex/pg-integration` / `C:\evo_forge_codex`:** T22의 main/평가/UI 편집과 분리해
  `postgres_missions.py`, `missions.py`의 선택 backend, 확장 006, Codex 테스트·관련 문서를 수정한다.
  `50ffc5b`에서 API가 이미 사용하는 mission facade의 상태/단계 증거 복원·RLS·봉인 코드 비노출을 구현했다.
  API 463개·실제 DB 118개·SQL 96개·참조 112개·웹 빌드 통과. 지원 코드는 아직 main 미반영이다.
  후속 `4bbbf6d`: `postgres_missions.py`·확장 006에서 리뷰 복구 시 provider_evidence_ids도 같은 버전에 복원한다.
  누락·중복·다른 mission/scope·잘못된 호출 자료를 차단하고 API 463개·실제 DB 131개·계약·웹 빌드를 통과했다.
  공개 main/공급사 전송기와 T22 파일은 수정하지 않았다. 아래 최신 복구 검증 기록을 따른다.
  main.py·상위 봉인 테스트는 편집하지 않는다. 모델 호출 전 claim·비용/명령의 공유 core 연결은 T22 병합 뒤 이어간다.
- **Codex (내부 통합 검증 완료·공개 연결 대기) / `codex/pg-integration` / `C:\evo_forge_codex`:** 두 준비된 지원 브랜치를 별도 통합 브랜치에서 합쳤다.
  명령 완료 응답과 같은 scope의 서버 생성 증거를 원자적으로 연결하도록 `postgres_commands.py`·확장 004·Codex 테스트·문서를 보강한다.
  `kernel_api.py`의 서비스 인증 명령 접수/dispatch/완료/조회 경로와 Codex HTTP 테스트도 연결한다. 브라우저에는 내부 자격 증명을 제공하지 않는다.
  상위 round7은 `d347b56`으로 먼저 main에 반영되어 통합 브랜치에서 보존·동기화했다.
  후속 Muse T22(`muse/round8`)가 main을 편집 중이므로 공개 `commands.py` backend 위임·공유 `_generate_core`/mission 접점은 그 병합 뒤 이어간다.
  현재 main 파일은 편집하지 않으며 봉인 테스트도 편집하지 않는다.
  완료 증거/지연 제약·내부 Worker 경로는 `83798f9`, Google/커널 인증 병행과 round7 호환 검증은 `b29c3a9`, manifest는 `9ce7093`이다.
  이후 두 원 브랜치를 따로 합치지 말고 이 통합 브랜치를 기준으로 이어간다. 아래 최신 검증 기록을 따른다.
- **Codex (지원 검증 완료·상위 병합 대기) / `codex/runner-core-evidence` / `C:\evo_forge_codex`:** 상위 API 진입점 편집과 분리해 실제 Runner의 입력/빌드 식별자와 저장된 실행 증거를 기존 core 후보·G2_REQUIRED에 연결한다.
  `postgres_run_evidence.py`, `runner_attestation.py`, Runner/Runner client의 선택적 메타데이터, `kernel_api.py`, 확장 005,
  Codex 소유 테스트·문서/환경 예제만 수정한다. 구체적 head를 빈 diff로 다시 실행한 증거와 정산된 Builder 바인딩을 요구한다.
  없는 게이트·리뷰·승인은 생성하지 않고 `core.authorize_merge`를 유지한다. 공개 main·mission과 상위 봉인 테스트는 편집하지 않는다.
  구현 `3526ae0`, 내부 인증 테스트 `21707ed`, 검증 manifest `75ca7f8`을 준비했다. main 반영은 상위 round7 이후다.
- **Codex (지원 준비·공개 연결 대기) / `codex/commands-persistence`:** P0-2 명령의 canonical PostgreSQL 접수·상태·히스토리·완료 응답 영속화를 맡는다.
  우선 `postgres_commands.py`·확장 004·Codex DB 테스트·문서/환경 예제만 수정한다.
  상위 round7의 `commands.py`/main 변경이 main에 먼저 반영된 뒤 호환 연결·재검증한다. 비용 원장 변경은 이번 단계와 별도다.
  별도 저장 계층은 `9bfe0bc`로 검증·커밋했으며 공개 경로 연결과 main 병합은 아직 대기 중이다. 아래 검증 기록을 따른다.
  두 지원 브랜치는 `codex/pg-integration`에 통합했다. 검증 폴더 `C:\evo_forge_codex`의 현재 체크아웃도 통합 브랜치이며 원 브랜치/커밋을 보존했다.
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

## Canonical 명령 저장 지원 (상위 작업 병합 대기)

`codex/commands-persistence`의 `9bfe0bc`는 정본 `core.accept_command`와 상태 전이 제약으로 접수하고,
확장 004에 이력·완료 응답을 원자적·불변으로 보존한다. 동시 요청은 한 명령과 한 dispatch만 허용하며,
실행 중 종료된 명령을 새 API 프로세스에서 다시 dispatch하지 않는다.
완료 응답 저장 실패는 상태·이력과 함께 롤백하고, 조회는 서로 다른 시점의 상태를 섞지 않는다.
일반 advance로 완료를 위조할 수 없으며 DB도 APPLIED인 명령과 일치하는 응답만 허용한다.

API **403 passed·1 skipped**, 실제 PostgreSQL **91 passed**, 참조 **112개**·SQL **96개**·패키지 검사와 웹 빌드 통과.
원본 로그 6개와 SHA-256은 `C:\evo_forge\.local\evidence\api-commands-20261027-9e7itreq`에 보존했다.
설정·다음 연결은 해당 지원 브랜치의 `docs/COMMAND_PERSISTENCE.md`, manifest는
`docs/validation/2026-10-27-api-commands.json`(`b94a16a`)에 있다.

Muse round7은 main/mission 인터페이스를 수정 중이므로 상위 브랜치가 main에 먼저 반영될 때까지 해당 파일은 편집하지 않았다.
현재 main의 공개 명령·원장은 계속 메모리다. 공개 Generate의 dispatch/완료 hook·HTTP 재시도 검증,
운영 DB 확장 적용과 canonical 비용·mission 저장은 남아 있으며 전체 개발·P0-2 완료를 선언하지 않는다.
이번 검증은 공급사를 호출하지 않았고 기본 모델 `muse-spark-1.3`은 그대로 유지했다.

## Runner 증거 → core 후보/G2 지원 (상위 작업 병합 대기)

`codex/runner-core-evidence`의 `3526ae0`는 내부 `/v1/kernel/candidate-runs`에서
기존 canonical 후보·정산된 Builder 바인딩·서버에 보존된 실제 Runner 결과를 대조하고 G2_REQUIRED를 저장한다.
커밋된 head를 빈 diff로 다시 실행한 증거만 허용하고, 입력/결과 해시·서버 봉인 원본·현재 fencing과 모델/동의를 확인한다.
API/Runner에 구성하는 image digest는 운영자가 승인한 배포 식별자이며 독립 측정·서명이 아니다.
원격 클라이언트는 불가능한 실행 수·잘못된 해시/image·hygiene 실패를 502로 거부한다.

실제 로컬/번들 Runner → API client → PostgreSQL 연결, 다른 scope의 404, append-only/RLS,
동시 재전송과 실패 저장의 원자성, 이후 FAIL을 과거 PASS 재전송이 덮지 않는 것을 확인했다.
다른 필수 게이트·리뷰·승인은 만들지 않으며 후보 상태도 바꾸지 않는다. `core.authorize_merge`의 거부도 확인했다.
내부 읽기/쓰기 경로 모두 서비스 자격 증명 없이 DB를 만들지 않는 회귀 테스트는 `21707ed`다.

API **414 passed·1 skipped**, 실제 PostgreSQL **91 passed**, 참조 **112개**·SQL **96개**·패키지 검사와 웹 빌드 통과.
Dockerfile의 두 Python 파일만 별도 `python -I` 프로세스에서 실행해 API 패키지 없이 Runner가 동작하는 것도 확인했다.
Docker 실행 파일이 없어 컨테이너 빌드는 수행하지 않았다. Critic·영수증·등록 image는 합성 fixture이며 실제 공급사 청구 검증이 아니다.
원본 로그 6개는 `C:\evo_forge\.local\evidence\runner-core-20261027-m9gl2ykz`에 보존했다.
해당 지원 브랜치의 `docs/RUNNER_CORE_EVIDENCE.md`, `docs/validation/2026-10-27-runner-core-evidence.json`(`75ca7f8`)을 따른다.

상위 round7이 main/mission/평가 경로를 편집 중이므로 main 병합은 아직 하지 않았다.
공개 요청의 canonical 후보 생성·나머지 검증/독립 리뷰·비용/승인 연결, 운영 확장 005와 실제 Runner digest 설정·배포 검증은 남아 있다.
전체 개발과 P0-2는 미완료이며 현재 채팅의 자동 재개를 유지한다.

## PostgreSQL 지원 통합 검증 (round7 동기화·공개 연결 대기)

`codex/pg-integration`은 두 지원 브랜치의 테스트·환경 설정을 모두 보존해 합쳤다(`edffa84`).
상위 round7이 `d347b56`으로 먼저 main에 반영된 뒤 `911c41d`에서 동기화했고, Muse 코드와 봉인 수용 테스트를 그대로 유지했다.
통합 지원 코드는 아직 main에 병합하지 않았다.

`83798f9`는 서비스 인증 내부 명령 접수·단일 dispatch·완료·조회와 서버 증거 FK를 연결한다.
응답의 command_id·candidate·gates가 같은 프로젝트의 저장 증거와 일치해야 하며,
API BUILD 상태만 APPLIED로 커밋하는 SQL도 지연 제약으로 거부한다.
core_app 세션 역할·RLS에서 완료 커밋이 동작하고, 증거 테이블에 UPDATE 권한을 추가하지 않았음을 확인했다.
20회 재전송·동시 실행권·복구 후 완료 재저장·새 API 프로세스 조회·다른 scope/위조된 증거 거부도 검증했다.

`b29c3a9`는 Google ID 토큰과 내부 토큰의 Authorization 충돌을 해결한다.
운영 Google 인증을 유지한 채 `X-Evoforge-Kernel-Token`을 별도로 검사하며, 명시한 잘못된 헤더는 다른 자격 증명으로 대체하지 않는다.
Google audience·허용 서비스 계정·IAM·BFF 정책은 변경하지 않았다. 서명 검증기는 fixture로 대체한 테스트다.

API **463 passed·1 skipped**, 실제 PostgreSQL **107 passed**, 인증 경계 **35 passed**(전체 API 집계에 포함),
참조 **112개**·SQL **96개**·패키지 검사와 round7 웹 빌드 통과.
원본 로그 7개는 `C:\evo_forge\.local\evidence\pg-integration-20261027-wm8m7mca`에 보존했다.
각 로그·source SHA-256은 통합 브랜치의 `docs/validation/2026-10-27-pg-integration.json`(`9ce7093`),
범위와 다음 작업은 `docs/PG_INTEGRATION.md`에 기록했다.

후속 Muse T22(`muse/round8`)가 main을 편집 중이어서 공개 facade·공유 생성/mission 접점 변경은 그 병합 뒤 이어간다.
현재 통합 브랜치의 main.py·commands.py는 round7 main과 코드 차이가 없으며 공개 명령·비용·mission 영속화는 계속 미완료다.
Critic·영수증·등록 image는 합성 fixture이며 실제 Muse 청구·Google IAM·운영 DB 확장·새 배포 검증은 수행하지 않았다.
전체 개발과 P0-2를 완료로 표시하거나 자동 재개를 비활성화하지 않는다.

## Mission 상태 영속화 지원 (실제 DB 검증 완료·상위 병합 대기)

`codex/pg-integration`의 `50ffc5b`는 공개 mission facade에 PostgreSQL 선택 backend를 연결한다.
확장 006의 append-only 버전별 snapshot에 입력·확인·상태·단계 증거를 보존하고 RLS를 유지한다.
완료된 서버 출력과 단계 이벤트가 한 개로 확인될 때만 조회가 복원하며 모델은 재호출하지 않는다.
불완전하거나 중복된 출력은 409로 거부한다. HIGH 확인, 병렬 attach/mark 멱등성,
다른 DB 연결의 view 격리, 다른 scope의 404, DB 실패 시 메모리 우회 금지도 확인했다.
실제 로컬 Runner로 Generate→Review→Run→PR 저장을 확인했으며 Builder/Critic/GitHub는 합성 transport다.
봉인 원본은 서버에만 보존하고 HTTP에서는 기존 마스킹을 유지한다.

API **463 passed·1 skipped**, 실제 PostgreSQL **118 passed**(mission 신규 11개 포함),
참조 **112개**·SQL **96개**·계약 검사 **0 failure**, round7 웹 프로덕션 빌드 통과.
원본 로그 6개는 `C:\evo_forge\.local\evidence\mission-persistence-20261027-04hrzi1i`에 보존했다.
지원 브랜치의 `docs/validation/2026-10-27-mission-persistence.json`에 source·로그 SHA-256을 기록했고,
설정과 한계는 `docs/MISSION_PERSISTENCE.md`를 따른다.

앞 절의 mission 저장 미완료 기록 중 **지원 브랜치의 상태 저장**은 이 구현으로 대체된다.
현재 main은 여전히 기존 mission 구현이며, Muse T22(`muse/round8`)의 main/평가/UI·봉인 수용 테스트는 변경하지 않았다.
T22가 main에 먼저 반영되면 지원 브랜치에 동기화하고 공유 core의 호출 전 claim·명령 완료·비용 연결을 이어간다.
출력 없는 UNKNOWN 대사·동시 모델 호출의 실행권·mission 접수와 Objective 기록의 원자성,
공개 비용/명령/performance 저장·실제 청구·운영 DB/배포는 계속 미완료다. API min=max=1과 자동 재개를 유지한다.

## Critic 호출 증거의 mission 복구 누락 보강 (지원 검증 완료)

`codex/pg-integration`의 `4bbbf6d`는 리뷰 aggregate 저장 후 attach 중 종료될 때
호출별 provider_evidence_ids도 단계 포인터와 같은 snapshot에 복원한다. 이미 연결된 ID는 중복 추가하지 않는다.
확장 006은 같은 scope의 provider_call·spec→review 순서와 명시한 mission_id를 검사하고,
review 포인터가 있는 버전에서 호출 ID를 생략하는 직접 SQL도 거부한다.
Phase A 조기 종료의 단일 spec 기록은 보존한다. Runner의 봉인 suite 검사·정본 승인 경계는 변경하지 않았다.

수정 전 새 복구 집중 사례 **8 failed**를 확인했다. 수정 후 API **463 passed·1 skipped**,
실제 PostgreSQL **131 passed**(신규 회귀 13개 포함), 참조 **112개**·SQL **96개**·계약 **0 failure**,
웹 프로덕션 빌드가 통과했다. 공식 SDK에 모의 HTTP를 사용해 실제 리뷰 API의 세 연결 지점에서 중단을 주입했고,
재조회 시 호출 증거가 복원되며 Critic 재호출·중복 ID 저장이 없는 것을 확인했다. 실제 공급사 호출/청구 검증은 아니다.

원본 로그 8개는 `C:\evo_forge\.local\evidence\review-recovery-20261027-qvkgnfg8`에 보존했다.
지원 브랜치의 `docs/validation/2026-10-27-review-recovery.json`에 source·로그 해시와 범위를 기록했다.
이전 확장 006 지원 초안을 사용한 테스트 DB에는 SQL 재적용이 필요하며 과거 불변 기록은 수정하지 않는다.

저장된 리뷰 aggregate가 없는 UNKNOWN 호출은 이 복원 대상이 아니다. 기존 추정 원장의 호출 감사 기록을
canonical 청구 영수증으로 취급하지 않는다. T22 상위 병합·공유 core 실행권·명령/비용·운영 통합은 계속 대기하며,
전체 개발은 미완료이고 Muse Spark 기본값과 자동 재개를 유지한다.

## 테넌트 전체 선불 예약 가드 (지원 검증 완료)

`codex/pg-integration`의 `5b5b253`은 프로젝트 RLS 아래에서 정본 예약 함수가 다른 프로젝트의 open 예약을
보지 못하던 초과 예약을 재현하고, 확장 007의 비공개 hold 이벤트로 테넌트 전체 합계를 추가 검사한다.
정본 reserve/settle 함수와 프로젝트 RLS 정책은 그대로이며 core.authorize_merge를 변경하지 않았다.
SENT/UNKNOWN은 예약을 유지하고 정상 정산/해제 때만 hold를 닫는다. 실패 시 같은 트랜잭션에서 롤백한다.
core_app은 원본 private hold 테이블을 읽거나 수정하지 못하며 현재 tenant의 합계만 조회할 수 있다.

가드가 없거나 비활성화/replica 설정으로 실행되지 않으면 새 예약은 503으로 거부한다.
기존 데이터는 소유자의 DDL 트랜잭션 안에서 백필하고 원본/hold의 FORCE RLS를 복원한 뒤 커밋한다.
반복 적용은 이벤트를 중복 생성하지 않으며 과거 초과 예약을 임의 환불하지 않는다.
운영 적용 순서는 DB 확장 007 다음 새 API 배포다. 운영 DB에는 이번 턴에 적용하지 않았다.

수정 전 초과 예약 회귀 **1 failed**, 수정 후 API **463 passed·1 skipped**,
실제 PostgreSQL **139 passed**(신규 8개), 참조 **112개**·SQL **96개**·계약 **0 failure**·웹 빌드 통과.
같은 테넌트의 24개 병렬 예약 중 선불 잔액에 해당하는 10개만 허용했고,
UNKNOWN/정산/해제·롤백·닫힌 예약 재개방 금지·테넌트 격리·실제 core_app 권한·백필과 RLS 보존도 확인했다.

원본 로그 8개는 `C:\evo_forge\.local\evidence\tenant-credit-guard-20261027-ezvkqtpw`에 보존했다.
지원 브랜치의 `docs/validation/2026-10-27-tenant-credit-guard.json`에 source/로그 해시를 기록했고,
설정과 한계는 `docs/TENANT_CREDIT_GUARD.md`를 따른다.
상위 T22의 main/평가/UI·봉인 테스트는 보존했다. 공개 명령/비용 통합·실제 청구·운영 반영은 계속 미완료이며
Muse Spark `muse-spark-1.3`과 현재 채팅의 자동 재개를 유지한다.

## 정산·Git 증거에 따른 canonical Builder 후보 등록 (지원 검증 완료)

`codex/pg-integration`의 `e947cbf`는 인증된 내부 `POST/GET /v1/kernel/candidates`에서
같은 scope의 정산된 Builder call·canonical 영수증/원장·transport request ID·서버 저장 출력을 대조한다.
설정된 저장소의 immutable head가 reserved base에 Builder diff와 visible 테스트를 적용한 Git tree와
정확히 일치할 때만 PROPOSED 후보와 확장 008의 불변 binding을 원자적으로 저장한다.
현재 GitHub resolver에 맞춰 40자리 SHA-1만 허용하며 요청으로 모델/agent/tenant/경로/상태를 바꿀 수 없다.

Git 확인 중에는 DB 트랜잭션을 잡지 않고, 저장 직전에 fencing·동의·영수증·출력을 다시 확인한다.
등록 후 head/call이 바뀌면 Runner/G2 연결과 과거 PASS 재전송도 거부한다.
다른 필수 게이트·독립 리뷰·승인이나 후보 상태 전이를 만들지 않으며 core.authorize_merge의 거부를 유지했다.

API **465 passed·1 skipped**, 실제 PostgreSQL **144 passed**(신규 후보 등록 5개),
참조 **112개**·SQL **96개**·계약 **0 failure**·웹 빌드 통과.
동시 최초 등록 8회가 후보 하나로 수렴하고, 새 API 프로세스 조회·실제 로컬 Runner/G2 연결·병합 거부,
잘못된 모델/request ID/정산액/Git 변경 거부·fencing 재검사·binding 저장 실패의 원자적 롤백을 확인했다.
Builder/Critic/영수증/원격 checkout transport는 합성 fixture이며 실제 Muse 호출/청구 검증이 아니다.

원본 로그 7개는 `C:\evo_forge\.local\evidence\candidate-registration-20261027-u3iva17t`에 보존했다.
지원 브랜치의 `docs/validation/2026-10-27-candidate-registration.json`에 source/로그 해시,
`docs/CANDIDATE_REGISTRATION.md`에 경로·008 적용·제한을 기록했다.
상위 T22의 main/평가/UI·봉인 수용 테스트는 보존했고 지원 코드는 main 미반영이다.
공개 Generate/mission/PR의 명령·Broker 예약/영수증·후보 등록 호출·PR base 전달과 전체 승인·운영 배포는 계속 미완료다.
Muse Spark 기본값과 현재 채팅의 자동 재개를 유지한다.

## 정산과 새 예약의 프로젝트 cap 경합 보강 (지원 검증 완료)

`codex/pg-integration`의 `c479487`은 초기 예산 확인 뒤 기존 호출이 더 높은 실제 금액으로 정산될 때,
초기 사용액을 기준으로 새 예약이 한도를 초과하던 경합을 확장 007에서 차단한다.
INSERT 시점의 테넌트 잔액/hold와 프로젝트 현재 cap/사용액을 같은 snapshot으로 확인하며 새 예약도 사용액에 포함한다.
이미 발생한 정산·청구는 보존하고, 거부된 새 예약과 intent/hold는 커밋하지 않는다.

회귀는 cap 1000µUSD·기존 예약 100µUSD에서 새 900µUSD 예약을 초기 cap 검사 뒤 대기시킨다.
기존 호출을 900µUSD로 정산한 뒤 새 요청을 재개해 거부하고, 남은 100µUSD는 예약을 허용했다.
수정 전 **1 failed**, 수정 후 API **465 passed·1 skipped**·실제 PostgreSQL **145 passed**,
참조 **112개**·SQL **96개**·계약 **0 failure**·웹 프로덕션 빌드 통과.
정본 SQL·reserve/settle·core.authorize_merge와 프로젝트 RLS 정책은 변경하지 않았다.

원본 로그 8개는 `C:\evo_forge\.local\evidence\project-cap-race-20261027-4io029zf`에 보존했다.
지원 브랜치의 `docs/validation/2026-10-27-project-cap-race.json`에 source/로그 해시,
`docs/TENANT_CREDIT_GUARD.md`에 007 재적용과 한계를 기록했다.
실제 공급사 호출·운영 DB 적용/배포는 수행하지 않았다. T22 Muse 실행 프로세스가 동작 중인 것을 확인했고 중복 실행하지 않았다.
공개 명령·Broker 비용/영수증·전체 승인·운영 연결은 계속 미완료이며 Muse Spark와 자동 재개를 유지한다.

## 병합 승인의 현재 정책·자격 검사 (지원 검증 완료)

`codex/pg-integration`의 `1441518`은 후보/task/run 공유 잠금 아래에서 head와 정책이 현재 run에 맞는지 확인한다.
정본 core.authorize_merge를 그대로 호출한 뒤 HIGH/CRITICAL의 context-independent spec-first approve 검증자 자격을
실제 DB 시각에도 확인한다. 트랜잭션 시작 시각에 고정된 now()로 지연 중 만료된 자격을 승인하지 않는다.
게이트·리뷰·사람 승인·자격이나 후보 상태를 생성하지 않으며 Agy의 자격 시험 알고리즘은 수정하지 않았다.

수정 전 정책 변경/트랜잭션 중 자격 만료 회귀 **2 failed**, 수정 후 API **465 passed·1 skipped**,
실제 PostgreSQL **147 passed**(신규 2개), 참조 **112개**·SQL **96개**·계약 **0 failure**·웹 빌드 통과.
만료된 HIGH 자격을 거부하고 새로 유효한 자격을 추가했을 때 정상 승인되는 것도 확인했다.
승인 근거는 합성 DB fixture이며 실제 운영 승인이나 GitHub 병합을 실행한 것이 아니다.

원본 로그 8개는 `C:\evo_forge\.local\evidence\merge-freshness-20261027-jomlv8hr`에 보존했다.
지원 브랜치의 `docs/validation/2026-10-27-merge-freshness.json`에 source/로그 해시,
`docs/POSTGRES_KERNEL.md`에 검사 시점과 실제 외부 병합 전 재검사/expected head 요구를 기록했다.
정본·상위 main/평가/UI·봉인 테스트·Agy 소유 모듈은 보존했고 별도 Git 설치 CI 변경도 동기화해 보존했다.
공개 명령/Broker 비용·검증 전체 연결·실제 청구/운영 배포는 미완료이며 Muse Spark 기본값과 자동 재개를 유지한다.

## Context Mesh·리뷰어 자격·공급망/공정 큐/키 격리 고도화 (main 반영 완료)

`ebfeb95`는 상위 Muse T22(`muse/round8`) 및 Codex(`codex/pg-integration`)와 분리된 런타임 모듈 3종과 수용 테스트 15개로
`Acceptance_Test_Matrix.md` 및 `SERVICE_STATUS.md` P1의 미구현 시나리오를 구현·검증했다. 상세 매핑은 [CR_CLOSURE_ADVANCEMENT.md](CR_CLOSURE_ADVANCEMENT.md).

- `evoforge/context_mesh.py`: 결정적 `log.text` 코덱 및 독립 파서 기반 L1–L5 Fidelity Gate, 블롭별 DEK 포락선 암호화·read-back SHA 검증(CR-01)·임의 evict 없는 용량 상한(CR-20)·crypto-shred/색인 제거/패킷 REVOKED/legal-hold 차단(CR-17)·Vault 장애 시 Critic 승인 차단(CR-16), Folder Bridge 및 REST 복원 게이트웨이(CR-06/07/15/21), `A_RAW` 캐시 기준선·복원률 70% 손익분기·기능 플래그 OFF 폴백·5-Agent A/B 계측 온라인 결정 엔진(CR-12/18/24/28), 테넌트 32바이트 `cache_namespace` 솔트(CR-26)·연속 턴 L0–L2 해시 고정(CR-25)·런타임 프롬프트 인젝션 및 민감도 라우팅 차단(CR-11/19) Context Packet v2 컴파일러.
- `evoforge/review_qualification.py`: 409,600B 초과 대형 Diff PR 분할/인간 리뷰어 요구 및 hunk 단위 `review_chunk`+`review_cross_chunk` 계획(CR-32), 리뷰어별 바이트 구간 합집합(`range_agg`) Review Coverage 원장 및 `assert_review_gate`(CR-08/10/14/32), Seeded-Defect Canary 검출률(`context_fidelity_probe_score`) 기반 승인자 풀 자동 제외 및 SNR 정밀도·버전 변경 재자격·HIGH/CRITICAL 독립성+인간 승인 통합 검사(CR-34/58/66/68).
- `evoforge/runtime_guards.py`: BSL-1.1/Caveman/LiteLLM/미고정 Git 의존성 공급망·SBOM 스캐너 및 실패 시 기존 코덱 버전을 유지하는 릴리스 가드(CR-23/35), 단일 테넌트 폭주 시 정상 테넌트 대기시간 p95 증가율을 ≤ 20%로 제한하는 Start-Time Fair Queuing 스케줄러(CR-49), `provider_broker` 신원만 복호화를 허용하고 그 외 모든 신원의 복호화 성공 0건을 강제하는 KMS 포락선 키 가드(CR-50).

근거: API **465 passed·1 skipped**(신규 CR 수용 테스트 15개 포함), 참조 **112개**·`validate_package.py` **0 failure** 통과.
기존 `main.py`·웹·DB 마이그레이션·정본(`docs/evoforge-v4.2/`)은 변경하지 않았다. 실제 외부 공급사 과금 호출·GCP KMS 하드웨어 연동·운영 배포는 별도 범위다.

## 상위 CR 모듈·Critic·배포 수정과 PostgreSQL 지원의 동기화 검증

`codex/pg-integration`의 `41949da`는 main `2cb3627`까지의 CR 모듈(`ebfeb95`),
Critic 16k 출력 예산(`fa02e57`), 웹 API base/표시 수정(`25480fd`), CI Git 설치/collection 보호와
배포 인프라 수정을 보존해 합쳤다. Codex의 병합 정책/자격 시점 수정(`1441518`)과 전체 지원 코드도 함께 검증했다.

API **485 passed·1 skipped**, 실제 PostgreSQL **147 passed**, 참조 **112개**·SQL **96개**·
계약 **0 failure**·웹 프로덕션 빌드 통과. 이전 API 465개 기록은 상위 변경 동기화 전의 검증으로 보존한다.
원본 로그 6개는 `C:\evo_forge\.local\evidence\upstream-sync-20261027-n32bxlnp`,
source 33개와 로그의 SHA-256은 지원 브랜치 `docs/validation/2026-10-27-upstream-sync.json`에 기록했다.

실제 DB/Git/Runner를 실행했지만 모델 transport·영수증·승인/자격 근거는 합성 fixture다.
새 독립 모듈의 공개 경로 연결·실 GCP KMS·실청구·Docker 이미지/운영 배포는 이 검증으로 완료 처리하지 않는다.
Muse T22의 main/평가/UI·봉인 테스트를 보존했으며 그 상위 병합 후 공개 명령/Broker 비용·전체 승인 연결을 이어간다.
지원 코드는 main 미반영이고 전체 개발은 미완료다. Muse Spark `muse-spark-1.3`과 현재 채팅의 자동 재개를 유지한다.
