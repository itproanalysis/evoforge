"""Real-provider judging-profile smoke; no provider or Runner mocks."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--keys-file", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    allowed = {"MODEL_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"}
    for line in Path(args.keys_file).read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if key.strip() in allowed:
                os.environ[key.strip()] = value.strip().strip("\"'")
    os.environ.update(EVO_MODEL_PROFILE="collaborative", MODEL_BUILDER="muse-spark-1.3",
        MODEL_CRITIC="claude-opus-5-5", MODEL_MAX_TOKENS="32000", MODEL_CRITIC_MAX_TOKENS="32000",
        EVO_STATE_BACKEND="memory", EVO_PROJECT_BUDGET_CENTS="2000")
    for name in ("CRITIC_API_BASE", "CRITIC_API_KEY", "EVO_RUNNER_URL"):
        os.environ.pop(name, None)
    from evoforge import arena, broker_meta, collaboration, ledger
    ledger.configure({"default": 2000})
    builder_calls = []
    original = broker_meta.call_builder
    def observed_builder(*a, **kw):
        out = original(*a, **kw)  # observation only; actual provider still runs
        builder_calls.extend(out.get("provider_calls", []))
        return out
    broker_meta.call_builder = observed_builder
    task = {"id": "judge-default-real-smoke", "goal": "In app.py implement inc(x). Accept Python integers but reject bool and other types with ValueError. Return x + 1, including negative integers and zero.",
            "files": {"app.py": "def inc(x):\n    return x\n"},
            "heldout": [
                {"kind": "compositional", "code": "def test_positive():\n    import app\n    assert app.inc(10) == 11\n"},
                {"kind": "negative", "code": "def test_type():\n    import app, pytest\n    with pytest.raises(ValueError):\n        app.inc(True)\n"},
                {"kind": "boundary", "code": "def test_zero_negative():\n    import app\n    assert app.inc(0) == 1\n    assert app.inc(-2) == -1\n"}]}
    lane = arena._run_evoforge_lane_critic(task, "muse-spark-1.3", 60, max_attempts=2)
    records = [v for _,v in collaboration._records.items() if v.get("kind")=="provider_call"]
    models = {c.get("model") for c in builder_calls}
    models.update(v.get("metadata", {}).get("model") for v in records if v.get("metadata"))
    result = {"profile": collaboration.public_defaults(), "lane": lane, "builder_calls": builder_calls,
              "provider_records": records, "observed_models": sorted(m for m in models if m),
              "ledger": ledger.snapshot(), "execution": "real native APIs + real local release Runner; not Cloud Run/PostgreSQL proof"}
    dest = Path(args.output); dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert lane["status"] == "succeeded" and lane["outcome"] == "passed", "real default profile did not pass"
    assert models == {"muse-spark-1.3", "gpt-6.1-sol", "gemini-4-argon", "claude-opus-5-5"}
    assert ledger.snapshot()["reserved_cents"] == 0
    print(json.dumps({"outcome": lane["outcome"], "observed_models": sorted(models),
                      "cost_cents": ledger.snapshot()["spent_cents"], "evidence": str(dest)}))


if __name__ == "__main__":
    main()
