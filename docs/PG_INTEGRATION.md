# PostgreSQL 지원 통합 상태

`codex/pg-integration`은 `commands-persistence`와 `runner-core-evidence`를 모두 포함한다.
각 브랜치의 DB 테스트·환경 설정을 보존해 합쳤고, 상위 round7 `d347b56`이 먼저 main에 반영된 뒤 동기화했다.
향후에는 이 통합 브랜치를 기준으로 이어간다. 정본 `docs/evoforge-v4.2/`는 변경하지 않았다.

## 실제로 연결한 내부 경로

- 정본 `core.accept_command` → 단일 dispatch → 서버 증거와 일치하는 완료 응답 → 별도 API 프로세스 조회.
- 응답의 evidence FK와 command_id/candidate/gates 비교. 앱 SQL의 상태만 APPLIED인 커밋도 지연 제약으로 거부한다.
- core_app 세션 역할과 RLS를 유지한 완료 커밋. 증거 테이블에 UPDATE 권한을 추가하지 않는다.
- 정산된 Builder 바인딩·현재 fencing·커밋 head의 실제 로컬/번들 Runner 결과 → core G2_REQUIRED.
- Google ID 인증과 내부 커널 토큰을 각각 검사하는 HTTP 전달. 잘못된 명시 헤더는 대체하지 않는다.

클라이언트가 보낸 실행 수나 모델 JSON만으로 게이트를 만들지 않는다.
다른 필수 게이트·독립 리뷰·승인은 누락 상태를 유지하며 `core.authorize_merge`의 거부를 확인한다.
비용 UNKNOWN을 자동 환불하거나 이미 dispatch한 모델 호출을 다시 실행하지 않는다.

## 검증 증거

API **463 passed·1 skipped**, 실제 PostgreSQL **107 passed**, 인증 경계 **35 passed**(전체 API 집계에 포함),
참조 **112개**·SQL **96개**·패키지 검사와 round7 웹 프로덕션 빌드가 통과했다.
최종 로그·source SHA-256은 `docs/validation/2026-10-27-pg-integration.json`을 따른다.
실제 PostgreSQL과 실제 Python/번들 Runner를 사용한다. Critic·영수증·image 식별자는 명시적 합성 fixture다.
Google 인증 연동 테스트의 서명 검증기는 fixture로 대체하므로 실 Google IAM 검증 완료를 뜻하지 않는다.
배포 이미지 빌드는 Docker가 없어 수행하지 않았고, 실제 Muse 호출·운영 DB 마이그레이션·GCP 배포는 이 검증 범위 밖이다.

확장 004는 신설 테이블·반복 적용을 검증했다. 이전 미배포 초안의 응답에 서버 증거가 없으면 스키마 보강을 거부하며,
불변 응답을 수정하거나 증거를 생성해 맞추지 않는다.

## 남은 공개 경로와 운영 연결

공개 Generate와 mission은 현재 메모리 명령·추정 원장을 사용한다. 내부 HTTP 명령 경로는 항상 PostgreSQL을 사용한다.
`EVO_STATE_BACKEND=postgres`의 기존 증거 저장과 새 내부 명령 API가 공개 전체 파이프라인의 영속화를 뜻하지 않는다.
따라서 P0-2와 전체 개발은 계속 미완료다.

후속 Muse T22가 같은 main 파일을 편집 중이다. 그 작업이 먼저 반영된 뒤 다음을 이어간다.

1. `commands.py` backend 위임과 명시적 dispatch/완료를 공유 `_generate_core`·mission 생성 단계에 연결한다.
2. 공개 HTTP의 재전송·동시 요청·실패·DB 복구·재시작을 새 경로에서 검증한다.
3. 실제 Builder/독립 Critic 호출의 패킷·가격표·예약·정본 영수증과 공개 비용 원장을 연결한다.
4. canonical 후보 생성·다른 게이트/리뷰/승인·0원과 청구 정정 정책, mission/측정 상태와 운영 배포를 대조한다.

Muse Spark `muse-spark-1.3` 기본값과 자동 모델 대체 금지는 유지한다.
