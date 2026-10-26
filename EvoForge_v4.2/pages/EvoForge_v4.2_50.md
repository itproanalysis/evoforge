<!-- PAGE:50/50 -->

# 50. 출시 기준·결정 레지스터·근거

> **목적:** 출시 판단 기준, 확정 결정 목록, 확인한 외부 근거를 한 곳에 둔다. · **결정:** 전체 · **계약:** `contracts/Architecture_Decisions.md`, `contracts/Acceptance_Test_Matrix.md`

### GA Go/No-Go 체크리스트
- [ ] `tools/validate_package.py --pg` CI 통과(스키마 5종·예시·어휘·페이지 정합성·참조 구현 112개·SQL 96개).
- [ ] 가입 → 조직·프로젝트 → GitHub 연결 → 공급사 allowlist → 첫 검증 PR이 셀프서비스로 완료.
- [ ] 플랫폼 키: Broker 외 복호화 0, 회전·사고 훈련 완료, 공급사 약관·DPA 확인 완료.
- [ ] 공급사 호출 100%가 예약 후 실행, 초과 실행 0, 청구 = 원장 = receipt 대사.
- [ ] 5좌석 토폴로지가 과제별로 동작하고, 단일 과제에서 불필요한 좌석은 쓰지 않음.
- [ ] 지원 AI Chat이 MCP 또는 Folder로 실제 참여·결과 제출(비지원은 수동 참여로 표시).
- [ ] Claim·Lease·fencing·재배정·중복 메시지·복구 통합 테스트 통과.
- [ ] 결함 패치 4종이 게이트에서 차단되고, INCONCLUSIVE 병합 0, 미승인 병합 0.
- [ ] `GH_INTEGRITY`·`GC_COMPOSITION` 없이 병합 0, 봉인 held-out 격차 Δ 보고, 평가 샌드박스 git 이력 제거 확인.
- [ ] HIGH/CRITICAL 병합 전부에 자격·컨텍스트 독립·명세 선행 approve + 인간 승인.
- [ ] 리뷰어 approve는 원문 커버리지 100% 후에만, 자격 미달 리뷰어 approve 0.
- [ ] 명령 접수와 적용이 분리 표시되고, STOP_ALL이 부하와 무관하게 동작.
- [ ] 멀티테넌트 격리·캐시 격리·침투 시험·DR·백업 복구 완료.
- [ ] 데이터 처리·국외 이전·보존·삭제·결제 고지·지원 채널 준비.
- [ ] Quality Gate Tier B: 기본값 토폴로지·codec 비열등 + 안전 0, 속도 비율 하한 ≥ 3.0 보고(미달이면 미달로 보고).
- [ ] 10X는 사전 등록 평가의 하한으로만 표기.
- [ ] 빌드 SBOM에 Caveman BSL 경로 코드 0, 로컬 모델 런타임 의존성 0.

