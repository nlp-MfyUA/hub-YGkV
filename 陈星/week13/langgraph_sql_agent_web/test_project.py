"""离线测试，需安装 requirements.txt；无需 API Key。"""

import sqlite3
import unittest
from pathlib import Path

from brains import MockBrain
from db_tools import SQLiteTools
from schemas import SQLDraft

ROOT = Path(__file__).resolve().parent


class TestSQLite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = SQLiteTools(ROOT / "chinook.db")

    def test_album_count(self):
        sql = self.db.validate("SELECT COUNT(*) AS total FROM albums")
        self.assertEqual(self.db.execute(sql).rows, [["347"]])

    def test_reject_update(self):
        with self.assertRaises(ValueError):
            self.db.validate("UPDATE albums SET Title='bad'")

    def test_unknown_table(self):
        with self.assertRaises(sqlite3.Error):
            self.db.validate("SELECT * FROM albumz")

    def test_database_readonly(self):
        with self.assertRaises(sqlite3.Error):
            with self.db.connect() as connection:
                connection.execute("DELETE FROM albums")


class TestGraph(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sql_graph import build_graph
        cls.build_graph = staticmethod(build_graph)
        cls.db = SQLiteTools(ROOT / "chinook.db")

    def run_graph(self, brain, question):
        return self.build_graph(self.db, brain, max_repairs=3).invoke(
            {"question": question, "repair_count": 0, "trace": []}
        )

    def test_album_count(self):
        state = self.run_graph(MockBrain(), "数据库里一共有多少张专辑？")
        self.assertIn("347", state["answer"])
        self.assertEqual(state["repair_count"], 0)

    def test_top_artist(self):
        state = self.run_graph(MockBrain(), "哪位歌手拥有最多专辑？")
        self.assertIn("Iron Maiden", state["answer"])
        self.assertIn("21", state["answer"])

    def test_repair_route(self):
        state = self.run_graph(
            MockBrain(inject_typo=True), "数据库里一共有多少张专辑？"
        )
        self.assertEqual(state["repair_count"], 1)
        self.assertIn("347", state["answer"])
        self.assertTrue(any("repair_sql" in item for item in state["trace"]))

    def test_stop_after_limit(self):
        class UnsafeBrain(MockBrain):
            def generate_sql(self, question, schema):
                return SQLDraft(sql="DELETE FROM albums", explanation="故意制造危险 SQL")

            def repair_sql(self, question, schema, bad_sql, error):
                return SQLDraft(sql="DELETE FROM albums", explanation="始终不修复")

        state = self.run_graph(UnsafeBrain(), "数据库里一共有多少张专辑？")
        self.assertEqual(state["repair_count"], 3)
        self.assertIn("未能完成查询", state["answer"])
        # 即使连续三次输出危险语句，数据库仍完整。
        count = self.db.execute(self.db.validate("SELECT COUNT(*) FROM albums"))
        self.assertEqual(count.rows, [["347"]])

    def test_unknown_question_stops(self):
        state = self.run_graph(MockBrain(), "明天天气如何")
        self.assertIn("离线模拟器", state["answer"])
        self.assertNotIn("sql", state)


if __name__ == "__main__":
    unittest.main(verbosity=2)
