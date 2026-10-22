import unittest
from calc import checkout


class CheckoutTests(unittest.TestCase):
    def test_no_discount(self):
        self.assertEqual(checkout(100, 0, 8.25), 108.25)

    def test_discount_then_tax(self):
        # Business rule: discount is rounded to cents before tax is applied.
        # 1.01 - 12.5% = 0.88375 -> 0.88; then 8.25% tax -> 0.95.
        self.assertEqual(checkout(1.01, 12.5, 8.25), 0.95)

    def test_zero(self):
        self.assertEqual(checkout(0, 25, 8.25), 0.0)


if __name__ == "__main__":
    unittest.main()
