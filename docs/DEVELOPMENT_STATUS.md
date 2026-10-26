# EvoForge 개발 진행 상태

갱신: 2026-10-27 (Asia/Seoul). **전체 개발 상태: 미완료.**

## 사용자의 개발 지시

- EvoForge의 메인 모델은 **Muse Spark**다.
- 현재 저장소의 모델 식별자 `muse-spark-1.3`을 Builder·Critic의 기본값으로 유지한다.
- 다른 모델로의 자동 대체는 하지 않는다. Critic의 독립성·명세 선행 검증은 유지한다.
- 작업이 완료되지 않았는데 개발 세션이 끝나면 자동으로 다시 깨어나 실제 구현과 검증을 이어간다.

## 확인된 완료 항목

- [x] Builder·Critic 코드, `.env.example`, GCP Cloud Run 설정의 Muse Spark 기본값 확인.
- [x] 생성 경로와 전체 무결성 게이트의 판정 통일, 누락·오류 테스트 증거 처리 보강.
- [x] 회귀 테스트 20개 추가. API 테스트 27개, 참조 테스트 112개 통과.
- [x] 현재 채팅의 자동 재개 활성화. 자동화 ID: `evoforge`, 확인 간격: 15분.
- [x] CI 검증 의존성·PostgreSQL 15 테스트 환경·웹 빌드 검사 구성. 새 가상환경의 참조 112개·API 93개·웹 프로덕션 빌드 통과. 컨테이너 실행은 미검증.
- [x] 후속 Windows 임시 PostgreSQL 15.19 실제 실행: SQL 96개·참조 112개·계약 C1–C9 전체 통과. 컨테이너/배포 실행은 미검증.

## 이어서 수행할 작업

> **완료 (Claude, 2026-10-27, `eff542f` main 병합):** 아래 앞의 4개 항목 + 웹→API CORS 누락 수정.
> 근거: API 93 passed(Critic 수용 테스트 `tests/test_critic_t1~t4_*.py` 61개·CORS 5개 포함), 참조 112 passed,
> `validate_package.py` 0 failure(`--pg` 미실행), `next build` 성공, 패치 적용기 퍼징(difflib 3000건·git diff 150건) 불일치 0.
> 브라우저 E2E(로컬): Mission Control Generate → Lab Evaluate(실행 통계 입력) → INCONCLUSIVE 시 PR 버튼 비활성 확인.
> 미검증: 실제 Muse Spark 호출(키 없음), 실제 GitHub PR 생성(토큰 없음), Cloud Run 배포 환경의 CORS.
> Muse Spark Builder 루프: `tools/muse_improve.py` + `tools/muse_tasks/*.json` (`MODEL_API_KEY`를 `services/api/.env`에 두면 사용).

> **CI 구성 완료 (Codex, 2026-10-27, `560a5ef`):** API 변경과 분리해 검증 의존성, PostgreSQL 테스트 환경,
> 웹 빌드 검사, Docker 웹 컨텍스트와 빈 `public/` 경로를 보강했다.
> 검증 근거와 실제 SQL·컨테이너 실행의 남은 항목은 [CI_VALIDATION.md](CI_VALIDATION.md)에 기록했다.

> **SQL 검증 완료 (Codex, 2026-10-27, `71ed84f`):** `tools/validate_local_pg.py`로 Windows용 임시 PostgreSQL 15.19에서
> `validate_package.py --pg`를 실행했다. SQL 96개·참조 112개·C1–C9 전체 통과, 서버 종료와 클러스터 정리 확인.
> 재현 명령과 범위는 [LOCAL_POSTGRES_VALIDATION.md](LOCAL_POSTGRES_VALIDATION.md)에 기록했다.

- [x] 모델 호출 실패 후 비용 예약을 접수 전 실패(환불)·결과 불명(`UNKNOWN` 보류)으로 처리. 영수증 대사로 UNKNOWN을 settle/refund하는 잡은 미구현.
- [x] 실행 성공 수·전체 수의 입력 관계 검증(422)과 0건 실행의 증거 부족(INCONCLUSIVE) 처리.
- [x] 기준 브랜치 파일에 unified diff를 엄격 적용해 문맥을 보존하는 PR 생성 경로 구현·검증(mock transport).
- [x] PR은 서버가 저장한 게이트 평가(`evidence_id`)가 전부 PASS일 때만 생성. 웹 Lab도 Evaluate → PR 순서로 변경.
- [ ] 실제 Runner와 봉인 테스트 결과 연결.
- [x] PostgreSQL SQL 계약의 비용 예약·원장·RLS·병합 승인 등 96개 검사 실제 실행.
- [ ] FastAPI에서 PostgreSQL의 비용 예약·영수증·병합 승인 경로 연결. 현재 `ledger.reserve_pg/settle_pg`는 정본에 없는 `project_budgets`를 참조하므로 교체가 필요하다. DB는 micro-USD, 메모리 원장은 cents 단위이므로 정수 변환 계약도 명시해야 한다.
- [ ] Muse Spark 실제 호출과 저장소 연결을 포함한 통합 경로 검증.
- [ ] 배포·통합 검증 결과와 남은 요구사항을 대조하고 완료 근거 기록.

## 외부 연결 확인 범위

현재 Codex의 로컬 프로세스에서는 `MODEL_API_KEY`, `DATABASE_URL`, `GITHUB_TOKEN`이
설정되지 않은 것을 확인했다. 저장소 루트와 API 폴더에도 `.env`가 없었다.
다른 세션이나 Secret Manager의 설정 여부는 이 확인만으로 판단하지 않는다.
실제 연동을 완료하려면 해당 실행 환경의 자격 증명과 접근 권한을 확인해야 한다.
비밀 값은 문서·채팅·로그에 기록하지 않는다.

## 자동 재개의 완료 판단

자동화는 현재 채팅과 `C:\evo_forge`에서 미완료 개발을 이어간다.
기존 변경을 먼저 확인하고, 수정·검증 결과와 남은 작업을 이 문서에 갱신한다.
stub 또는 정적 게이트·단위 테스트 통과만으로 실서비스 통합 완료를 선언하지 않는다.
상태가 그대로면 반복 알림을 보내지 않으며, 중요한 진척·완료·실패 또는 사용자 조치가 필요할 때 알린다.
요구사항이 모두 충족되고 검증 근거가 기록되면 자동화를 비활성화한다.
로컬 파일 작업이므로 PC와 Codex 앱이 실행 중이어야 한다.
