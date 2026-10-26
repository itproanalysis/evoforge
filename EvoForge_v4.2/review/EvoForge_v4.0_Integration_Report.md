# EvoForge v4.0 통합 보고서

대상: `legacy/v3.6/EvoForge_Production_Blueprint_50pages_v3.6.md`(페이지마다 v3.1~v3.6 절이 쌓인 246KB 문서)와 v3.6 계약 패키지 · 작성일 2026-10-25

## 1. 결과 요약

| 항목 | v3.6 | v4.0 |
|---|---|---|
| 기획서 구조 | 50페이지 × 버전 절 최대 6개 | 50페이지 × 현재 유효한 결정 1개 |
| 크기 | 246KB | 157KB (중복 제거) |
| 페이지 서식 | 자유 | 목적·결정·계약 머리줄 + 요구사항 표(validator 강제) |
| 요구사항 | 페이지별 "수용 기준" 문장 | 160개(`R{NN}-{n}`), 모두 수용 기준 포함 |
| 결정 | D-001~D-016 + 버전별 산발 결정 | 결정 레지스터 D-001~D-040(p.50), ADR-035~053 |
| 어휘 lint 범위 | v3.5/v3.6 절만 | 기획서 전체 + 계약 문서 + 빌드 프롬프트 |
| 실행 계약 | ctx SQL 39개 검사, 참조 구현 22개 | + core SQL 46개 검사, 품질 판정 21개 |
| 검증 | validator C1–C8 | + C9(페이지 서식·추적성·참조 해석) |

`tools/validate_package.py --pg` 전체 통과: 스키마 4종, 예시 34개(valid 6 / invalid 28, 실패 사유까지 일치), 어휘 lint 5개 파일, 50페이지 바이트 동일성, README 참조, 참조 구현 43개, SQL 85개(PostgreSQL 16.15). 의도적으로 오류를 넣어 validator가 잡는지도 확인했다(미등록 결정·CR ID·SQL 테스트 ID·없는 파일·폐기 용어 → 모두 FAIL).

## 2. 사용자 결정 반영

| 결정 | 내용 | 반영 위치 |
|---|---|---|
| 1. 상용 라이선스 미사용 | Caveman 엔진 계열(BSL-1.1) 코드 미사용, 공개 문서만 참고한 클린룸 구현, MIT 경로만 허용, 제품명에서 상표 제거 | D-018, ADR-036R, p.05·p.32·p.45·p.50, 빌드 프롬프트 금지 항목, CR-35 |
| 2. 품질 기준을 최적으로 정의 | Quality Gate Framework v1: 불리한 쪽 경계 판정, 안전 0 허용, Tier A(δ 5%p)·Tier B(δ 2%p), cluster bootstrap, 관측 불일치율 기반 검정력, 리뷰어 자격, codec 런타임 감시, 10X 사다리 | D-020, ADR-048, p.36·p.37, `contracts/quality_gates.json`, `reference_impl/quality_gate.py`(21개 테스트) |
| 3. 제안 수준 채택 | 리뷰 Diff 한도 400KB, Lease 10분, Registry 14일, backpressure 80%, 컨텍스트 결정 30세션·70% 등을 기본값으로 | D-021, ADR-049, p.35·p.29·p.22·p.31·p.39 |
| 4. 플랫폼 키 | 고객은 키를 넣지 않음. KMS·Broker 단일 복호화, 선결제 크레딧·호출 전 예약·하드캡, 테넌트 공정 큐, namespace 솔트 필수, 공급사 DPA·약관 확인, 국외 이전 법률 검토, BYOK는 범위 밖 | D-019, D-026, D-034, ADR-047, p.03·p.04·p.05·p.07·p.09·p.19·p.21·p.22·p.34·p.45·p.46·p.48, `core.reserve_cost`·`usage_ledger`, receipt 스키마 |
| 5. 전체 통합 | 버전 레이어 제거, 페이지별 단일 정본, 충돌 해소 | D-022, ADR-050, 이 보고서 §3 |

## 3. 충돌 해소 목록

