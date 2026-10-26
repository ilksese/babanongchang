import unittest

import numpy as np

from babanongchang.cli import OcrText, find_goods_entry, parse_fertilizer


def item(text: str, x: int, y: int, score: float = 0.99) -> OcrText:
    box = np.array([[x - 10, y - 5], [x + 10, y - 5], [x + 10, y + 5], [x - 10, y + 5]])
    return OcrText(text=text, score=score, box=box)


class ParseFertilizerTest(unittest.TestCase):
    def test_parses_combined_balance(self) -> None:
        items = [item("肥料68989", 360, 1150)]
        self.assertEqual(parse_fertilizer(items, (1600, 720, 3)), 68989)

    def test_ignores_product_reward(self) -> None:
        items = [item("肥料+70000", 200, 1450)]
        self.assertIsNone(parse_fertilizer(items, (1600, 720, 3)))

    def test_parses_split_balance(self) -> None:
        items = [item("肥料", 330, 1150), item("700", 390, 1150)]
        self.assertEqual(parse_fertilizer(items, (1600, 720, 3)), 700)


class FindGoodsEntryTest(unittest.TestCase):
    def test_finds_home_entry(self) -> None:
        entry = item("百县百品", 70, 350)
        self.assertIs(find_goods_entry([entry], (1600, 720, 3)), entry)

    def test_accepts_alternate_entry_text(self) -> None:
        entry = item("逛农货", 70, 350)
        self.assertIs(find_goods_entry([entry], (1600, 720, 3)), entry)

    def test_ignores_center_banner_with_same_text(self) -> None:
        entry = item("百县百品", 70, 350, score=0.90)
        banner = item("百县百品", 300, 350, score=0.99)
        self.assertIs(find_goods_entry([entry, banner], (1600, 720, 3)), entry)


if __name__ == "__main__":
    unittest.main()
