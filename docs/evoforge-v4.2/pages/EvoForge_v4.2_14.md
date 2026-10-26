<!-- PAGE:14/50 -->

# 14. 목표 계층 — 목표부터 코드까지

> **목적:** 목표·측정·작업·결과를 하나의 인과 그래프로 묶는다. · **결정:** D-008, D-036 · **계약:** —

### 도메인 구조
`Vision → ObjectiveVersion → Key Result(OutcomeMetric) → Initiative → Task → Candidate → Gate/Review → PR → Outcome`. 피드백은 Objective와 Task 양쪽에 연결된다. 연구 그래프(`CapabilityGap → Method → HarnessVariant → Evaluation → Promotion`)는 별도 그래프이며, 연구 제안·승격은 고객 진척 성과가 아니다.

### 목표 작성
자연어 목표 → 계획 모델이 측정안을 제안 → 사용자가 기준선·단위·허용 범위·가중치를 정함 → 버전 확정. KR은 `측정 대상·기준 기간·데이터 소스·검증 책임·성공 조건`이 없으면 확정하지 않고 `측정 불가`로 둔다. 범용 응답량·코드 라인 수·회의 발언량은 성과 점수에 넣지 않는다.

### 진척 3단 분리
- **Activity:** 예정 Task 대비 완료(계획 변경 시 분모 버전 표시).
- **Validation:** 통과한 필수 Acceptance 수 / 전체.
- **Outcome delta:** `{metric, unit, baseline, candidate, direction, environment_hash, sample_count, confidence_interval, measurement_status}`. `PR 검증됨`과 `고객 효과 검증됨`(배포 후 측정)을 구분하고, 병합 후 Outcome 측정을 예약한다.

### 계획 변경 영향 분석
우선순위 변경 시 중단될 작업, 이미 쓴 비용, 재검증이 필요한 후보, 새로 예약할 파일을 미리 보여준다. 이전 목표와 검증 기록은 `goal_version`으로 영구 보존한다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R14-1 | 역추적 | 개선 결과 하나에서 목적·요청자·AI 결정·SHA·CI 실행·실측 지표를 모두 조회 |
| R14-2 | 가중치 고정 | 작업 시작 후 가중치·성공 조건 변경 시 새 ObjectiveVersion이 생성되고 기존 결과는 재계산되지 않음 |
| R14-3 | 측정 불가 처리 | KR 필수 필드가 빠진 목표는 실행은 가능하되 WVI 가중치 1로 고정, 화면에 표시 |

---
