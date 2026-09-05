import sys
import unittest


class SupportedRuntimeTests(unittest.TestCase):
    def test_tested_runtime_is_within_the_published_support_range(self) -> None:
        self.assertGreaterEqual(sys.version_info[:2], (3, 9))
        self.assertLess(sys.version_info[:2], (3, 15))


if __name__ == "__main__":
    unittest.main()
