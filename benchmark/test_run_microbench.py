import unittest
import run_microbench as runner


class MicroCollectorTests(unittest.TestCase):
    def line(self, stage="GraphCore", suffix="", metrics="123.5 ns/op 64 B/op 2 allocs/op"):
        return f"BenchmarkThemisLocal/n=10/f=1/gamma=0.95/seed=7/history=24/cap=200/bytes=64/cycle/{stage}{suffix} 12 {metrics}"

    def test_parse_units_and_cpu_suffix(self):
        row = runner.parse_benchmarks(self.line(suffix="-1"))[0]
        self.assertEqual(row["ns_per_op"], 123.5)
        self.assertEqual(row["iterations"], 12)
        self.assertEqual(row["bytes_per_op"], 64)
        self.assertEqual(row["stage"], "GraphCore")
        self.assertEqual(runner.parse_benchmarks(self.line(metrics="2 allocs/op 1e3 ns/op 64 B/op"))[0]["ns_per_op"], 1000)

    def test_bad_results_fail(self):
        for metrics in ["2 ns/op", "NaN ns/op 1 B/op 2 allocs/op", "-1 ns/op 1 B/op 2 allocs/op", "garbage"]:
            with self.subTest(metrics=metrics), self.assertRaises(ValueError):
                runner.parse_benchmarks(self.line(metrics=metrics))

    def test_exact_completeness_and_repeats(self):
        rows = runner.parse_benchmarks("\n".join(self.line(stage) for stage in runner.STAGES))
        samples = {rows[0]["sample"]: {"candidate_available": True}}
        runner.validate_results(rows * 2, samples, 2)
        for bad in [rows[:-1], rows * 2, []]:
            with self.assertRaises(ValueError):
                runner.validate_results(bad, samples, 1)
        samples[rows[0]["sample"]]["candidate_available"] = False
        runner.validate_results(rows[:2], samples, 1)
        with self.assertRaises(ValueError):
            runner.validate_results(rows, samples, 1)

    def test_metadata_and_version(self):
        line = 'THEMIS_MICRO_SAMPLE {"sample":"x","workload_version":"themis-receipts-v1"}'
        self.assertEqual(runner.parse_samples(line)["x"]["sample"], "x")
        for text in ["", line + "\n" + line, line.replace("receipts-v1", "receipts-old")]:
            with self.assertRaises(ValueError):
                runner.parse_samples(text)

    def test_statistics_keep_process_seed_distinct(self):
        rows = []
        for process, time in [(1, 10), (1, 20), (2, 40)]:
            row = runner.parse_benchmarks(self.line())[0]
            row.update(process=process, ns_per_op=time)
            rows.append(row)
        second_seed = dict(rows[0], sample=rows[0]["sample"].replace("seed=7", "seed=19"))
        summary = runner.summarize(rows + [second_seed])
        self.assertEqual(len(summary), 2)
        observed = next(s for s in summary if s["observations"] == 3)
        self.assertEqual(observed["independent_processes"], 2)
        self.assertEqual(observed["process_mean_ns"], 27.5)
        self.assertFalse(any("ratio" in key for s in summary for key in s))

    def test_defaults_are_time_based_and_native_cap(self):
        args = runner.parser().parse_args([])
        self.assertEqual(args.benchtime, "1s")
        self.assertEqual(args.processes, 4)
        self.assertEqual(args.receipt_cap, 200)
        self.assertFalse(hasattr(args, "lo_size"))


if __name__ == "__main__":
    unittest.main()
