# Builder 출력과 canonical 후보 연결

인증된 Worker가 저장된 Builder 출력·정산·실제 Git tree를 대조해 `core.candidates`에
PROPOSED 후보를 등록한다. 모델 호출, GitHub 쓰기, 게이트/리뷰 생성이나 병합 승인은 하지 않는다.
Muse Spark 기본 모델 `muse-spark-1.3`은 유지한다.

## 경로와 설정

기존 내부 서비스 인증·tenant/project 설정과 확장 001–010이 필요하다.
DB에 `010_candidate_pr_evidence.sql`까지 적용한 뒤 API를 배포한다.
저장소는 서버의 GITHUB_REPO/GITHUB_TOKEN 설정을 사용하며 요청으로 경로나 자격 증명을 바꿀 수 없다.
브라우저 BFF의 `/v1/kernel` 차단과 Google/커널의 독립 인증은 유지한다.

| 경로 | 동작 |
|---|---|
| POST `/v1/kernel/candidates` | call_id(UUID), Builder evidence_id, head_sha와 선택적 pr_source_evidence_id로 등록. candidate_id는 서버가 생성 |
| GET `/v1/kernel/candidates/{candidate_id}` | scope 내 등록 증거·원래 head·현재 head·상태 조회 |

현재 GitHub checkout 경로에 맞춰 40자리 소문자 SHA-1 commit만 받는다. branch/ref와
요청의 status/model/agent/tenant/project/source_repo 변경은 거부한다.

## 등록 전 확인

- Builder call의 정본 예약이 COMMITTED/CONFIRMED이고 같은 call의 model_usage 원장 항목이 있어야 한다.
- 보존한 정본 영수증의 digest·tenant/project/call/receipt·platform 소유·가격이 원장/예약과 같아야 한다.
- packet/model/가격표·현재 agent/task fencing·provider consent를 기존 preflight로 확인한다.
- Task/Candidate/Gate 이벤트가 있는 서버 Builder 출력이어야 한다. stub은 거부한다.
- 출력의 SDK provider_calls는 해당 Builder 한 호출이며 provider/model/phase와 transport request ID가 영수증에 일치해야 한다.
  없는 request ID를 completion ID로 대체하지 않는다.

서버는 설정된 저장소를 요청한 immutable head로 가져와 reserved base가 그 조상인지 확인한다.
base의 실제 UTF-8 blob에 strict unified diff를 적용하고, Builder visible 테스트를 PR 경로와 같은 이름으로 포함한다.
새 PR은 서버에 저장된 실행 증거 ID를 `pr_source_evidence_id`로 전달하며 파일명은
`tests/evoforge_gen/test_{실행증거 태그}_{N}.py`다. 이전 호출의 ID 생략 시 기존 `test_gen_N.py`를 검증한다.
실제 base→head의 전체 변경 경로·blob ID·파일 mode가
이 결과와 같아야 한다. 누락된 테스트, 다른 코드/추가 파일, 충돌 경로와 mode 변경은 거부한다.
이 단계는 Git 객체만 읽고 후보 코드는 실행하지 않는다. 경계를 확인한 전용 임시 checkout만 삭제한다.

새 실행 증거는 같은 scope의 Candidate/Gate 단계가 있어야 하며 기준 SHA·diff·visible 테스트가
정산된 Builder 출력과 정확히 일치해야 한다. mission Builder이면 같은 mission의 실행이어야 한다.
서버 Review가 non-stub이고 봉인 suite가 유효하며 Runner 실행 수·타임아웃·종료 코드와 모든 기록된 게이트가 PASS여야 한다.
실행 증거 ID와 문서 SHA-256은 후보 binding에 함께 저장하며 010의 scope FK·불변 트리거로 보존한다.
다른 ID를 이용한 재전송, 다른 scope/mission 증거, 기준/내용 불일치와 누락된 010 스키마는 거부한다.

네트워크 checkout 동안 DB 트랜잭션을 잡지 않는다. Git 검증 후 새 트랜잭션에서 영수증·fencing·출력을
다시 확인하고 후보와 불변 binding을 함께 저장한다. 동시 요청/재전송은 같은 후보를 반환하며,
다른 evidence/head로 재사용하거나 등록 후 head가 바뀐 경우 409다. binding 저장 실패는 후보도 롤백한다.

## Runner와 미완료 경계

등록된 Builder 후보의 Runner/G2 연결은 원래 head/call을 다시 검사한다.
PR 생성 전에 기록된 실행 증거만으로 committed head의 G2를 만들지 않는다. 해당 head의 별도 Runner 재검사가 필요하다.
등록 후 head drift가 있으면 과거 PASS의 재전송도 거부한다. 기존 수동/다른 출처의 core 후보 경로는 유지한다.
이 등록만으로 후보 상태를 올리거나 필수 게이트를 PASS로 만들지 않으며 `core.authorize_merge`는
나머지 게이트·독립 리뷰·승인이 없으면 계속 거부한다.

공개 Generate/mission/PR의 canonical 명령·실제 Broker 예약·가격표/영수증·후보 등록 호출은 아직 연결되지 않았다.
공개 GitHub PR 생성의 base 전달도 공유 main 경로에서 추가 대조가 필요하다.
실제 모델 청구·운영 DB/배포 완료로 취급하지 않는다. 원격 Runner image 설정은 기존과 같이 운영자 승인 식별자다.

검증은 실제 Git·PostgreSQL·로컬 Runner를 사용하며 Builder/Critic/영수증/GitHub checkout transport는 합성 fixture다.
원본 로그·SHA-256·집계는 `docs/validation/2026-10-27-candidate-registration.json`에 보존한다.
API **465 passed·1 skipped**, 실제 PostgreSQL **144 passed**(새 후보 등록 회귀 5개 포함),
참조 **112개**·SQL **96개**·계약 **0 failure**·웹 프로덕션 빌드를 통과했다.
동시 최초 등록 8회·새 API 프로세스 조회·실제 Runner/G2 연결·병합 거부·head drift·fencing 재검사·원자적 롤백을 확인했다.
상위 Muse T22의 main/평가/UI·봉인 테스트·정본 파일은 수정하지 않는다.
