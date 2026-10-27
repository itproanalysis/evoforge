# EvoForge 정식 서비스 — 구현 현황과 출시 갭

갱신: 2026-10-27 (main `b411739` 기준). 정본 명세 `docs/evoforge-v4.2/`는 수정하지 않는다(README 규칙).
이 문서는 정본의 수용 매트릭스(`contracts/Acceptance_Test_Matrix.md`, 계약 수준)와 별개로 **실행 중인 서비스**가
무엇을 실제로 하는지 기록한다. 계약 수준 통과는 서비스 통과가 아니다.

## 1. 실제 동작 확인된 경로 (2026-10-27, 소유자 Meta 키)

GitHub 저장소 → 목표 → Builder 패치(Muse Spark 1.3) → Critic 봉인 테스트(Phase A, 3종) → 서버 실행(위생 샌드박스,
visible 3/3·held-out 3/3) → 게이트 `GH_INTEGRITY`·`GC_COMPOSITION`·`G2_REQUIRED` 전부 PASS → 검증 PR
[itproanalysis/evoforge-target#1](https://github.com/itproanalysis/evoforge-target/pull/1) (본문에 게이트 판정과 evidence id).
원장 실지출 기록(정수 cents), UNKNOWN 0.

## 2. 서비스에 구현된 것 (근거 = `services/api/tests`)

| 영역 | 구현 | 관련 ID |
|---|---|---|
| 공급사 호출 경계 | 예약 → 호출 → 정산, 접수 안 됨=환불 / 결과 불명=UNKNOWN 보류, 영수증 대사, 자동 재시도 끔, 추론 모델 토큰 예산·절단 명시 | CR-37·38·39·47, D-019(부분) |
| 명령 | 멱등 키, 위험 명령 confirm, 상태 전이 | CR-42·43 |
| 무결성 게이트 | 오라클 강도·held-out 구성·격차·조회 테이블·변조 탐지, 0건 실행=증거 부족, `G2_REQUIRED`=필수 테스트 실제 실행·전부 통과 | CR-62·63·64·79, p.36 |
| 서버 Runner | base까지만 재구성한 위생 샌드박스, diff 엄격 적용, 비밀 env 제거, held-out 격리(conftest·ini·플러그인·sitecustomize·파일 변조 차단) | CR-74(부분), D-050 |
| 봉인 스위트 | Critic 리뷰로 서버 저장, 클라이언트 held-out 거부, stub·형식 위반 거부, HTTP에 코드 비노출 | CR-64, D-030 |
| PR | 서버 실행 증거 + 전부 PASS일 때만, 파일에 diff 적용(덮어쓰기 아님) | CR-45(부분) |
| 증거 | 단계 체인(ObjectiveVersion→…→Outcome), `GET /v1/events/{id}` 드릴다운, 없는 단계는 null | README "증거 부족" |
| 웹 | Mission Control(실제 원장), Improvement Lab(Review→서버 Run→PR), Evidence 드릴다운 | — |
| PostgreSQL 커널 | 정본 함수 어댑터·영수증 저장·내부 `/v1/kernel` API (Codex) — **요청 경로 미연결** | CR-37~48(DB) |

## 3. 정식 출시 갭

### P0 — 출시 차단

| # | 갭 | 상태 (2026-10-27) | 근거 |
|---|---|---|---|
| P0-1 | 인증·권한 | **완료** — 소유자 로그인(scrypt, `__Host-` HttpOnly Secure 쿠키, 시도 제한), 페이지 middleware, `/api/evoforge` 프록시(경로 정책), API는 web SA의 Google ID 토큰만 허용 | T14·T14b·T14c, GCP: API 직접 403, 소유자 본인 토큰도 401, 프록시 무세션 401 |
| P0-2 | 영속성 | **미완료(Codex 진행 중)** — 요청 경로가 메모리. 그때까지 API `min=max=1` | `docs/DEVELOPMENT_STATUS.md` Codex 클레임 |
| P0-3 | Runner 격리 | **완료** — 별도 `evoforge-runner`(무권한 SA, 비밀 없음, api SA만 호출), base-only git bundle | T16, GCP: Runner 직접 403 |
| P0-4 | 원격 저장소 | **완료** — 구성된 GitHub 저장소를 base(또는 ref)로 서버 체크아웃, 토큰은 env의 Basic 헤더 | T15·T15b, 실 비공개 저장소 체크아웃 |
| P0-5 | Builder 문맥 | **완료** — `target_paths` 파일 내용(32KB/128KB 상한·경로 제한)을 Builder에 전달 | T17 |
| P0-6 | PR 내용 | **완료** — Builder 테스트를 `tests/evoforge_gen/`로 PR에 커밋, 봉인 코드는 제외 | T17, [#2](https://github.com/itproanalysis/evoforge-target/pull/2)·[#3](https://github.com/itproanalysis/evoforge-target/pull/3) |
| P0-7 | 비밀 | **완료(토큰 교체 필요)** — Secret Manager, 서비스별 접근(api: Meta 키·GitHub, web: 세션·해시, runner: 없음). `GITHUB_TOKEN`은 소유자 gh 토큰 → 대상 저장소 한정 토큰으로 교체 필요 | `docs/DEPLOY_PRODUCTION.md` |

**GCP 정식 운영 검증 (2026-10-27, `evoforge-prod-4ff3`):** 공개 web 출처로만 소유자 로그인 → Generate(Muse Spark, `calc.py` 문맥) →
Critic 봉인 3종(HTTP 코드 비노출) → Cloud Run Runner 실행 visible 4/4·held-out 3/3 → 게이트 전부 PASS →
PR [evoforge-target#3](https://github.com/itproanalysis/evoforge-target/pull/3) (수정 + 테스트). 원장 360¢, 프록시로 `/v1/kernel` 404.
알려진 사항: Cloud Run은 `z`로 끝나는 경로(`/healthz`)를 예약해 404를 돌려준다(헬스 프로브 미사용). run 증거 체인에 Review 단계 미연결.

### P1 — 출시 직후

- 명령 lifecycle 자동화(Generate→Review→Run→PR을 하나의 명령 상태로), Mission Control 지표를 실제 상태에서 계산.
- 봉인 평가 세트 v0 + `X_SINGLE` 기준선 측정(Phase 4), 리뷰어 자격 시험.
- Review Coverage(RAW 인라인 + REF_ONLY Diff), 대형 Diff 분할(CR-32).
- 공정 큐·플랫폼 키 IAM 시험(CR-49·50), SBOM·BSL 스캔(CR-23·35).

### P2 — M2·M3 범위

5좌석·토폴로지, MCP 서버, Context Packet Compiler·codec·Fidelity Gate, 투기 실행·cascade 등 TRIAL 기법.

## 4. 진행 방식

`AGENTS.md` 서열(Muse Spark 1 > Claude 2 > Codex 3). P0 구현은 Muse Spark가 계획·구현하고 Claude가 봉인 테스트·리뷰,
GCP 인프라 구성은 Claude, PostgreSQL 커널 연동은 Codex 범위.
