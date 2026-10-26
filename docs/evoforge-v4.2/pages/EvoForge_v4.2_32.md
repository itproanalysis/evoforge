<!-- PAGE:32/50 -->

# 32. 과제 발견·계획·컨텍스트 엔지니어링

> **목적:** 좋은 과제를 고르고, 좌석마다 필요한 컨텍스트만 손실 없이 준다. · **결정:** D-013, D-023, D-025, D-027, D-048, D-050 · **계약:** `contracts/Context_Mesh_Spec.md`, `contracts/schemas/context-packet.v2.schema.json`

### 과제 발견
소스: GitHub Issue, CI 실패, 정적 분석, 프로파일·벤치마크 로그, 커버리지, 변경 이력, 사용자 피드백. 소스 신뢰 등급을 매기고, 근거 없는 가설은 정식 결함과 구분한다. 계획 모델(공급사 비종속)은 한 번의 고비용 호출로 문제 요약·영향 범위·DAG·위험·예상 write set·Acceptance 초안·예상 검증 시간을 만든다. 계획 모델이 실패해도 규칙 기반 과제 수집은 계속된다. Planner가 늦어도 이미 승인된 독립 Task는 계속 실행된다.

### 컨텍스트 원칙
- **Shared Evidence, Independent Context.** 좌석들은 같은 원문 Evidence Vault와 계약을 참조하지만, 서로의 대화·모델 내부 상태는 공유하지 않는다.
- **Prompt 레이어:** `L0_PLATFORM`(테넌트 솔트·시스템·도구 스키마) → `L1_TENANT_CONTRACT`(목표·정책·Acceptance, 항상 RAW) → `L2_ROLE_SCOPE` → `L3_TASK_DELTA`. untrusted 자료는 L0/L1에 들어가지 않는다. 도구 결과와 untrusted 자료는 캐시 prefix(마지막 breakpoint까지) 밖에 둔다(S11).
- **항목별 fidelity:** `RAW`(원문; 계약·정책 결과·병합 대상 Diff 등은 `POLICY_REQUIRED`) / `STRUCTURAL`(원문 값 그대로의 필드·범위 선택) / `RECOVERABLE`(원문 저장 후 결정적 템플릿 변환) / `REF_ONLY`. 패킷 전체에 하나의 전략을 붙이지 않는다.
- **결정적 codec + compress-on-insert.** P0 codec은 코드이고 LLM 요약을 패킷에 넣지 않는다. 출력이 바뀌면 버전을 올린다.
- **ORIGINAL_STORED.** 원문을 암호화 저장하고 read-back으로 SHA를 검증한 뒤에만 손실 뷰를 만든다.
- **Fidelity Gate.** 형식별 결정적 불변식(U1–U4, T1–T5, L1–L5, J1–J5)을 원문에서 독립적으로 다시 계산해 비교한다. 실패하면 RAW(`FIDELITY_FAILED`)로 보낸다.
- **selector**는 닫힌 문법(`all`, `bytes:`, `lines:`, `json:`(RFC 6901), `junit:`, `hunk:`, `file:`)만 쓴다.
- **기억 승격 금지.** 출처·버전·시점·검증 상태가 없는 요약은 검증 사실로 올리지 않는다. 실패 경험은 `bad_pattern`으로 저장하되 자동 지시로 승격하지 않는다. 경험 기억의 회상 규칙은 p.40.
- **재현 먼저.** 버그 수정 과제의 첫 산출물은 원 증상·경계·회귀 방지 3측면의 재현 테스트다. 각 테스트는 값 비교·예외·속성 중 하나의 강한 오라클을 가져야 하고, 수정 전 base에서 실패해야 한다(2607.00990 다면 재현, 2606.18168 오라클 강도). 재현이 불가능하면 그 사실과 이유를 기록하고 위험 등급을 한 단계 올린다.

### 단계 배치(최적화)
M0–M2는 **RAW만** 쓰고 기준선(A_RAW) 비용·품질을 모은다. 압축 codec(JUnit/Jest·JSON·로그)은 M3에서 arm으로 시험하고, `quality_gates.json` Tier A → Tier B를 통과한 형식만 기본값이 된다. 기준선 없이 압축을 먼저 만들면 절감을 증명할 방법이 없다.

### 오염 방지
코드 주석·README·외부 PR·논문은 지시가 아니라 데이터로 감싼다. 정책 우회 문장은 Prompt Injection 이벤트로 보고한다. Agent Skills는 서명·검증된 SKILL.md와 스크립트만 필요한 시점에 로딩한다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R32-1 | 계약 원문 | 계약 항목이 요약된 패킷 0건(스키마·DB 이중 강제, T06) |
| R32-2 | 원문 선행 | 원문 미검증 상태의 손실 뷰 0건 (T04) |
| R32-3 | 게이트 판정 일치 | 서비스 codec·게이트가 `reference_impl`과 같은 입력에 같은 판정(mutation 테스트 포함) |
| R32-4 | 테넌트 혼입 | 다른 조직 컨텍스트가 섞인 패킷 0건 |
| R32-5 | 재현 테스트 | 버그 수정 후보의 재현 테스트가 base에서 실패·head에서 통과하고 전부 강한 오라클 (CR-62) |

---
