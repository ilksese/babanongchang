import unittest

import numpy as np

from babanongchang.nlgj.popups import AD_SCROLL_SECONDS, AdWait


class AdWaitTest(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((1600, 720, 3), np.uint8)

    def test_confirms_fixed_thirty_second_ad_before_scrolling(self):
        wait = AdWait(started=1.)

        self.assertFalse(wait.confirm_entry([("浏览29秒得奖励", .99, 100, 100)], 1600, 2.))
        self.assertTrue(wait.confirm_entry([("浏览30秒得奖励", .99, 100, 100)], 1600, 3.))

        wait.start_scrolling(4.)
        self.assertEqual(wait.remaining(4.), AD_SCROLL_SECONDS)
        self.assertEqual(wait.remaining(37.), 0.)

    def test_requires_reward_issued_after_fixed_scroll_before_return(self):
        wait = AdWait(started=1., entered_at=2.)
        wait.start_scrolling(3.)
        close_only = [("返回游戏", .99, 650, 100)]
        reward_and_close = [("奖励已发放", .99, 100, 100), *close_only]

        self.assertIsNone(wait.close_action(self.image, reward_and_close, 35.9))
        self.assertIsNone(wait.close_action(self.image, close_only, 36.))
        self.assertEqual(wait.close_action(self.image, reward_and_close, 36.),
                         (650, 100, "close-finished-ad"))

    def test_accepts_reward_text_with_optional_ocr_particle(self):
        wait = AdWait(started=1.)

        self.assertTrue(wait.reward_issued([("奖励已发放", .99, 100, 100)], 1600))
        self.assertTrue(wait.reward_issued([("奖励了已发放", .99, 100, 100)], 1600))

    def test_cannot_start_scrolling_before_entry_is_confirmed(self):
        wait = AdWait(started=1.)

        with self.assertRaises(RuntimeError):
            wait.start_scrolling(2.)
        self.assertIsNone(wait.remaining(3.))

    def test_repeated_start_does_not_extend_fixed_scroll(self):
        wait = AdWait(started=1., entered_at=2.)
        wait.start_scrolling(3.)
        wait.start_scrolling(10.)

        self.assertEqual(wait.remaining(36.), 0.)

    def test_low_confidence_reward_does_not_allow_return(self):
        wait = AdWait(started=1., entered_at=2.)
        wait.start_scrolling(3.)
        lines = [("奖励已发放", .84, 100, 100), ("返回游戏", .99, 650, 100)]

        self.assertIsNone(wait.close_action(self.image, lines, 36.))


if __name__ == "__main__":
    unittest.main()
