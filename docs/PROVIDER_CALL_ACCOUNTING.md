# Muse Spark 호출 경계와 비용 예약

2026-10-27. 고정 SDK `openai==1.57.0`의 기본 재시도 2회와, Critic의 두 HTTP 호출을
하나의 예약으로 처리하던 경로를 보강했다. 메인 모델은 `muse-spark-1.3`으로 유지했다.

## 반영한 동작

- API와 개발 Builder CLI의 공용 Meta 클라이언트는 `max_retries=0`을 사용한다.
  429·5xx·timeout을 SDK가 자동 재전송하지 않는다.
- 실제 Critic 요청의 Phase A·B는 각각 별도 예약 후 호출하고 성공한 호출을 각각 정산한다.
  현재의 정수 추정치로는 호출당 120 cents다. 공급사 확정 청구 금액은 검증하지 않았다.
- Phase A 성공 후 B가 401/429로 거부되면 A의 지출은 남고 B만 환불한다.
  B가 timeout/5xx이면 B의 예약은 UNKNOWN으로 남는다.
- B의 예산이 부족하면 두 번째 HTTP 요청을 보내지 않는다.
- Phase A가 빈 값·잘못된 테스트 목록을 반환하면 B를 호출하지 않고 INCONCLUSIVE를 반환한다.
- B의 모델 JSON은 A에서 얻은 테스트를 바꾸지 못한다. 리뷰에는 `execution_verified=false`를 기록한다.
  실제 테스트 실행은 Runner 연결 과제로 남아 있다.
- 호출마다 예약 상태·공급사 메타데이터·SDK 응답 문서를 서버 Evidence에 기록한다.
  B가 실패해도 A의 테스트 응답과 지출 근거를 보존한다.
- 단독 Critic 함수도 A 이후 실패를 전체 미접수로 취급하지 않는다.
  `ProviderOutcomeUnknown.completed_calls`에 이미 완료된 호출 메타데이터를 남긴다.

## 메타데이터와 오류

SDK가 받은 `x-request-id`와 completion ID를 각각 `provider_request_id`, `provider_response_id`로 구분한다.
모델 JSON에 적힌 request ID·usage·billing 표시는 신뢰하지 않고 서버 값으로 교체한다.
이 메타데이터는 `billing_verified=false`이며, 가격표·패킷·예약을 갖춘 정식 사용 영수증을 대체하지 않는다.

공급사 오류 본문은 사용자 응답과 변환된 예외 traceback에 전달하지 않는다.
잘못된 Builder 출력도 테스트 증거를 비우고 게이트를 차단하며, 이미 호출한 비용은 보존한다.

## 검증

```powershell
& '.\.local\venv-api\Scripts\python.exe' -m pytest services/api/tests -q
```

기존 API 93개와 신규 23개를 합한 **116개**가 통과했다.
최종 호출 Evidence 응답 문서 추가 후 관련 23개도 다시 통과했다.
DB 테스트 모듈은 `EVO_TEST_DATABASE_URL`이 없으면 skip하며, 실제 DB 검증은 [별도 절차](POSTGRES_KERNEL.md)로 실행한다.
신규 검사는 실제 고정 SDK와 `httpx.MockTransport`를 사용해 요청 수·메시지·오류·메타데이터를 확인했다.
실제 Meta API 호출이나 비용 청구를 실행하지 않았다.

## 남은 작업

FastAPI의 원장은 현재 메모리의 추정 원장이다. 인증 컨텍스트·패킷·정식 영수증과
PostgreSQL 어댑터를 요청 경로에 연결해야 한다.
개발 CLI에도 프로젝트 예산·영수증 연결이 남아 있다. 이를 플랫폼 비용 통제가 완료된 경로로 간주하지 않는다.
