# 관리 화면 운영 반영 준비 — 2026-10-28

이 문서는 조회 결과와 배포 인계다. 이 조사에서는 운영 DB·서비스·트래픽을 변경하지 않았다.

- 프로젝트 `evoforge-prod-4ff3`, `asia-northeast3`의 웹 최신 Ready revision은
  `evoforge-web-00011-kt8`이지만, 실제 서비스 트래픽 100%는
  `evoforge-web-00003-hpf`(`rev3`)에 고정돼 있다. API 트래픽 100%는
  `evoforge-api-00013-9p7`이다. 따라서 새 웹 revision 생성만으로 사용자에게 반영되지 않는다.
- 인증 정보 없이 웹 루트와 웹 프록시 dashboard가 HTTP 200, participants와 performance가
  404였다. 직접 API dashboard는 403이었다. 이는 관찰 당시의 접근 결과이며 새 revision의
  인증 정책이나 배포 권한을 입증하지 않는다. release captain이 노출 범위를 확인해야 한다.
- Cloud SQL `evoforge-pg-hackathon` 인스턴스는 RUNNABLE이다. 운영 011의 실제 적용 여부와
  테이블·권한·RLS·트리거 및 ledger 일치는 확인하지 못했다. 현재 세션의 SQLROOT_PW도
  설정돼 있지 않다. 비밀값은 채팅에 보내지 말고 운영 담당자가 승인된 비밀 관리 경로를 사용한다.
- `e14ba3f`는 검증 대상 후보이며, `57c4cb0`과 API·웹·인프라·정본 소스가 같다.
  후자의 전체 API 671 passed·4 skipped, 격리 PostgreSQL 011 및 정본 검사가 통과했다.
  웹 tree는 npm ci/tsc/build를 검증한 `e13cce8`과 같다. 다만 이는 release captain이
  확정한 새 release commit이나 운영 검증을 뜻하지 않는다. 기존 `release/live`는
  `72a0d86`으로 이 후보와 다르다.

운영 담당자 순서:

1. 운영 migration ledger와 실제 스키마 및 001–010 적용 근거를 읽기 전용으로 대조한다.
   011이 없다면 승인된 절차로 011을 선적용하고 권한·RLS·트리거를 검증한다.
   ledger와 스키마가 어긋나면 중단하고 `docs/MIGRATION_RECOVERY_CODEX.md`를 따른다.
   Cloud Build의 migrate 단계는 skip이므로 자동 적용을 가정하지 않는다.
2. release captain이 최신 main과 통합 테스트 근거를 확인하고 확정 commit에서 별도
   깨끗한 release worktree를 만든다. API와 웹을 이 정확한 commit으로 배포한다.
3. 웹 트래픽 고정을 확인하고 승인된 방식으로 새 revision에 전환한다. 인증된 운영
   접근과 프로젝트 범위의 participants/performance 빈 상태 및 실제 데이터를 확인한다.
   proxy를 통한 live mission과 증거를 확인하고 결과를 기록한다.

공급사 실호출·실청구와 공개 PR의 전체 경로는 이 준비 확인으로 완료되지 않는다.
기본 모델 `muse-spark-1.3`과 자동 대체 금지 방침을 유지한다.
