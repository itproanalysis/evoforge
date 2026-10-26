> **v3.6 주석:** 이 README는 v3.4 원 패키지의 것이다. 아래 표기 중 *(이 패키지에 미포함)* 항목은 v3.5 패키지에도 들어 있지 않았다(v3.5 리뷰가 'ZIP 무결성 검증'을 적었지만 이 누락은 잡지 못했다). `pages/EvoForge_v3.4_NN.md` 분리본도 없다. 필요한 경우 v3.4 원본 패키지에서 다시 가져와야 한다.

# EvoForge v3.4 — 5-Agent Adaptive Collective Package

This is a **design** package; there is no runtime performance claim or implementation.

- `README_MASTER_50PAGES.md`: definitive 50-page SaaS implementation blueprint, v3.4.
- `pages/EvoForge_v3.4_NN.md`: exactly 50 logically separate pages.
- `FIVE_AGENT_ADAPTIVE_COLLECTIVE_SPEC.md`: detailed five-agent topology, scheduling, gates and 10X evaluation protocol.
- contracts/collective-run.schema.json *(이 패키지에 미포함)*: new run contract; accompanying collective-run.example.json *(이 패키지에 미포함)*.
- contracts/collaboration-event.schema.json *(이 패키지에 미포함)*: new event contract.
- schema/v3_4_collective_migration_DRAFT.sql *(이 패키지에 미포함)*: **unexecuted draft** migration.
- benchmarks/FIVE_AGENT_10X_PROTOCOL.md *(이 패키지에 미포함)*: matched experimental plan.
- acceptance/FIVE_AGENT_20_SCENARIOS.md *(이 패키지에 미포함)*: new acceptance tests.
- decisions/ADR_034_FIVE_AGENT_AND_THROUGHPUT.md *(이 패키지에 미포함)*: decision record.
- `reference_v3_3/`, older `contracts/`, `examples/`, and `schema/` retain prior source material and migration contracts.

**Precedence:** 2026-10-23 v3.4 sections supersede older conflicting v3.3 decisions. In particular, no mandatory always-on five-way fan-out.

**Safety:** cannot skip independent review, branch protection, tenant isolation, permissions, budget caps, or required CI for higher throughput. 10X is a hypothesis for actual matched experiments, not verified performance.
