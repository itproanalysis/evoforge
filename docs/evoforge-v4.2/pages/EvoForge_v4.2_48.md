<!-- PAGE:48/50 -->

# 48. 과금 엔진·원가·지원 콘솔

> **목적:** 플랫폼 키 구조에서 청구·원가·정산을 원장 하나로 맞춘다. · **결정:** D-019, D-034, D-040 · **계약:** `contracts/sql/core_DRAFT.sql`(`usage_ledger`, `cost_reservations`), `contracts/schemas/provider-usage-receipt.v1.schema.json`

### 흐름
`reserve_cost(보수적 최대치)` → 공급사 호출 → receipt(`cost_micros` = 공급사 원가, `customer_price_micros` = 고객 가격, `price_table_version`, `call_purpose`, 원본 usage 필드) → `settle_reservation`(예약 COMMITTED + 원장 `model_usage` 차감, 같은 트랜잭션) → 일일 공급사 청구서 대사. 남은 예약은 `RELEASED`. 실제가 예약을 넘으면 `overrun`으로 표시하고 추정기를 교정한다.

### 원장(`core.usage_ledger`)
- 종류: `credit_purchase`, `credit_grant`, `model_usage`, `runner_minutes`, `storage`, `subscription_fee`, `adjustment`, `refund`. 고객 관점 부호(크레딧 +, 사용 −)를 CHECK로 강제한다.
- append-only. 정정은 `adjustment` 역분개로, 원래 금액을 정확히 상쇄하고 한 번만 가능하다. `UNIQUE(tenant, idempotency_key)`.
- 잔액 = 원장 합계(`credit_balance`). 예약 가능액 = 잔액 − 열린 예약.
- 모든 금액은 정수 micro-USD. 표시 통화 환산은 표시 계층에서만 한다.

### 원가 분해
`provider uncached input`, `cache write/read`, `output`, `call_purpose`(task_turn / retrieval_turn / review_chunk / review_cross_chunk / rerun / probe), Runner CPU·메모리·시간, Object Storage 보관·전송, 재평가 Runner. 취소된 작업의 잔여 컴퓨팅 비용도 보인다. `net_savings`는 대응하는 기준군(A_RAW 실측) 없이 마케팅에 쓰지 않는다.

### 결제
국내 PG와 글로벌 구독 결제 대행을 비교해 결제 실패·카드 저장 책임·VAT·영수증·정기결제·환불 API·국가 지원을 검증한다. 하나의 결제 수단을 모든 국가에 강제하지 않는다. PG 웹훅 중복·역순·환불·부분 환불·무료 한도 이월은 계약 테스트로 확인한다.

### 수익성 지표와 콘솔
조직별 Gross Margin(모델 마크업 포함), 모델 원가율, Runner minutes per WVI, 저장 원가, 지원 비용, 실패 Job 재실행 비용, 크레딧 소진 속도. 고원가 고객은 자동 차단 전에 예산 경고와 단계 축소를 제안한다. 관리 콘솔: 플랜·계약·승인 정책·사용량·실패 Run·청구·환불·공급사 이상·키 회전·사고 조치. 동일 비용·동일 시간 비교 리포트를 고객용으로 생성한다.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R48-1 | 중복 청구 0 | 웹훅 중복·정산 지연 재현 시 최종 청구 = 원장 합계 |
| R48-2 | 원장 무결성 | 수정·삭제 불가, 역분개 규칙 (C-14) |
| R48-3 | 대사 | receipt 합계와 공급사 청구서 일일 대사, 차이 원인 분류 |

---
