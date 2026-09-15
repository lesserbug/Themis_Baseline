import unittest
from analyze_themis_mechanism import paired_ratios


class PairedRatios(unittest.TestCase):
    def row(self, stage, value, process="1"):
        return dict(sample="n=20/seed=1/mechanism_small", process=process, repeat="1", stage=stage, ns_per_op=value)

    def test_pair_within_process(self):
        rows = [self.row("LeaderBuildFull", 2), self.row("FollowerVerifyFull", 4),
                self.row("LeaderBuildFull", 4, "2"), self.row("FollowerVerifyFull", 2, "2")]
        self.assertEqual([r["rho"] for r in paired_ratios(rows)], [2, .5])

    def test_missing_duplicate_invalid(self):
        build = self.row("LeaderBuildFull", 2)
        for rows in ([build], [build, build], [build, self.row("FollowerVerifyFull", 0)],
                     [build, self.row("FollowerVerifyFull", "nan")]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                paired_ratios(rows)


if __name__ == "__main__":
    unittest.main()
