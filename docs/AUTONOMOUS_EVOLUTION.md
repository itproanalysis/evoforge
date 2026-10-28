# Autonomous Evolution (Autopilot) + Proof Certificates

갱신: 2026-10-28. **새 지평: 목표 입력 → 검증된 PR 출력.**

## 왜 혁명인가

기존 EvoForge는 수동 파이프라인이었다: Generate → Review → Run → PR을
사람이 한 단계씩 눌러야 했다. Autopilot은 이를 **자율 진화 루프**로 바꾼다:

1. 목표 하나를 넣으면 N세대 × M개체의 후보가 자동으로 번식한다.
2. 각 후보는 기존 트러스트 커널(`_generate_core`/`_review_core`/`_run_core`)로만
   평가된다. Autopilot 자체는 PASS를 발행할 수 없다.
3. Critic의 실패 원인이 다음 세대의 goal로 자동 피드백된다
   (`evolution.feedback_goal` — 문자열 수술, 신뢰 주장 없음).
4. 전부 PASS한 run이 나오면 CONVERGED, 예산(최대 10세대)이 다하면 EXHAUSTED.
   오프라인 키 없음 상태에서는 정직하게 EXHAUSTED (가짜 수렴 없음).
5. 수렴한 best run만 `POST /v1/evolution/{id}/promote`로 PR 승격.
   미검증 best의 승격은 409.

## Proof Certificates — AI 코드의 SSL 인증서

`GET /v1/proof/{evidence_id}`는 공유 가능한 변조 방지 증명을 민트한다:

- gates 판정, evidence chain, diff sha256, sealed 메타데이터만 포함.
- **코드는 절대 포함하지 않음** (redacted public view 위에서 서명).
- `signature = sha256(canonical JSON)` — 누구나 `verify`로 재계산 검증.
- 채팅 기록 대신 URL 하나를 공유하면 된다.

## API

- `POST /v1/evolution/start` {goal, repo_ref, max_generations 1..10, population 1..5}
- `POST /v1/evolution/{id}/step` — 1세대 동기 실행
- `POST /v1/evolution/{id}/run` — CONVERGED/EXHAUSTED까지 루프
- `GET /v1/evolution`, `GET /v1/evolution/{id}`
- `POST /v1/evolution/{id}/cancel`, `POST /v1/evolution/{id}/promote`
- `GET /v1/proof/{evidence_id}`

## Web

- `/evolution` (`/[locale]/evolution`) — Autopilot Observatory: 실행 시작,
  세대 타임라인, fitness 바, step/run/promote, proof 링크.
- `/verify/[id]` — 공개 증명서 뷰어 (로그인 없이 공유 가능).
- 프록시 정책(`proxyPolicy.ts` + cases 11건 추가) — `/v1/kernel/*` 차단은 유지.

## Wave 2 — Evolution Memory + Trust Leaderboard (2026-10-28)

쓰면 쓸수록 똑똑해지는 팩토리 + 검증 경제의 순위표.

- `evoforge/memory.py`: 수렴한 winner를 패턴(goal 키워드 + diff 발췌 ≤2000자 +
  fitness)으로 증류. `recall()`은 결정적 키워드 겹침 순위 (LLM 없음).
- `POST /v1/evolution/start`의 `use_memory=true`면 과거 승리 접근법이
  Builder 프롬프트에 서버사이드로만 주입 (`hint_block` — HTTP 응답에 코드 유출 없음).
- 수렴 시 `_maybe_memorize`가 자동 기록 (evolution당 1회, 멱등).
- `GET /v1/leaderboard`: 수렴 진화를 fitness↓·세대수↑ 순으로 순위화.
  명성의 단위는 주장이 아니라 proof 링크 (`/v1/proof/{run}`).
- `GET /v1/memory`: 다이제스트 전용 공개 뷰 (코드 영원히 없음).
- 웹: `/leaderboard` (+`/[locale]/leaderboard`), evolution 시작폼에 메모리 토글.
  프록시 cases 4건 추가 (총 96).
- 검증: `tests/test_evolution_memory_leaderboard.py` 4개 — recall 순위,
  리더보드 proof 링크, 메모리 코드 비유출(HTTP 본문 검사),
  `use_memory` 플래그. Wave 1 포함 10개 통과.

## 검증

- `tests/test_evolution_autopilot.py` 6개: 오프라인 EXHAUSTED 정직성,
  미검증 promote 409, fitness 단위, feedback 문구, 증명서 redact+서명 검증/변조 거부, 404.
- 회귀: `test_api` + `test_outcomes` + `test_critic_t4/t18` 35개 통과.
- `tsc --noEmit` 0 error, `next build` 전 라우트(신규 4개 포함) 성공,
  `validate_package --pg` 0 failure, 한/영 키 동등성 일치.
