<!-- PAGE:49/50 -->

# 49. 마일스톤 로드맵

> **목적:** v3.x에 흩어져 있던 6가지 단계 체계를 하나의 사다리로 합치고, 목표 달성에 유리한 순서로 재배열한다. · **결정:** D-035, D-020, D-036, D-042, D-046, D-051, D-054, D-055 · **계약:** `build/CLAUDE_CODE_BUILD_PROMPT.md`

### 재배열의 근거
1. **증명 수단이 기능보다 먼저다.** 10X·비용 절감을 판정하려면 X_SINGLE 기준선과 봉인 평가 세트가 먼저 있어야 한다 → M0에 넣는다.
2. **압축은 기준선 이후.** A_RAW 실측 없이 codec을 만들면 절감을 증명할 수 없다 → codec은 M3.
3. **플랫폼 키는 과금 안전이 선행 조건.** 예약·하드캡·원장 없이는 첫 외부 호출도 하면 안 된다 → M0.
4. **연구 루프는 GA 이후.** trace 양과 봉인 평가 인프라가 쌓여야 의미가 있다 → M6.
5. **연동 표준을 전부 먼저 만들지 않는다.** MCP·Folder는 M2, A2A는 M4.
6. **거짓 성공을 막는 장치는 첫 병합 전에.** `GH_INTEGRITY`·차단 리뷰 증거·평가 위생은 성능 기법이 아니라 측정의 전제다 → M0. 결합 게이트는 병렬 후보가 처음 생기는 M2와 함께.
7. **분류기를 쓰기 전에 분류기를 잰다.** 오라클 분류기의 사람 라벨 holdout을 M0에 200건 이상으로 늘려야 오라클 미달이 INCONCLUSIVE가 아니라 FAIL이 된다(D-054). 라벨 작업은 X_SINGLE 기준선 측정과 함께 한다.
8. **속도 기법은 측정 가능한 순서로 하나씩.** 분할·선택(M2) → 투기·cascade·접기(M3) → 최적화기(M6). 한 번에 켜면 어떤 기법이 이득을 냈는지 구분할 수 없다.

### 사다리
| 마일스톤 | 범위 | Exit 기준 |
|---|---|---|
| **M0 Foundation** | GitHub App, 플랫폼 키 Broker(공식 SDK, KMS, 공정 큐), core·ctx 스키마, 예약·원장, microVM Runner POC, Evidence Vault(RAW만), 결정적 게이트 G0–G4·GR + **GH_INTEGRITY**(오라클 강도·held-out·변조), 차단 리뷰 증거 CHECK, 봉인 평가 세트 v0(held-out compositional·negative 포함, base 도달 객체만으로 재구성한 샌드박스) + X_SINGLE 측정 하네스 + 오라클 분류기 사람 라벨 holdout ≥ 200건, 공급사 약관·DPA 확인 | 로그인 → 저장소 → 1좌석 → 격리 실행 → 검증 PR; SQL 96개 검사·validator CI 통과; X_SINGLE 기준선 측정 완료(scaffold 기록) |
| **M1 Private Alpha** | 2좌석 SINGLE(builder + 독립 critic), Review Coverage(RAW), 기본 Mission Control, Command fast lane, 선결제 크레딧(테스트 결제), receipt 대사 | 외부 3팀 검증 PR; 안전 불변식 위반 0; 청구 = 원장 = receipt |
| **M2 Closed Beta** | 5좌석·5토폴로지, Lease·fencing, **응집도 분할 + GC_COMPOSITION + 동시 변경 통지**, **실행 증거 우선 선택 + adaptive k + 다면 재현 테스트**, MCP(지원 클라이언트 1+), Folder Bridge, Feedback 폐쇄 루프, SSE 동기화, 리뷰어 자격 시험(정밀도 포함) + `reviewer_qualifications`, HIGH/CRITICAL 명세 선행 verifier | X_ADAPTIVE5 vs X_SINGLE: 품질 Tier A 비열등 + 안전 0 + 속도 비율 하한 ≥ 1.5(동일 시간); 각 v4.1 기법의 절제(ablation) 결과 보고 |
| **M3 Context Efficiency** | 결정적 codec(JUnit/Jest·JSON·로그), Fidelity Gate, Cache Planner + namespace 솔트 + S11 배치, Registry probe, arm B/D/E, codec 런타임 감사, **읽기 전용 투기 실행, 보정 cascade, 가역 접기(경계 단위 평가), 단계 기억 회상**, PPI 라벨 추정 | 채택 codec·기법이 Tier A 통과 + 비용 비율 상한 < 1.0; 투기 불일치 0; 런타임 감사 가동 |
| **M4 Public Beta** | A2A Gateway, 실결제·정산, 자동 병합(LOW·옵트인), 공정성 부하 시험, 외부 침투 시험, DR 훈련, 문서·SDK | SLO 충족; 보안·법률·운영 Go |
| **M5 GA** | 세금·환불·영수증, 지원 체계, 가격 검증, 증거 attestation(in-toto/Sigstore), Tier B 판정 | 속도 비율 하한 ≥ 3.0(동일 시간·동일 비용 모두 보고); 기본값 codec·토폴로지 Tier B 통과; p.50 전체 체크 |
| **M6 Post-GA** | Harness Research Loop(OFF → SUGGEST → EVALUATE → CANARY), GEPA 기준선 최적화기 + 구조화 패치 + 편집 예산 annealing, 연구 스키마, 분기별 기술 레이더 재검토, Enterprise(SSO/SCIM, 전용 Runner, BYOK 재검토) | 하네스 승격이 Tier A/B 규칙으로만 이뤄짐; `D_test` 1회 사용 원칙 위반 0 |
일정은 팀 규모에 따라 달라지므로 확정 납기가 아니다. 각 마일스톤은 Exit 기준을 통과하기 전에는 다음으로 넘어가지 않는다. 기능 데모가 아니라 모델·보안·과금·운영·문서의 수용 기준을 모두 봐야 한다.

### 역할(초기 권장)
Backend/Workflow, Frontend/Realtime, Cloud/Security/DevOps, AI Integrations/Quality(평가 하네스 포함), Product/Design, QA, 법률·개인정보 자문. 인원이 적으면 서비스별 소유자를 정하고 M2 이후 기능을 미룬다. 착수 전에 기존 Autonomous AI Collective 소스를 실사해 이 명세와 충돌하는 부분을 목록화한다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R49-1 | 단계 통제 | 마일스톤 승격마다 Exit 기준 증거 패키지(커밋·이미지·하네스·모델·평가셋·정책 해시) 보관 |
| R49-2 | 측정 선행 | M2 판정에 쓰는 X_SINGLE 기준선이 M0에 봉인됨 |
| R49-3 | 실행 프롬프트 | `build/CLAUDE_CODE_BUILD_PROMPT.md`의 Phase가 이 사다리와 1:1 대응 |
| R49-4 | 기법별 귀속 | M2·M3에서 켠 v4.1 기법마다 단독 절제 실험 결과(Tier A 판정)가 있고, 이득이 확인되지 않은 기법은 기본값에서 제외 |
| R49-5 | M0 측정 준비 | 오라클 분류기 사람 라벨 holdout ≥ 200건, 평가 샌드박스 감사 통과율 100%가 M0 Exit 증거 패키지에 포함 |

---
