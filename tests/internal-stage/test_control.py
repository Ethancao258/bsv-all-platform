"""Control-plane routing and release evidence rejection tests."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "platform/lighthouse/internal-stage")]
from bsvctl import JOBS, validate_ci
from route_change import route


class ControlTests(unittest.TestCase):
    def test_routes_known_work_keeps_namespaces(self):
        index = json.loads((ROOT / "config/change-routing.json").read_text())
        change = route(index, "在POS开桌", [], "API_LOGIC", "isolated")
        self.assertEqual(change["module_ids"], ["store-pos"])
        self.assertEqual(change["state"], "ROUTED")
        self.assertIn("identity.A", change["data_sources"])
        change = route(index, "数据库A换地址", ["supply-api"], "SOURCE_ENDPOINT", "isolated")
        self.assertEqual(change["state"], "REVIEW")
        self.assertIn("supply.A", change["data_sources"])
        self.assertNotIn("identity.A", change["data_sources"])
        self.assertEqual(route(index, "其他需求", [], "UI_COPY", "isolated")["state"], "REVIEW")

    def test_ci_binds_exact_sha_and_required_jobs(self):
        sha = "a" * 40
        proof = {"url": "https://github.com/Ethancao258/bsv-all-platform/actions/runs/42",
                 "headSha": sha, "conclusion": "success", "status": "completed", "event": "pull_request",
                 "workflowName": "validate-architecture",
                 "jobs": [{"name": name, "conclusion": "success", "status": "completed"} for name in JOBS]}
        self.assertEqual(validate_ci(proof, sha), proof["url"])
        with self.assertRaises(ValueError):
            validate_ci(proof, "b" * 40)
        with self.assertRaises(ValueError):
            validate_ci(dict(proof, jobs=proof["jobs"][:-1]), sha)
        with self.assertRaises(ValueError):
            validate_ci(dict(proof, url="https://github.com/else/repo/actions/runs/42"), sha)


if __name__ == "__main__":
    unittest.main()
