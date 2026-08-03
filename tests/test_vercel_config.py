import json
from pathlib import Path


def test_vercel_functions_run_near_supabase_tokyo_region():
    config = json.loads((Path(__file__).resolve().parents[1] / "vercel.json").read_text(encoding="utf-8"))

    assert config["regions"] == ["hnd1"]
