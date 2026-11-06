from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from tools.web_security.audit import execute_readonly, open_readonly_database

from tests.web.security.helpers import cleanup, workspace


class SqliteReadonlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = workspace()
        self.data = self.root / "approved_copy"
        self.data.mkdir()
        self.database = self.data / "observations.sqlite3"
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "CREATE TABLE observations(id TEXT PRIMARY KEY,title TEXT NOT NULL,price_twd INTEGER NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO observations VALUES(?,?,?)",
                (("p1", "Coffee", 199), ("p2", "Tea", 99)),
            )

    def tearDown(self) -> None:
        cleanup(self.root)

    def test_approved_copy_opens_readonly_and_selects(self) -> None:
        connection = open_readonly_database(self.database, allowed_root=self.data)
        try:
            rows = execute_readonly(
                connection,
                "SELECT id,title,price_twd FROM observations WHERE title LIKE ? ORDER BY id",
                ("%Coffee%",),
            )
            self.assertEqual(rows, [{"id": "p1", "title": "Coffee", "price_twd": 199}])
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("UPDATE observations SET price_twd=0")
        finally:
            connection.close()

    def test_query_injection_is_data_not_sql(self) -> None:
        connection = open_readonly_database(self.database, allowed_root=self.data)
        try:
            rows = execute_readonly(
                connection,
                "SELECT id FROM observations WHERE title=?",
                ("Coffee' OR 1=1 --",),
            )
            self.assertEqual(rows, [])
            count = execute_readonly(connection, "SELECT COUNT(*) AS count FROM observations")
            self.assertEqual(count[0]["count"], 2)
        finally:
            connection.close()

    def test_mutation_pragma_attach_comments_and_multistatement_are_denied(self) -> None:
        connection = open_readonly_database(self.database, allowed_root=self.data)
        try:
            statements = (
                "UPDATE observations SET price_twd=0",
                "PRAGMA database_list",
                "ATTACH DATABASE 'x' AS other",
                "SELECT * FROM observations; DROP TABLE observations",
                "SELECT * FROM observations -- bypass",
                "SELECT * FROM observations /* bypass */",
            )
            for statement in statements:
                with self.subTest(statement=statement):
                    with self.assertRaisesRegex(ValueError, "SQL_NOT_SELECT|SQL_UNSAFE_TOKEN"):
                        execute_readonly(connection, statement)
        finally:
            connection.close()

    def test_outside_path_and_wrong_suffix_are_denied(self) -> None:
        outside = self.root / "outside.sqlite3"
        outside.write_bytes(self.database.read_bytes())
        with self.assertRaisesRegex(ValueError, "SQLITE_PATH_OUTSIDE_ALLOWED_ROOT"):
            open_readonly_database(outside, allowed_root=self.data)
        wrong = self.data / "observations.txt"
        wrong.write_bytes(self.database.read_bytes())
        with self.assertRaisesRegex(ValueError, "SQLITE_SUFFIX_INVALID"):
            open_readonly_database(wrong, allowed_root=self.data)

    def test_row_limit_fails_closed(self) -> None:
        connection = open_readonly_database(self.database, allowed_root=self.data)
        try:
            with self.assertRaisesRegex(ValueError, "SQL_ROW_LIMIT_EXCEEDED"):
                execute_readonly(connection, "SELECT * FROM observations ORDER BY id", max_rows=1)
        finally:
            connection.close()

    def test_formal_project_database_is_not_in_approved_test_copy(self) -> None:
        formal = Path("data/d01/observations.sqlite3")
        if formal.exists():
            with self.assertRaisesRegex(ValueError, "SQLITE_PATH_OUTSIDE_ALLOWED_ROOT"):
                open_readonly_database(formal, allowed_root=self.data)


if __name__ == "__main__":
    unittest.main()
