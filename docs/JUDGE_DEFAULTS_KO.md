# 심사용 기본 협업 설정

2026-10-31 사용자 승인: 심사자는 API 키를 입력하지 않고 실행한다.
GPT·Gemini·Claude도 실제 기본 협업 경로에 참여한다.

| 역할 | 기본 모델 | 실제 입력 |
|---|---|---|
| 구현 | Muse Spark 1.3 | 원래 계약·기준 파일·미검증 계획·독립 Critic 피드백 |
| 구현 계획 | GPT-6.1 Sol | 원래 계약·기준 파일 |
| 구현 계획 | Gemini 4 Argon | 원래 계약·기준 파일 |
| 독립 검증 | Claude Opus 5.5 | 원래 계약, 이후 단계에서 패치·실행 결과 |

Planner는 최종 채점용 테스트·정답·실패 이름을 받지 않는다.
Critic은 Builder의 대화·자기평가·Planner 계획을 받지 않는다.
두 Planner는 라운드당 한 번 호출하며 Builder 재시도에도 계획을 재사용한다.
검증·Runner·병합 승인은 기존 서버 경로를 통과한다.

키는 Secret Manager에서 API 서비스 계정에만 제공한다. 웹·Runner·빌드 인자·
응답·로그·브라우저 저장소에 넣지 않는다. 공개 `GET /v1/models/defaults`는
모델 이름·역할·설정 여부만 반환한다. 키 존재 여부가 실제 연결 성공 증명은 아니다.
잘못된 프로필·키 누락·필수 공급사 실패는 작업을 차단하며 다른 모델로 대체하지 않는다.

서버 기본 배포 프로필은 `EVO_MODEL_PROFILE=collaborative`다.
`MODEL_BUILDER=muse-spark-1.3`, `MODEL_CRITIC=claude-opus-5-5`로 고정한다.
OpenAI·Anthropic·Gemini 키는 각각 명시한 Secret Manager 버전을 참조한다.
기존 일일 20회·웹 POST 분당 20회 제한과 예산 검사를 유지한다.
단일 AI 비교 차선은 Spark 단독 호출이며, 비교 명세에 다중 모델 구성을 공개한다.
Muse Wonder Full은 공개 API에 없으므로 기본 구성에 포함하지 않는다.

유료 모델 호출마다 먼저 예약하고 사용량으로 정산한다. 명확한 접수 거절만
환불하고 타임아웃·사용량 누락은 UNKNOWN 예약으로 보존한다. Claude 두 단계도
별도 예약한다. 앞 단계가 성공한 뒤 다음 단계가 실패해도 이미 발생한 비용을 유지한다.
네이티브 reasoning 토큰은 출력 사용량에 한 번만 포함한다.

검증된 실제 로컬 실행에서 네 모델의 응답을 모두 확인했고, 실제 Runner의
타입·양수·음수·0 테스트를 통과했다. 비용 8¢, 미결 예약 0¢다.
이는 클라우드 실행을 대신하는 증거가 아니며 배포 후 키 없는 웹 실행을 별도 확인한다.
근거는 `docs/validation/2026-10-31-judge-real-model-smoke.json`이다.

배포는 검사를 통과한 커밋의 깨끗한 release 작업 트리에서만 한다.
장애 시 같은 배포 스크립트의 `MODEL_PROFILE=legacy`로 명시적으로 되돌릴 수 있다.
새 기본 구성으로 조용히 대체하거나 실패한 모델을 다른 모델로 숨기지 않는다.
해커톤의 최종 제출은 수행하지 않는다.

## 2026-10-31 운영 검증 완료 — 심사용 네 모델 기본값

깨끗한 `release/2026-10-31-judge`의 `b832086f`를 Cloud Build
`1c5aba8d-923e-4b1c-aea9-57858af1dd8a`에서 검증 후 배포했다. Linux 전체 API
1404 passed / 65 skipped, 실제 PostgreSQL kernel169, 정본 검사0 failures,
웹 npm ci·TypeScript·Next build·프록시147·SSR162 검사를 통과했다.
최신 release31-2 UI를 포함하며 다른 작업의 main 미커밋 파일은 보존했다.

API `evoforge-api-00052-qlh`, Web `evoforge-web-00050-rhw`, Runner
`evoforge-runner-00041-pcc`가 각각100% 트래픽을 받는다. GPT·Gemini·Claude
키는 Secret Manager 버전1에서 API에만 전달한다. 기존 일일20회·POST 분당20회를 유지했다.

키·로그인 없는 웹 요청 `job_306819b0b688`에서 Spark 구현, GPT·Gemini 계획,
Opus 검증이 실제 참여했다. 두 차선 모두 held-out13/13 통과; 모델 API 비용은
단일3¢ + 협업10¢ + 공통 Judge13¢ =26¢다. Runner 비용과 공급사 청구서 대사는 포함하지 않는다.
PostgreSQL의 Planner 영수증 두 건은 SETTLED, 원격 Runner HTTP200 요청13건,
공유·검증 페이지 HTTP200과 Ed25519 서명 유효를 확인했다. 한 번의 실행은 우위나 지능 순위의 증거가 아니다.
기존 Critic 진행 이벤트의11/4는 snippet그룹 분모 문제이며 최종 held-out 판정13/13과 구분한다.

- 사이트: https://evoforge-web-230852112787.asia-northeast3.run.app/ko
- 실행: https://evoforge-web-230852112787.asia-northeast3.run.app/ko/share/job_306819b0b688
- 검증: https://evoforge-web-230852112787.asia-northeast3.run.app/ko/verify/job_306819b0b688
- 근거: `docs/validation/2026-10-31-judge-live-defaults.json`

첨부 개선제안서는 참고 자료다. Meta 오픈웨이트 Critic 제안은 최신 사용자의 Opus 선택보다 우선하지 않는다.
방문자별 쿼터, SEC02 추가 격리, 외부 OSS PR, 영상은 별도 남은 작업이며 완료로 표시하지 않는다.
영상은 사용자가 나중에 추가 결제 없이 녹화하기로 했고 최종 제출은 하지 않았다.
서버 오류 이메일은 과거 GitHub CI 실패·취소 알림이었다. npm11 수정과 이번 Linux 전체 검증은 통과했으며
과거6시간 hang의 정확한 원인은 확정하지 않았다. 새 CI는 시간 제한·스택·로그 수집을 추가했다.
