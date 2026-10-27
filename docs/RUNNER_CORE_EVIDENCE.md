# Runner 실행 증거와 canonical 후보 연결

`/v1/kernel/candidate-runs`는 서버에 저장된 Runner 결과를 기존 `core.candidates`와
`core.gate_results.G2_REQUIRED`에 원자적으로 연결한다. 정본 SQL과 병합 승인 함수는 수정하지 않는다.
공개 Generate/PR 경로 전체의 canonical 전환이나 운영 적용 완료를 뜻하지 않는다.

## 입력과 처리

확장 001–003과 `005_runner_candidates.sql`을 순서대로 적용한다. 명령 확장 004는 별도 기능이다.
내부 경로는 기존 서비스 토큰과 서버 소유 tenant/project 범위를 사용한다.
요청은 `candidate_id`, `call_id`, `evidence_id`만 받으며 scope·head·policy·결과·image 덮어쓰기는 422다.

1. 후보는 trusted controller가 이미 만든 core 행이어야 한다. Builder 호출은 해당 task/author의
   사전 바인딩과 정본 영수증 정산(`COMMITTED`/`CONFIRMED`)을 요구한다.
   현재 패킷·동의·모델·task lease/fencing·기준 SHA도 재검증한다.
2. 실제 커밋된 후보 head를 `base_sha`로, 빈 diff와 서버 소유 리뷰의 봉인 스위트로 다시 실행한다.
   이전 base에 diff를 적용한 실행은 결과 트리의 Git commit SHA를 증명하지 못하므로 이 경로에서 거부한다.
   tree hash나 임의 digest를 head SHA로 대체하지 않는다.
3. 저장된 실행에는 Candidate/Gate 단계, 참조된 비-stub 리뷰에는 Review 단계가 필요하다.
   실행 입력·결과 해시, 실제 resolved base, visible 코드·봉인 원본·kind와 배포 식별자를 대조한다.
4. 수집 수·성공 수·timeout·exit code를 검사해 G2_REQUIRED만 산출한다.
   빈/누락 스위트, 정의 수보다 적은 수집, 실패·skip·timeout·비정상 종료는 PASS가 아니다.
   scope·integrity·composition·review·merge-head 게이트와 독립 리뷰·승인은 이 기능이 생성하지 않는다.

후보 상태를 바꾸거나 `core.authorize_merge`를 우회하지 않는다. 다른 필수 게이트가 없으면 병합 승인은 계속 거부된다.
과거 성공 응답 재전송은 기존 gate id를 반환하며 이후 실패 결과를 덮는 새 PASS를 만들지 않는다.
DB 오류는 두 행을 모두 롤백하고 503으로 거부한다. 비용 예약·영수증을 환불하거나 모델을 재호출하지 않는다.

읽기 경로: `GET /v1/kernel/candidates/{candidate_id}/runner-evidence/{evidence_id}`.
원본 봉인 코드는 반환하지 않으며 다른 scope와 없는 id는 동일한 404다.

## Runner 식별자와 해시의 경계

API와 실제 Runner에 `EVO_RUNNER_IMAGE_DIGEST=sha256:<64 lowercase hex>`를 같은 승인된 빌드 digest로 설정한다.
배포 설정은 운영자가 실제 배포 artifact와 대조해야 한다. 이 값은 자동 측정이나 서명된 attestation이 아니다.
신뢰된 Runner 전송·서비스 권한과 서버의 append-only 증거 저장이 함께 필요하다.
해시만 일치하는 클라이언트 JSON을 실행 증명으로 받지 않는다.

Runner는 실행 전에 입력 식별자를 고정하고 실행 결과에 해시를 붙인다.
격리 Runner 이미지에는 stdlib 전용 해시 모듈 하나만 추가하며 API 런타임·비밀은 포함하지 않는다.
원격 클라이언트는 설정된 image/해시가 없거나 다르고, 성공 수가 전체를 초과하거나 hygiene가 실패하면 502로 거부한다.
식별자 미설정 시 기존 개발 실행은 유지되지만 canonical 증거 연결의 신규 기록은 503으로 거부한다.

원격 클라이언트는 base ref를 실제 Git 커밋으로 한 번 해석한 뒤 그 커밋으로 bundle을 만들고
Runner 요청에 전달한다. 임시 원격 checkout의 HEAD가 요청한 SHA와 다르거나 Runner 응답의 base가
보낸 커밋과 다르면 실행 증거를 반환하지 않는다. 이 비교는 Runner가 실행한 내용을 독립적으로
증명하는 서명이 아니므로 신뢰된 Runner 전송과 별도 attestation 검사는 여전히 필요하다.
임시 bundle의 참조가 이미 존재하면 그 참조를 건드리지 않는다. 생성한 참조가 다른 커밋으로 이동하면
bundle을 거부하고 해당 참조를 삭제하지 않으며, 실패 시 생성한 부분 bundle만 정리한다.
원격 응답이 전달하지 않은 스위트의 수집을 주장하거나, 성공한 수집 수가 전달된 스니펫 수보다 적거나,
성공 수와 exit code가 맞지 않거나, 봉인 종류 순서·값이 보낸 스위트와 다르면 거부한다.
수집 수 하한은 각 스니펫별 수집 증명을 대체하지 않으며, 세부 파일별 증거는 별도 연결이 필요하다.

## 검증 범위와 남은 연결

수용 테스트는 실제 PostgreSQL·실제 로컬/번들 Runner를 사용한다.
Critic 응답·영수증·등록된 image digest는 명시적인 합성 fixture이며 실공급사 청구나 OCI 이미지 검증을 뜻하지 않는다.
Runner Dockerfile의 Python 파일 구성만 별도 `python -I` 프로세스로 실행해 API 패키지 없이 동작하는 것도 확인한다.
Docker 이미지 빌드·GCP 배포·실제 Muse 호출은 이 변경의 검증 범위에 포함하지 않는다.
API **414 passed·1 skipped**, 실제 PostgreSQL **91 passed**, 참조 112·SQL 96·패키지 검사와 웹 빌드 통과.
원본 로그와 SHA-256은 `docs/validation/2026-10-27-runner-core-evidence.json`이 가리키는 보존 폴더를 따른다.

공개 생성 결과의 canonical 후보 생성·요율/청구·나머지 게이트와 독립 리뷰·승인 연결,
운영 마이그레이션·승인된 Runner digest 배포 설정은 남아 있다. 기본 Muse Spark와 자동 모델 대체 금지는 유지한다.
