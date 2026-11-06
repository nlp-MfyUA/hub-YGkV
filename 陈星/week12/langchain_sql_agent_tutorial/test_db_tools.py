"""离线单元测试：无需 API Key、无需 LangChain。"""
import sqlite3
import unittest
from pathlib import Path
from db_tools import SQLiteTools

ROOT = Path(__file__).resolve().parent


class TestSQLiteTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = SQLiteTools(ROOT / "chinook.db")

    def test_album_count(self):
        sql = self.db.validate("SELECT COUNT(*) FROM albums")
        self.assertEqual(self.db.execute(sql).rows, [["347"]])

    def test_join(self):
        sql = self.db.validate(
            "SELECT COUNT(*) FROM albums a JOIN artists r ON a.ArtistId = r.ArtistId"
        )
        self.assertEqual(self.db.execute(sql).rows, [["347"]])

    def test_reject_write(self):
        with self.assertRaises(ValueError):
            self.db.validate("DELETE FROM albums")

    def test_reject_multiple_statements(self):
        with self.assertRaises(ValueError):
            self.db.validate("SELECT 1; DROP TABLE albums")

    def test_keyword_in_string_is_safe(self):
        sql = self.db.validate("SELECT 'DROP TABLE' AS message")
        self.assertEqual(self.db.execute(sql).rows, [["DROP TABLE"]])

    def test_unknown_column(self):
        with self.assertRaises(sqlite3.OperationalError):
            self.db.validate("SELECT MadeUpColumn FROM albums")

    def test_readonly_at_db_level(self):
        with self.assertRaises(sqlite3.DatabaseError):
            with self.db.connect() as con:
                con.execute("DELETE FROM albums")


if __name__ == "__main__":
    unittest.main()
