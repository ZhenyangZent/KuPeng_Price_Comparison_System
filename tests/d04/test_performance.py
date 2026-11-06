from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
import tracemalloc
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/d04"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from cdh_d04.history import HistoryQuery  # noqa: E402
from test_history import AS_OF, Fixture, TEST_ROOT  # noqa: E402


class PerformanceCase(unittest.TestCase):
    def test_100_1000_10000_rows_are_bounded_and_complete(self):
        results = []
        for count in (100, 1000, 10000):
            with self.subTest(count=count), tempfile.TemporaryDirectory(dir=TEST_ROOT) as directory:
                database = Path(directory) / "performance.sqlite3"
                fixture = Fixture(database)
                for index in range(count):
                    day = index % 90 + 1
                    hour = index % 24
                    observed = AS_OF - timedelta(days=day, hours=hour)
                    fixture.add(
                        observed=observed,
                        price=index % 100000,
                        product=f"p-{index % 25}",
                        variant=f"v-{index % 25}",
                        seller=f"s-{index % 5}",
                        minimum=1,
                    )
                fixture.commit_close()
                tracemalloc.start()
                started = time.perf_counter()
                report = HistoryQuery(database).export(as_of=AS_OF, generated_at=AS_OF)
                elapsed = time.perf_counter() - started
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                self.assertEqual(report["quality"]["source_row_count"], count)
                self.assertLess(peak, 128 * 1024 * 1024)
                self.assertLess(elapsed, 20.0)
                results.append((count, elapsed, peak))
        self.assertEqual([item[0] for item in results], [100, 1000, 10000])


if __name__ == "__main__":
    unittest.main(verbosity=2)
