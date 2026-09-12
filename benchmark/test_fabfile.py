import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fabfile


class OfferedRateResultTests(unittest.TestCase):
    def setUp(self):
        self.parameters = {
            "nodes": 7, "faults": 1, "gamma": 0.9, "rate": 1000,
            "tx_size": 512, "duration": 20, "offered_rate_tolerance": 0.02,
            "lo_interval": 150, "lo_size": 200,
        }
        self.metrics = {
            "replica_states": {str(i): ("1", "a" * 64, "b" * 64) for i in range(7)},
            "measurement_duration_ms": 20000,
            "submitted": 19223,
            "finalized": 18000,
            "locally_failed_transaction_send_attempts": 0,
            "locally_failed_local_order_send_attempts": 0,
            "locally_failed_candidate_send_attempts": 0,
            "locally_failed_benchmark_commit_send_attempts": 0,
            "proposal_verification_failures": 0,
            "order_extraction_failures": 0,
            "follower_candidate_rejections": 0,
            "hosting_commit_rejections": 0,
        }

    def write_result(self):
        with tempfile.TemporaryDirectory() as directory:
            warning = io.StringIO()
            with patch.object(fabfile, "RESULT_DIR", Path(directory)), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(warning):
                fabfile._write_result("local", self.parameters, 1, self.metrics)
            paths = list(Path(directory).glob("*.json"))
            self.assertEqual(len(paths), 1)
            return json.loads(paths[0].read_text(encoding="utf-8")), warning.getvalue()

    def test_underload_is_saved_with_warning_and_separate_rates(self):
        result, warning = self.write_result()
        self.assertEqual(result["configured_offered_rate"], 1000)
        self.assertEqual(result["actual_offered_rate"], 961.15)
        self.assertEqual(result["average_tps"], 900)
        self.assertAlmostEqual(result["offered_rate_relative_deviation"], 0.03885)
        self.assertFalse(result["offered_rate_within_tolerance"])
        self.assertIn("WARNING", warning)

    def test_saturated_finalization_does_not_fail_rate_check(self):
        self.metrics.update(submitted=19999, finalized=100)
        result, warning = self.write_result()
        self.assertTrue(result["offered_rate_within_tolerance"])
        self.assertEqual(result["average_tps"], 5)
        self.assertEqual(warning, "")

    def test_threshold_boundary_and_excess_load(self):
        for submitted, within in [(19600, True), (19599, False), (20400, True), (20401, False)]:
            with self.subTest(submitted=submitted):
                self.metrics["submitted"] = submitted
                result, warning = self.write_result()
                self.assertEqual(result["offered_rate_within_tolerance"], within)
                self.assertEqual(bool(warning), not within)

    def test_zero_target_is_json_safe(self):
        self.parameters["rate"] = 0
        self.metrics["finalized"] = 0
        for submitted in [0, 1]:
            with self.subTest(submitted=submitted):
                self.metrics["submitted"] = submitted
                result, warning = self.write_result()
                self.assertEqual(result["offered_rate_within_tolerance"], submitted == 0)
                self.assertEqual(result["offered_rate_relative_deviation"], 0.0 if submitted == 0 else None)
                self.assertEqual(bool(warning), submitted != 0)

    def test_compound_go_duration(self):
        self.assertAlmostEqual(fabfile._duration_ms("1m0.0001s"), 60000.1)
        self.assertEqual(fabfile._duration_ms("1h2m3s"), 3723000)

    def test_missing_replica_report_rejects_results(self):
        del self.metrics["replica_states"]["6"]
        with self.assertRaisesRegex(RuntimeError, "same final committed"):
            self.write_result()

    def test_send_failures_still_reject_results(self):
        for key in [key for key in self.metrics if key.startswith("locally_failed_")]:
            with self.subTest(key=key):
                with patch.dict(self.metrics, {key: 1}), self.assertRaisesRegex(RuntimeError, "locally.failed"):
                    self.write_result()

    def test_inconsistent_replica_states_still_reject_results(self):
        self.metrics["replica_states"]["4"] = ("2", "c" * 64, "d" * 64)
        with self.assertRaisesRegex(RuntimeError, "same final committed"):
            self.write_result()

    def test_interval_sweeps_and_repeats_have_distinct_run_ids(self):
        first = fabfile._run_id("remote", self.parameters, 1)
        second = fabfile._run_id("remote", self.parameters, 1)
        self.parameters["lo_interval"] = 50
        third = fabfile._run_id("remote", self.parameters, 1)
        self.assertEqual(len({first, second, third}), 3)
        self.assertIn("-i150-", first)
        self.assertIn("-i50-", third)

    def test_existing_result_is_not_overwritten(self):
        self.parameters["run_id"] = "fixed-test-run"
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(fabfile, "RESULT_DIR", Path(directory)), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                fabfile._write_result("local", self.parameters, 1, self.metrics)
                saved = (Path(directory) / "fixed-test-run.json").read_bytes()
                with self.assertRaises(FileExistsError):
                    fabfile._write_result("local", self.parameters, 1, self.metrics)
                self.assertEqual((Path(directory) / "fixed-test-run.json").read_bytes(), saved)

    def test_queue_exhaustion_log_cannot_be_used_as_a_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.log"
            path.write_text("BENCHMARK INVALID: evidence queue exhausted", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "failed benchmark"):
                fabfile._parse_log(path)

    def test_diagnostics_and_build_metadata_survive_parsing(self):
        text = '''THEMIS BUILD {"revision":"abc", "modified":"false"}
THEMIS DIAGNOSTICS {"elapsed_seconds":1, "replica_id":0, "batch_queue":2}
THEMIS DIAGNOSTICS {"elapsed_seconds":2, "replica_id":0, "batch_queue":3}
Measurement Duration: 2s
Gamma Semantics: Themis all-replica premise
Total Submitted: 200
Total Finalized: 198
Average TPS: 99.00
Actual Offered Rate: 100.00
Locally Failed Transaction Send Attempts: 0
Mean Completed-Transaction Latency: 20ms
Latency Samples: 198
Outstanding: 2
Completion Ratio: 0.99
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.log"
            path.write_text(text, encoding="utf-8")
            result = fabfile._parse_log(path)
        self.assertEqual(result["build_metadata"][0]["revision"], "abc")
        self.assertEqual([sample["batch_queue"] for sample in result["diagnostics_samples"]], [2, 3])
        self.assertEqual(result["average_tps"], 99)


if __name__ == "__main__":
    unittest.main()