### 결정 레지스터
| ID | 결정 | ADR |
|---|---|---|
| D-001 | 지속형 다중 주체 운영 플랫폼, 단일 채팅 제품 아님 | — |
| D-002 | 로컬 LLM/GPU 추론 제외, 외부 API 중심 | — |
| D-003 | 외부 AI Chat은 능력·권한별 비상주 참여, 수동 참여 표시 | — |
| D-004 | A2A·MCP는 외부 연동 어댑터, 내부 정본은 자체 도메인 | — |
| D-005 | PostgreSQL 정본 + Outbox + 비동기 워커 + 격리 Runner, Temporal은 실측 후 | — |
| D-006 | 기본 자동화 모드 ASSISTED, 승격은 명시 승인 | — |
| D-007 | 병합 최종 판단은 결정적 정책(`core.authorize_merge`), LLM 리뷰는 근거 중 하나 | ADR-052 |
| D-008 | 목표·작업·코드·검증·결과·피드백을 Evidence Graph로 연결 | — |
| D-009 | UI는 확정 이벤트만 반영, 접수와 적용 분리 | — |
| D-010 | 요금·SLO·성능 목표는 가정, 실측으로 확정 | — |
| D-011 | Customer Software Loop와 Harness Research Loop 분리 | — |
| D-012 | 하네스 5모듈 T/C/S/M/W | — |
| D-013 | 연구·저장소 텍스트는 비신뢰 데이터 | — |
| D-014 | D_evo/D_val/D_test 분리와 봉인 평가 | — |
| D-015 | 동의 없는 테넌트 간 연구 데이터 공유·학습 금지 | — |
| D-016 | 승격·롤백은 원자적, 진행 중 Run은 버전 고정 | — |
| D-017 | 제3자 LLM 게이트웨이(LiteLLM 등) 기본 의존성 제외, 공식 SDK | — |
| D-018 | Caveman 엔진 계열 코드 미사용, 클린룸 구현(사용자 결정) | ADR-036R |
| D-019 | 플랫폼 관리 공급사 키, BYOK는 범위 외(사용자 결정) | ADR-047 |
| D-020 | Quality Gate Framework v1(사용자 결정) | ADR-048 |
| D-021 | 제안 수준 임계값을 기본값으로 채택, `quality_gates.json`으로 버전 관리(사용자 결정) | ADR-049 |
| D-022 | 단일 통합 명세, 실행 계약 우선(사용자 결정) | ADR-046, ADR-050 |
| D-023 | 항목별 fidelity와 호출별 cache_mode 분리 | ADR-041N |
| D-024 | 좌석과 기능 역할 분리, 토폴로지 5종 | ADR-042N, ADR-053 |
| D-025 | 결정적 codec, compress-on-insert | ADR-043N |
| D-026 | 테넌트 cache namespace 솔트 필수 | ADR-044N |
| D-027 | ref = 무작위 grant, 외부/미존재 동일 not_found | ADR-037R |
| D-028 | Review Coverage Ledger | ADR-039R |
| D-029 | 비용 기준선은 A_RAW 실측, 복원 = 추가 턴 | ADR-038R |
| D-030 | 감사 append-only(무FK), 삭제는 crypto-shred | ADR-045N |
| D-031 | Fast lane 명령 분리, 위험 명령 확정 | ADR-052 |
| D-032 | Lease epoch fencing | ADR-052 |
| D-033 | 외부 부작용 intent, UNKNOWN은 조회 후 진행 | ADR-052 |
| D-034 | 선결제 크레딧 + 호출 전 예약 + 하드캡(DB 강제) | ADR-047, ADR-052 |
| D-035 | 마일스톤 사다리 M0–M6(codec은 기준선 이후, 연구는 GA 이후) | ADR-051 |
| D-036 | WVI 단일 정의, 10X 사다리는 구간 하한 판정 | ADR-048 |
| D-037 | microVM 격리 기본, 개발/검증 Runner 풀 분리 | — |
| D-038 | AI 리뷰 ≠ 인간 승인, 고위험 인간 승인(재인증) | ADR-052 |
| D-039 | MCP 2026-07-28 기준, 폐지 예고 기능 미사용, Tasks는 선택 확장 | — |
| D-040 | `tenant_id` 명명, UUID, 정수 micro 금액 | ADR-053 |
| D-041 | HIGH/CRITICAL 독립성 = 자격 + 컨텍스트 독립 + 명세 선행, 반례만 피드백(공급사 다양성 불요) | ADR-054 |
| D-042 | 병합 무결성 게이트 `GH_INTEGRITY` 항상 필수(오라클 강도·held-out 격차·조회 테이블·변조) | ADR-055 |
| D-043 | 결합 게이트 `GC_COMPOSITION`(wave 후보 ≥ 2) + 동시 변경 통지 | ADR-056 |
| D-044 | 차단 리뷰는 실행 가능한 증거 필수, advisory 상한 5, 리뷰어 정밀도 자격 | ADR-057 |
| D-045 | 후보 선택은 실행 증거 우선, 판정자 토너먼트는 동점에서만, adaptive k | ADR-058 |
| D-046 | 응집도 기반 분할(허브 wave 0, 응집도 ≥ 0.75, 예상 속도 ≥ 1.3) | ADR-059 |
| D-047 | 도구 투기 실행은 읽기 전용 5종만, 순서 커밋, 거짓 수락 0 | ADR-059 |
| D-048 | 캐시 배치 규칙 S11, 압축은 경계 단위 평가, 가역 접기는 TRIAL | ADR-060 |
| D-049 | 사람 라벨 지표에 PPI 허용, 안전 지표 금지 | ADR-061 |
| D-050 | 평가 위생: git 이력 제거, scaffold 동시 기록, 공급사 scaffold 점수 인용 금지 | ADR-061 |
| D-051 | M6 최적화기: GEPA 기준선, 구조화 패치, dev 선택, test 1회, 편집 예산 | ADR-061 |
| D-052 | 기술 채택은 레이더 등급·고리로 기록, 논문 수치는 예측 근거일 뿐 판정·주장에 쓰지 않음 | ADR-054~061 |
| D-053 | Python 오라클 분류·심볼 비교는 AST, 정규식은 대체 경로, 정확도는 dev/holdout 말뭉치로 측정·회귀 | ADR-062 |
| D-054 | 사람 라벨 holdout 200건 전까지 오라클 미달은 INCONCLUSIVE, 보상 해킹·변조는 항상 FAIL | ADR-062 |
| D-055 | 평가 샌드박스는 base 도달 객체만으로 재구성 + 7항목 감사, 점수는 scaffold 5필드 없이 기록 불가 | ADR-063 |
| D-056 | 압축 경계 판정 4조건(성공 비열등, 반복 탐색·막힌 행동 비율 상한 1.10, 불안정 증가 ≤ 5%p), 세션 ≥ 30 | ADR-064 |
| D-057 | M6 최적화 실행 상태 머신(OPEN→FROZEN→CLOSED) + `harness-patch/v1` 스키마 | ADR-065 |

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R50-1 | 출시 증거 패키지 | 체크리스트 각 항목에 증거 링크, 패키지에 커밋·이미지·하네스·모델·평가셋·정책 해시와 설계 수치/실측치 구분 포함 |
| R50-2 | 결정 변경 절차 | D-xxx 변경은 ADR 추가 + `contracts/vocabulary.json`·계약 갱신 + `tools/validate_package.py` 통과 후에만 반영 |
| R50-3 | 외부 근거 재확인 | 구현 착수·M4·M5 전에 아래 링크와 공급사 Registry를 다시 확인하고 날짜를 갱신 |

