# Muse Spark의 직접 API capability 사전 검증

Meta의 [프롬프트 캐싱 문서](https://dev.meta.ai/docs/prompt-caching)와
[사용 예제](https://dev.meta.ai/docs/cookbook/prompt-caching)를 2026-10-27에 확인했다.
별도 capability 입력은 `meta/muse-spark-1.3`의 Meta 직접 API에서 자동 캐싱이 사용된다고 기록한다.
캐시를 끄는 방법과 명시적 breakpoint는 확인하지 못했으므로 두 기능을 허용하지 않는다.
최소 토큰 수와 가격 배수는 확인된 값이 없어 `null`이다.

`PreflightCallBroker`는 Meta `https://api.meta.ai/v1`을 사용하는 해당 모델에 한해 이 입력을
정본 capability schema로 검사하고 독립된 정본 semantic validator 인스턴스에 추가한다.
정본 seed와 공유 validator는 수정하지 않으며 S1–S11 전체를 그대로 실행한다.
다른 서버·프록시·모델에는 이 capability를 적용하지 않는다.
패킷의 검증일은 입력의 실제 검증일과 일치해야 하며 서버 UTC 날짜 기준으로 미래 날짜나
14일 초과 자료는 거부한다. 만료되면 공식 문서를 다시 확인하고 근거와 검증일을 갱신해야 한다.

이 연결은 독립된 사전 검증 모듈의 범위다. 공개 Generate/mission의 canonical Broker 및
PostgreSQL 비용 경로에는 아직 연결되지 않았고 실제 Muse 호출·청구 검증이나 Docker 이미지 실행은
이 변경으로 완료된 것이 아니다. 사용자 승인 없는 다른 모델 대체는 하지 않는다.