| # | 주제 | v3.x에 있던 변형 | v4.0 정본 | 페이지 |
|---|---|---|---|---|
| 1 | North Star | Weekly Verified Improvements(건수) / Weighted Verified Improvement / Weighted Verified Impact per week / VFI 공식 / Verified Impact per Week | **WVI** = 사전 고정 가중치의 검증 개선 합/주 + 가중치 없는 검증 PR/주 병기 | p.10 |
| 2 | 명령 상태 | `accepted→planned→dispatched→applied/blocked` / `command_accepted→…→operation_applied` / `RECEIVED…FAILED` / `accepted/planned/applied/rejected/pending_safe_stop` | 단일 수명주기 + 위험 명령용 `AWAITING_CONFIRMATION`, DB 트리거 | p.08·p.13 |
| 3 | 에이전트 상태 | API·Chat 별도 목록, 7상태, `WAITING/READY/ACTIVE/OFFLINE`, 슬롯 표시 6종, 가입 상태 2가지 표기 | 4차원(join/connection/execution/credential) + UI 슬롯 표시는 파생값 | p.15·p.19·p.21·p.26 |
| 4 | 토폴로지 이름 | `SINGLE/PARALLEL_CANDIDATES/HIERARCHICAL/PIPELINE`, `RACE/PARALLEL_DAG`, `Single/Parallel/Hierarchical`, `RACE_2/DAG_PARALLEL/HIGH_RISK` | `SINGLE`, `RACE_2`, `DAG_PARALLEL`, `PIPELINE`, `HIGH_RISK` | p.15·p.28 |
| 5 | 병렬 후보 수 | v3.1 "최대 2개" vs v3.4 "Builder 최대 3" | v3.4 구성 + 승격 규칙(순이득 > 비용) + 과잉 협업 상한(R28-1) | p.28 |
| 6 | 실험군 라벨 | 제품 A–E(v1), A–F(v3.4), 컨텍스트 A_RAW… — 같은 글자가 다른 뜻 | 제품 `X_*`, 컨텍스트 `A_RAW…`로 분리 | p.37 |
| 7 | 품질 게이트 | 7단계 목록(v1) vs G0–G4(v3.4), 리뷰의 위치 불명확 | G0_SCOPE·G1_IMPACTED·G2_REQUIRED·G3_BENCHMARK·GR_REVIEW·G4_MERGE_HEAD, DB 기록 | p.36 |
| 8 | 기억·컨텍스트 계층 | 3단(Immutable/Shared/Dynamic), 4분할(정책/계약/증거/Playbook), 3계층 기억, 4-Layer Memory, L0–L3 | 기억 저장소 M-CONTRACT/M-EVIDENCE/M-GRAPH/M-PLAYBOOK와 Prompt 레이어 L0–L3를 별개 개념으로 | p.32·p.40 |
| 9 | 로드맵 | 단계 0–4(주 단위), VS0+게이트, 연구 P0–P3, Phase 0–4(두 종류), P0-1~7 | 마일스톤 사다리 M0–M6 + Exit 기준 | p.49 |
| 10 | 내비게이션 | 10개 메뉴 vs 8개 메뉴 | 9개 + Advanced(연구) | p.11 |
| 11 | 테넌트 컬럼 | `org_id`(v1·v3.1) vs `tenant_id`(ctx) | `tenant_id` | p.42 |
| 12 | 명령 엔드포인트 | 프로젝트 하위 / 최상위 / Run 하위 3종 | 프로젝트 하위 하나(본문 `scope`) + `GET /v1/commands/{id}` | p.43 |
| 13 | 피드백 | 분류 5종 vs 7종, CLOSED/RESOLVED 의미 혼재 | 7종 + 단일 상태 목록(RESOLVED는 검증 근거 있을 때만) | p.18 |
| 14 | 비용 주체 | 12개 페이지가 BYOK 전제 | 플랫폼 키 전제로 재작성 | §2 결정 4 |
| 15 | codec 비활성화 | "200건 중 게이트 실패 2%" | shadow 감사 기반 miss율(안전)과 폴백률(효율) 분리 | p.37·p.47 |
| 16 | 실험 margin | "−2%p(제안값)" 단일 문장 | Tier A/B + 검정력·군집·과소표본 규칙 | p.37 |
| 17 | 없는 파일 참조 | `schema/core.sql`, `contracts/openapi.yaml`, `implementation_contracts/…`, `v3_3_migration.sql` | core 스키마는 `contracts/sql/core_DRAFT.sql`로 작성·테스트, OpenAPI는 빌드 Phase 1에서 생성 | p.42·p.43 |
| 18 | 문서 구조 결함 | p.50 중간의 "문서 본문 종료" 문구 뒤에 v3.4·v3.5 절 | 단일 p.50, 종료 문구는 끝에 | p.50 |
| 19 | 병합 권한 | AI 리뷰·인간 승인·정책 엔진 관계가 여러 페이지에 다르게 서술 | `core.authorize_merge` 하나로 정의 | p.06·p.33·p.35 |

