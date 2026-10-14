import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar import copysim


class CopySim(unittest.TestCase):
    def test_late_entry_and_costs_eat_a_double(self):
        # La wallet hizo x2. Un seguidor con +17 % de entrada tardía y 1 % por lado + deslizamiento de 100 USD pierde parte.
        net = copysim.trade_net(2.0, 0.17, 1.0, 2.0, 100)
        self.assertLess(net, 1.0)
        self.assertGreater(net, 0.55)

    def test_bigger_size_means_more_slippage_and_less_return(self):
        small = copysim.trade_net(3.0, 0.1, 1.0, 2.0, 100)
        big = copysim.trade_net(3.0, 0.1, 1.0, 2.0, 5000)
        self.assertGreater(small, big)

    def test_stop_caps_the_loss_and_defines_R(self):
        pos = [[1000, 3600, 0.1, 1.0]]  # la wallet perdió el 90 %
        r = copysim.simulate(pos, 100, apply_stop=True, stop_pct=60)
        self.assertAlmostEqual(r["mean_net"], -0.6)
        self.assertAlmostEqual(r["expected_r"], -1.0)
        free = copysim.simulate(pos, 100, apply_stop=False)
        self.assertLess(free["mean_net"], -0.8)

    def test_expected_r_and_equity_curve(self):
        pos = [[3, 3600, 3.0, 1.0], [1, 3600, 0.5, 1.0], [2, 3600, 1.0, 1.0]]
        r = copysim.simulate(pos, 100, delay_s=30, apply_stop=True)
        self.assertEqual(r["n"], 3)
        self.assertEqual([c[0] for c in r["curve"]], [1, 2, 3])       # ordenada por hora de entrada
        self.assertAlmostEqual(r["curve"][-1][1], r["total_usd"])
        self.assertGreaterEqual(r["max_drawdown_usd"], 0)

    def test_forward_only_filters_by_join_time(self):
        pos = [[10, 3600, 2.0, 1.0], [200, 3600, 0.5, 1.0]]
        self.assertEqual(copysim.simulate(pos, 100, since_ts=100)["n"], 1)

    def test_empty(self):
        r = copysim.simulate([], 100)
        self.assertEqual((r["n"], r["expected_r"]), (0, None))


if __name__ == "__main__":
    unittest.main()
