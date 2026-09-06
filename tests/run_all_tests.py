"""
run_all_tests.py — Master test suite runner for Antigravity Telegram Bot.
Runs unit & integration tests across all components.
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def run_suite():
    loader = unittest.TestLoader()
    start_dir = str(Path(__file__).parent)
    suite = loader.discover(start_dir, pattern="test_*.py")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print(f"[OK] ALL {result.testsRun} TESTS PASSED SUCCESSFULLY!")
        print("=" * 60)
        sys.exit(0)
    else:
        print(f"[FAIL] {len(result.failures)} FAILURES, {len(result.errors)} ERRORS")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    run_suite()
