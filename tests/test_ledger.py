"""Pins the meaning of 'the last 5 hours'. Turns green when exercise 2 is done."""
import unittest

from agentshell.ledger import WINDOW_SECONDS, Ledger

NOW = 1_000_000.0


class WindowUsage(unittest.TestCase):
    def test_empty_ledger_is_zero(self):
        self.assertEqual(Ledger().window_usage("claude", NOW), 0)

    def test_sums_events_inside_the_window(self):
        led = Ledger()
        led.record("claude", 100, NOW - 60)
        led.record("claude", 250, NOW - 3600)
        self.assertEqual(led.window_usage("claude", NOW), 350)

    def test_ignores_other_backends(self):
        led = Ledger()
        led.record("claude", 100, NOW - 60)
        led.record("codex", 999, NOW - 60)
        self.assertEqual(led.window_usage("claude", NOW), 100)

    def test_event_just_inside_the_boundary_counts(self):
        led = Ledger()
        led.record("claude", 100, NOW - WINDOW_SECONDS + 1)
        self.assertEqual(led.window_usage("claude", NOW), 100)

    def test_event_exactly_on_the_boundary_does_not_count(self):
        led = Ledger()
        led.record("claude", 100, NOW - WINDOW_SECONDS)
        self.assertEqual(led.window_usage("claude", NOW), 0)

    def test_future_event_still_counts(self):
        led = Ledger()
        led.record("claude", 100, NOW + 5)
        self.assertEqual(led.window_usage("claude", NOW), 100)


class LearnedBudget(unittest.TestCase):
    def test_first_rate_limit_learns_the_window_total(self):
        led = Ledger()
        led.record("claude", 4000, NOW - 100)
        led.record("claude", 6000, NOW - 50)
        led.mark_refused("claude", NOW)
        self.assertEqual(led.state("claude").learned_budget, 10_000)
        self.assertTrue(led.cooling_down("claude", NOW + 1))
        self.assertFalse(led.cooling_down("claude", NOW + WINDOW_SECONDS))

    def test_over_budget_trips_at_ninety_percent(self):
        led = Ledger()
        led.state("claude").learned_budget = 10_000
        led.record("claude", 8_999, NOW - 10)
        self.assertFalse(led.over_budget("claude", NOW))
        led.record("claude", 1, NOW - 5)
        self.assertTrue(led.over_budget("claude", NOW))

    def test_unknown_budget_never_blocks(self):
        led = Ledger()
        led.record("claude", 10**9, NOW - 10)
        self.assertFalse(led.over_budget("claude", NOW))


if __name__ == "__main__":
    unittest.main()
