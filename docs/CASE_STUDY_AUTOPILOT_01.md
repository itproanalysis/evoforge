# Case Study 01 — 첫 실제 자율 진화 (Muse Spark 실호출, 과금)

일시: 2026-10-28. 도구: `tools/autopilot_case.py` (메타데이터만 출력, 비밀·코드 출력 없음).

## 설정

- 스크래치 git 저장소(임시 디렉터리, `EVO_REPO_ROOTS`로 허용)에 `calc.py` 1개:
  `add(a, b)`가 `a - b`를 반환하는 버그 포함, `subtract`는 정상.
- 목표: "Fix add(a, b) in calc.py so it returns a + b; keep subtract(a, b) unchanged"
- `repo_ref` = 스크래치 HEAD SHA, `target_paths` = ["calc.py"],
  `max_generations` = 2, `population` = 1, `use_memory` = true.
- 로컬 인프로세스 Runner (별도 Runner URL 없음).

## 결과 (1세대 만에 CONVERGED)

| 항목 | 값 |
|---|---|
| evolution_id | `evo_c1c8d61fc3fa` |
| generations | 1 (gen 0에서 수렴, gen 1 미실행) |
| GH_INTEGRITY | PASS (integrity clean) |
| GC_COMPOSITION | PASS |
| G2_REQUIRED | PASS — required tests executed and passed (visible 4/4, held-out 3/3) |
| fitness | 130.0 (만점: 100 + held-out 20 + visible 10) |
| review_result | PASS |
| run_evidence_id | `ev_9140e981d0f4` |
| 원장 실지출 | 360¢ (Builder 120 + Critic 2상 × 120), UNKNOWN 0 |
| proof | `GET /v1/proof/ev_9140e981d0f4` → VERIFIED, signature verify ok |

사람이 한 일: 목표 문장 1개 + 스크립트 실행. 이후 Builder→Critic→Run→게이트→
수렴 판정→(원하면)PR까지 전부 서버가 수행했다.

## 이 사례가 남긴 안정화 수정

1. **`_load_builder_context`가 `source_repo=""`를 하드코딩**하고 있어
   로컬 저장소 + `target_paths` 조합이 "unknown repo configuration" 400으로
   죽었다. 시그니처에 `source_repo`를 추가하고 autopilot step에서 전달.
   기존 호출자(기본값 `""`) 동작 불변. 회귀 테스트:
   `test_step_local_source_repo_context`.
2. **동시 step 경합**: 동일 evolution에 두 `/step`이 동시에 들어오면
   세대가 중복 실행됐다. `evolution.lock_for()` per-evolution 뮤텍스,
   경합 시 409. 테스트: `test_step_lock_rejects_concurrent_generation`.
3. **메모리 무한 증가**: 수렴할 때마다 패턴이 쌓였다. 상한 200,
   초과 시 fitness 최저→오래된 순 방출. 테스트:
   `test_memory_bounded_evicts_weakest`.

## 재현

```powershell
cd C:\evo_forge
python tools/autopilot_case.py   # .env의 MODEL_API_KEY 사용, 수백¢ 과금
```

출력은 증거 ID·게이트·fitness·원장 증감만 포함한다.
