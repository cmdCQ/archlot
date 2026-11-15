import unittest

from agent.effort import DEFAULT, HIGH, LOW, Effort
from core.contracts import fail, ok
from core.llm import build_body


def action():
    return ok("done", meta={"kind": "act", "effect": "sent"})


def observe():
    return ok("seen", meta={"kind": "observe"})


class EffortTest(unittest.TestCase):
    def test_disabled_stays_default(self):
        e = Effort(enabled=False)
        for _ in range(5):
            e.note_batch([action()])
        self.assertEqual(e.next_level()[0], DEFAULT)

    def test_three_pure_action_batches_lower_effort(self):
        e = Effort(enabled=True, low_after=3)
        self.assertEqual(e.note_batch([action()])[0], DEFAULT)
        self.assertEqual(e.note_batch([action()])[0], DEFAULT)
        level, reason = e.note_batch([action()])
        self.assertEqual(level, LOW)
        self.assertIn("简单动作", reason)
        self.assertEqual(e.next_level()[0], LOW)

    def test_observation_breaks_consecutive_actions_without_switching(self):
        e = Effort(enabled=True, low_after=3)
        e.note_batch([action()])
        e.note_batch([action()])
        self.assertEqual(e.note_batch([observe()])[0], DEFAULT)
        e.note_batch([action()])
        self.assertEqual(e.note_batch([action()])[0], DEFAULT)
        self.assertEqual(e.note_batch([action()])[0], LOW)

    def test_failure_escalates_for_two_requests(self):
        e = Effort(enabled=True, hold_requests=2)
        level, reason = e.note_batch([fail("boom", "exception")])
        self.assertEqual(level, HIGH)
        self.assertIn("失败", reason)
        self.assertEqual(e.next_level()[0], HIGH)
        self.assertEqual(e.next_level()[0], HIGH)
        level, reason = e.next_level()
        self.assertEqual(level, DEFAULT)
        self.assertIn("恢复默认", reason)

    def test_effect_failed_also_escalates(self):
        e = Effort(enabled=True)
        bad = ok("shell exit 1", meta={"kind": "act", "effect": "failed"})
        self.assertEqual(e.note_batch([bad])[0], HIGH)

    def test_denied_and_cancelled_do_not_escalate(self):
        e = Effort(enabled=True)
        self.assertEqual(e.note_batch([fail("no", "denied")])[0], DEFAULT)
        self.assertEqual(e.note_batch([fail("stop", "cancelled")])[0], DEFAULT)

    def test_failure_resets_consecutive_action_count(self):
        e = Effort(enabled=True, low_after=3)
        e.note_batch([action()])
        e.note_batch([action()])
        e.note_batch([fail("boom")])
        e.next_level()
        e.next_level()
        e.next_level()
        e.note_batch([action()])
        e.note_batch([action()])
        self.assertEqual(e.note_batch([action()])[0], LOW)


class LlmBodyTest(unittest.TestCase):
    def test_default_omits_reasoning_effort(self):
        body = build_body({"model": "m"}, [], effort=DEFAULT)
        self.assertNotIn("reasoning_effort", body)

    def test_low_and_high_are_sent(self):
        self.assertEqual(build_body({"model": "m"}, [], effort=LOW)
                         ["reasoning_effort"], LOW)
        self.assertEqual(build_body({"model": "m"}, [], effort=HIGH)
                         ["reasoning_effort"], HIGH)


if __name__ == "__main__":
    unittest.main()
