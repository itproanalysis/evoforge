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

| # | 갭 | 현재 | 필요한 것 |
|---|---|---|---|
| P0-1 | 인증·권한 | API·웹 무인증 | 웹 로그인 세션, API 비공개(웹 서버만 ID 토큰으로 호출), 허용 계정 제한 |
| P0-2 | 영속성 | 증거·비공개 리뷰·이벤트/체인은 PostgreSQL 선택 모드 연결. 명령·공개 원장은 메모리 | canonical 명령·비용 커널 연결과 운영 Cloud SQL 검증. [현재 범위](EVIDENCE_PERSISTENCE.md) |
| P0-3 | Runner 격리 | API 프로세스 안 subprocess, 메타데이터 서버·네트워크 접근 가능 | 비밀·권한 없는 별도 Runner 서비스, API가 base 번들만 전달 |
| P0-4 | 원격 저장소 | Runner가 로컬 경로만 허용 | 구성된 GitHub 저장소를 base에서 서버가 체크아웃 |
| P0-5 | Builder 문맥 | 목표 문장만 전달(파일 내용 없음) | 대상 파일 내용(크기 상한·경로 제한)을 Builder에 전달 |
| P0-6 | PR 내용 | 수정 diff만, Builder 테스트 미포함 | 새 테스트 파일도 PR에 포함 |
| P0-7 | 비밀 | 환경 변수 | Secret Manager(Broker 신원만 접근), 최소 권한 서비스 계정 |

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