## 4. 목표 달성을 위한 최적화 판단

1. **증명 수단을 기능보다 먼저.** 10X·비용 절감은 X_SINGLE 기준선과 봉인 평가 세트가 없으면 판정할 수 없다. v3.x 로드맵은 이것을 뒤쪽(Phase 0이나 Phase 4)에 두기도 했다. v4.0은 M0 Exit 기준에 넣었다.
2. **압축 codec을 M3로 늦췄다.** v3.5/v3.6은 codec을 P0로 잡았지만, A_RAW 실측 없이는 절감을 증명할 방법이 없다. M0–M2는 RAW + 원문 커버리지(안전 기능)만 운영하고 기준선을 쌓는다.
3. **플랫폼 키의 과금 안전을 첫 호출 전 조건으로 만들었다.** 예약·하드캡·원장은 DB가 강제하고(C-13/C-14), 모든 receipt가 `reservation_key`를 필수로 갖는다.
4. **품질 판정의 비용과 검정력을 맞췄다.** δ 2%p는 불일치율 0.10에서 1,546쌍이 필요하다. 그래서 모든 결정에 Tier B를 요구하지 않고, Tier A(248쌍)로 걸러낸 뒤 Canary·shadow 재생으로 Tier B 쌍을 누적한다. 표본이 부족하면 FAIL이 아니라 UNDERPOWERED로 두어, "통계적으로 아무것도 몰랐는데 통과"와 "나쁘다고 확인됨"을 구분한다.
5. **10X를 현실적인 사다리로.** 병렬화만으로는 Amdahl 한계(직렬 10%, 5좌석 ≈ 3.6배)를 넘지 못한다. M2 하한 1.5배, GA 하한 3배를 상업 목표로, 10배는 장기 목표로 두고 공개 문구는 구간 하한만 쓰게 했다.
6. **연구 루프는 GA 이후(M6).** 하네스 진화는 실행 trace와 봉인 평가가 쌓여야 의미가 있고, 그 전에는 고객 검증 PR 생산을 늦추기만 한다.
7. **연동 표준은 필요한 순서대로.** MCP·Folder는 M2, A2A는 M4. v3.x가 경고했던 "통신 표준부터 다 만들다 핵심을 못 만드는" 위험을 일정에 반영했다.
8. **DB가 불변식을 강제한다.** 병합 승인·fencing·명령 확정·부작용 재시도·과금 규칙이 서비스 코드 버그와 무관하게 지켜진다.

## 5. 이번에 줄이거나 옮긴 것

- 하네스 진화 의사코드, 연구 API 상세 표, ScholarEvolve 세부 서술 → 요약만 p.38에 두고 원문은 `legacy/v3.6/`에 보존(M6 착수 시 다시 구체화).
- 연구 스키마 → p.42에 테이블 목록만 두고 "M6, 미작성"으로 명시.
- 근거 링크 중 이번에 다시 확인하지 않은 것(AG-UI, A2UI, Temporal, GitHub 문서, OTel, OWASP)은 p.50에 "재확인하지 않음"으로 표시.

## 6. 남은 위험과 다음 결정

| 항목 | 상태 | 필요한 행동 |
|---|---|---|
| 공급사 상업 약관(SaaS 내 재제공·최종 사용자 조건) | 미확인 | M1 전 공급사별 법무 확인(R05-2). 미확인 공급사는 allowlist에 올릴 수 없음 |
| 공급사별 테넌트 하위 키(프로젝트·워크스페이스) 지원 | 미확인 | M0에서 공급사별 확인 후 Registry에 기록 |
| 개인정보 국외 이전·처리위탁 | 미검토 | 한국 출시 전 법률 검토(p.46) |
| 모델 사용 마크업 시작값 20%, 체험 크레딧 | 제안값 | 코호트 실험으로 조정(p.09) |
| 공정 큐 기준(대기 p95 증가 ≤ 20%) | 제안값·미구현 | M4 부하 시험(CR-49) |
| 플랫폼 키 IAM 격리 | 미구현 | M0 IAM 시험(CR-50) |
| 런타임 구성요소(Vault 왕복, Gateway, Compiler, A/B 하네스, CI 공급망) | 미구현 | 빌드 프롬프트 Phase 3–7 |
| 라이선스 해석 | 공개 문서 기반 | 법무 확인 필요(법률 자문 아님) |
