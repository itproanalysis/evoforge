"""Suite-wide test defaults (Critic-owned).

The public daily run limit (T84, EVO_PUBLIC_DAILY_RUNS, production default 20) counts every Arena created today; one
pytest process starts far more than 20 Arenas, so the suite runs with a high limit. Tests of the limit itself set or
delete the variable explicitly.
"""
import os

os.environ.setdefault("EVO_PUBLIC_DAILY_RUNS", "1000000")
