# 웹 의존성 수정과 검증

2026-10-27. 기존 Next.js 15.1.6 설치에서 npm audit가 3개 패키지 취약점
(critical 1, high 2)을 보고했다. Next.js를 **15.5.28**로 고정하고 lockfile을 갱신했다.
React/React DOM 19.0.0과 Muse round3의 화면 코드는 보존했다.

Next.js 유지관리자의 [보안 공지](https://github.com/vercel/next.js/security/advisories/GHSA-2464-fhr4-w9xw)는
15.5.28을 수정 버전으로 명시하며, 이미지 처리 라이브러리 sharp 0.35.5 이상을 요구한다.
새 설치에서도 sharp **0.35.5**를 확인했다.

Next 15.5.28이 고정하는 PostCSS 8.4.31에는 별도 경고가 남아,
`overrides.next.postcss`만 **8.5.32**로 고정했다.
PostCSS 유지관리자의 [공지](https://github.com/postcss/postcss/security/advisories/GHSA-fxqj-rqcc-2cmp)는
8.5.22 이하의 소스맵 파일 노출 문제와 8.5.23의 수정을 설명한다.
이 override는 Next가 사용하는 PostCSS에만 적용된다.
Next 빌드가 재생성한 `next-env.d.ts`의 route 타입 참조도 함께 반영했다.

Node **24.15.0**, Windows에서 확인했다:

```powershell
cd apps/web
$env:NEXT_TELEMETRY_DISABLED='1'
npm ci
npm audit --json
npm run build
```

- 깨끗한 npm ci 성공, audit **0 vulnerabilities**. 이는 검사 시점의 advisory 결과다.
- Next 15.5.28의 프로덕션 컴파일·타입 검사·정적 페이지 생성·build trace 성공.
- standalone 서버를 loopback 임시 포트에 시작해 `/`, `/lab`, `/evidence`, 정적 JS의 HTTP 200 확인.
- 검사 후 해당 서버 프로세스 종료 확인.
- 로그는 지원 작업 트리의 `.local/validation-web-audit.json`, `.local/validation-web-startup.log`.

main 반영 후 `C:\evo_forge`에서도 npm ci·audit 0건·프로덕션 빌드와 standalone HTTP 검사를 통과했다.
최종 로그는 main의 `.local/evidence/receipts-20261027-f42duc14`에 별도로 보존했다.

Linux 컨테이너 빌드, Cloud Run 배포, 실제 공급사·GitHub 워크플로와 브라우저 사용자 인증은
이번 검증에 포함하지 않았다. Muse Spark 기본값과 자동 모델 대체 금지는 유지했다.