### 확인한 외부 근거(2026-10-25)
- Caveman: [LICENSING.md](https://github.com/JuliusBrussee/caveman/blob/main/LICENSING.md)(엔진 계열 BSL-1.1, 제3자 호스팅·멀티테넌트는 상용 범위), [engine.md](https://github.com/JuliusBrussee/caveman/blob/main/docs/technical/engine.md), [context-recovery.md](https://github.com/JuliusBrussee/caveman/blob/main/docs/technical/context-recovery.md)
- 공급사 캐시: [OpenAI](https://developers.openai.com/api/docs/guides/prompt-caching), [Anthropic](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), [Gemini](https://ai.google.dev/gemini-api/docs/caching)
- [LiteLLM 2026-10-21 사고 공지](https://docs.litellm.ai/blog/security-incident-oct-21-2026)(v1.107.0 PyPI·Docker·GHCR 배포물 침해, 1.106.2 이하 고정 권고)
- [MCP 2026-07-28 공지](https://blog.modelcontextprotocol.io/posts/2026-07-28/)(stateless, `Mcp-Method/Mcp-Name`, Tasks 확장, MRTR, Roots/Sampling/Logging 폐지 예고)
- [A2A 1.0 공지](https://a2a-protocol.org/dev/blog/2026/03/12/a2a-protocol-ships-v10-production-ready-standard-for-agent-to-agent-communication/)(2026-03-12, 서명 Agent Card, 다중 테넌트)
- [SWE-Bench Pro V2](https://labs.scale.com/blog/swe-bench-pro-v2)(2026-09-22, 642과제, reference/empty patch 양면 검사, 깨끗한 이미지 재채점)
- [ScholarEvolve 논문 arXiv:2609.40169](https://arxiv.org/abs/2609.40169)(2026-09-30; 수치는 논문 실험 결과이며 EvoForge 기준 아님)
- v4.2 마감 근거·측정값: `review/EvoForge_v4.2_Closure_Report.md`.
- v4.1 연구 근거(논문 33건 + 벤치마크 자료, 제목·제출일·등급·고리·반영 위치·수용 테스트): `research/Technology_Radar_2026-10.md`. 핵심: [Co-Coder 2606.00953](https://arxiv.org/abs/2606.00953), [Passes Alone, Fails Together 2609.25396](https://arxiv.org/abs/2609.25396), [SWE-Doctor 2607.00990](https://arxiv.org/abs/2607.00990), [Test-Time Compute for Agentic Coding 2604.16529](https://arxiv.org/abs/2604.16529), [Who Verifies the Builder? 2610.28667](https://arxiv.org/abs/2610.28667), [CR-Bench 2603.11078](https://arxiv.org/abs/2603.11078), [All Smoke, No Alarm 2606.18168](https://arxiv.org/abs/2606.18168), [SpecBench 2605.21384](https://arxiv.org/abs/2605.21384), [TomasuLLM 2609.38201](https://arxiv.org/abs/2609.38201), [Don't Break the Cache 2601.06007](https://arxiv.org/abs/2601.06007), [REM 2610.27377](https://arxiv.org/abs/2610.27377), [AutoSaddler 2608.23041](https://arxiv.org/abs/2608.23041), [RRSI 2609.24972](https://arxiv.org/abs/2609.24972), [PPI 2301.09633](https://arxiv.org/abs/2301.09633), [Prompt Injection SoK 2601.17548](https://arxiv.org/abs/2601.17548). 모두 2026-10-25에 초록·공개 페이지로 확인했고, 수치는 각 논문 설정의 결과다.
- 기타 참고(재확인하지 않음): AG-UI, A2UI, Temporal message passing, GitHub 보호 브랜치·Merge Queue, OpenTelemetry GenAI conventions, OWASP Top 10 for Agentic Applications 2026.

> **문서 끝 — 50/50.** 외부 링크·라이선스·가격은 구현 착수 시점에 다시 확인한다.
