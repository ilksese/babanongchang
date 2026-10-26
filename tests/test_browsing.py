import unittest

from babanongchang.browsing import find_browse_iteration


class FindBrowseIterationTest(unittest.TestCase):
    def test_finds_arabic_iteration(self) -> None:
        self.assertEqual(find_browse_iteration(["浏览任务", "第3次"]), 3)

    def test_accepts_spaces(self) -> None:
        self.assertEqual(find_browse_iteration(["第 2 次浏览"]), 2)

    def test_ignores_chinese_numerals(self) -> None:
        self.assertIsNone(find_browse_iteration(["第三次"]))

    def test_ignores_zero_and_missing_iteration(self) -> None:
        self.assertIsNone(find_browse_iteration(["第0次", "浏览任务"]))

    def test_uses_largest_iteration_when_page_has_multiple_matches(self) -> None:
        self.assertEqual(find_browse_iteration(["第1次", "第3次"]), 3)


if __name__ == "__main__":
    unittest.main()
