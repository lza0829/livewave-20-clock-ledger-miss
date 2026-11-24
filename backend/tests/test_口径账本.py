"""口径账本硬约束测试（含题面两组夹具叙事）。

甲：钉事件时账本后改站规灌流——关闭集仍按旧世代事件时；
   处理时口径须强制重放后才生效，旧关闭集冻结不回溯。
乙：改钟与关窗扫描并发——整票同成败，不得两套关闭结论并存。
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

根 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(根))

夹具目录 = 根.parent / "fixtures"


def 启新库(临时目录: str):
    """每个用例独立库：app.db.库路径 在导入时固化，须显式重绑并重载种子。"""
    os.environ["数据目录"] = 临时目录
    os.environ["夹具目录"] = str(夹具目录)
    from app import db
    db.数据目录 = Path(临时目录)
    db.库路径 = db.数据目录 / "播浪.db"
    from app.seed import 初始化库
    初始化库()


class 账本测试基类(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        启新库(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def 灌(self, 名):
        from app.services import 装载
        return 装载.装一批(json.loads((夹具目录 / f"{名}.json").read_text(encoding="utf-8")))

    def 灌体(self, 体):
        from app.services import 装载
        return 装载.装一批(体)

    def 核证(self, 房=None):
        from app.db import 连接
        from app.modules import 口径账本
        conn = 连接()
        try:
            return 口径账本.查账本(conn, 房)
        finally:
            conn.close()

    def 关闭集(self):
        from app.db import 连接
        conn = 连接()
        try:
            return {
                r["窗键"]: r["账本世代"]
                for r in conn.execute("SELECT 窗键, 账本世代 FROM 热度窗 WHERE 状态='已关闭'")
            }
        finally:
            conn.close()


class 钉账与世代锁(账本测试基类):
    def test_首次选定同票钉账无空壳(self):
        r = self.灌("双钟水位样例")
        self.assertEqual(r["口径"], "事件时")
        核 = self.核证()
        self.assertTrue(核["valid"], 核["问题"])
        self.assertTrue(核["钉死"])
        self.assertEqual(len(核["账本"]), 1)
        行 = 核["账本"][0]
        self.assertEqual(行["口径"], "事件时")
        self.assertTrue(行["生效水位"])
        self.assertEqual(行["账本世代"], 1)
        self.assertEqual(行["状态"], "现行")

    def test_关窗行必带账本世代戳(self):
        self.灌("双钟水位样例")
        for wk, g in self.关闭集().items():
            self.assertGreater(g, 0, f"{wk} 无账本世代戳")

    def test_禁止只改站规就换钟(self):
        from app.db import 连接
        self.灌("双钟水位样例")
        旧集 = self.关闭集()
        conn = 连接()
        try:
            # 越权直改站规字段：账本不接管，后续装载必须仍按旧世代事件时跑。
            conn.execute("UPDATE 站规 SET 值='处理时' WHERE 键='时钟口径'")
            conn.commit()
        finally:
            conn.close()
        # 事件时 12:02:20 不推进关窗（12:02 窗止 12:03:00）；处理时 12:07:30 若被采信才会换钟关窗。
        r = self.灌体({
            "批次编号": "批-越权改库",
            "事件": [{
                "事件编号": "Z1", "房间键": "房A", "事件类型": "点赞",
                "事件时": "2026-11-22T12:02:20Z", "处理时": "2026-11-22T12:07:30Z",
                "点赞增量": 1,
            }],
        })
        # 口径仍采信账本（事件时），未被站规带跑；关闭集相对钉账时零漂移。
        self.assertEqual(r["口径"], "事件时")
        self.assertEqual(self.关闭集(), 旧集)
        conn = 连接()
        try:
            水位 = dict(conn.execute("SELECT * FROM 水位线").fetchone())
            self.assertEqual(水位["水位"], "2026-11-22T12:02:20Z")  # 事件时抬升，非处理时 12:07:30
            self.assertEqual(水位["口径"], "事件时")
        finally:
            conn.close()
        核 = self.核证()
        self.assertTrue(核["valid"], 核["问题"])


class 强制切换重放(账本测试基类):
    def test_重放后才按处理时且旧关闭集冻结(self):
        from app.db import 连接
        self.灌("双钟水位样例")
        旧集 = self.关闭集()
        self.assertEqual(len(旧集), 2)  # 事件时下 {12:00,12:01}
        旧世代 = {g for g in 旧集.values()}
        self.assertEqual(旧世代, {1})

        # 处理时口径只能走强制切换重放。
        conn = 连接()
        try:
            from app.modules import 口径账本
            果 = 口径账本.改钟重放(conn, "处理时", 批号="测试改钟", 时刻="2026-11-24T01:00:00Z")
            conn.commit()
        finally:
            conn.close()

        self.assertTrue(果["切换"])
        self.assertFalse(果["全空切换"])
        self.assertEqual(果["账本世代"], 2)

        conn = 连接()
        try:
            旧账 = [dict(r) for r in conn.execute(
                "SELECT * FROM 口径账本 WHERE 状态='已作废'")]
            新账 = [dict(r) for r in conn.execute(
                "SELECT * FROM 口径账本 WHERE 状态='现行'")]
            self.assertEqual(len(旧账), 1)
            self.assertEqual(旧账[0]["口径"], "事件时")
            self.assertEqual(len(新账), 1)
            self.assertEqual(新账[0]["口径"], "处理时")
            # 新水位按处理时重放：D5 处理时 12:06:00 抬升。
            self.assertEqual(新账[0]["生效水位"], "2026-11-22T12:06:00Z")
            水位 = dict(conn.execute("SELECT * FROM 水位线").fetchone())
            self.assertEqual(水位["口径"], "处理时")
            self.assertEqual(水位["水位"], "2026-11-22T12:06:00Z")
        finally:
            conn.close()

        新集 = self.关闭集()
        # 旧关闭集冻结（世代1 两窗原样），新钟重放只给未关闭边界补结论（世代2）。
        self.assertIn("房A|2026-11-22T12:00:00Z", 新集)
        self.assertIn("房A|2026-11-22T12:01:00Z", 新集)
        self.assertEqual(新集["房A|2026-11-22T12:00:00Z"], 1)
        self.assertEqual(新集["房A|2026-11-22T12:01:00Z"], 1)
        self.assertEqual(新集.get("房A|2026-11-22T12:02:00Z"), 2)
        self.assertEqual(set(新集), set(旧集) | {"房A|2026-11-22T12:02:00Z"})

        核 = self.核证()
        self.assertTrue(核["valid"], 核["问题"])
        self.assertEqual(核["现行口径"], "处理时")

    def test_全空切换原子无重放(self):
        from app.db import 连接
        from app.modules import 口径账本
        conn = 连接()
        try:
            果 = 口径账本.改钟重放(conn, "处理时", 批号="全空", 时刻="2026-11-24T01:00:00Z")
            conn.commit()
        finally:
            conn.close()
        self.assertTrue(果["全空切换"])
        self.assertEqual(果["房间"], [])
        conn = 连接()
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS c FROM 口径账本").fetchone()["c"], 0)
            self.assertEqual(
                conn.execute("SELECT 值 FROM 站规 WHERE 键='时钟口径'").fetchone()["值"],
                "处理时",
            )
        finally:
            conn.close()
        # 切换后首批事件按处理时钉账。
        r = self.灌("双钟水位样例")
        self.assertEqual(r["口径"], "处理时")
        核 = self.核证()
        self.assertTrue(核["valid"])
        self.assertEqual(核["账本"][0]["口径"], "处理时")

    def test_硬约束_空壳钉账被拒(self):
        from app.modules import 口径账本
        from app.db import 连接
        conn = 连接()
        try:
            with self.assertRaises(口径账本.账本冲突):
                口径账本.钉账(conn, "房A", "", "2026-11-22T12:00:00Z", "x", "t")
            with self.assertRaises(口径账本.账本冲突):
                口径账本.钉账(conn, "房A", "事件时", "", "x", "t")
        finally:
            conn.close()


class 改钟关窗并发(账本测试基类):
    def test_并发整票同成败无双套结论(self):
        import sqlite3
        from app.db import 连接
        from app.modules import 口径账本
        from app.seed import 此刻

        self.灌("双钟水位样例")
        错误 = []
        开始 = threading.Event()

        def 装载线程():
            开始.wait()
            try:
                self.灌体({
                    "批次编号": "批-并发装",
                    "事件": [{
                        "事件编号": "C1", "房间键": "房A", "事件类型": "点赞",
                        "事件时": "2026-11-22T12:03:20Z",
                        "处理时": "2026-11-22T12:03:25Z",
                        "点赞增量": 4,
                    }],
                })
            except Exception as e:  # noqa: BLE001
                错误.append(("装载", repr(e)))

        def 改钟线程():
            开始.wait()
            conn = 连接()
            try:
                口径账本.改钟重放(conn, "处理时", 批号="并发改钟", 时刻=此刻())
                conn.commit()
            except Exception as e:  # noqa: BLE001
                conn.rollback()
                错误.append(("改钟", repr(e)))
            finally:
                conn.close()

        t1 = threading.Thread(target=装载线程)
        t2 = threading.Thread(target=改钟线程)
        t1.start(); t2.start()
        开始.set()
        t1.join(timeout=30); t2.join(timeout=30)
        self.assertFalse(t1.is_alive() or t2.is_alive())

        # 无论谁先拿锁：两票各自整票成功或整票回滚，不允许半截。
        self.assertEqual(错误, [], 错误)
        核 = self.核证()
        self.assertTrue(核["valid"], 核["问题"])

        # 全库只允许一套现行钟；每个关闭窗只挂一个世代戳。
        self.assertEqual(len({r["口径"] for r in 核["账本"] if r["状态"] == "现行"}), 1)
        关 = self.关闭集()
        self.assertTrue(all(g > 0 for g in 关.values()))
        # 世代只能前进：不存在世代戳大于现行世代的关闭行。
        现行世代 = max(r["账本世代"] for r in 核["账本"] if r["状态"] == "现行")
        self.assertTrue(all(g <= 现行世代 for g in 关.values()))

        # 账本口径与水位行、站规三者一致（无切换半截）。
        conn = 连接()
        try:
            账口径 = 口径账本.全局口径(conn)
            规 = conn.execute("SELECT 值 FROM 站规 WHERE 键='时钟口径'").fetchone()["值"]
            水位口径 = conn.execute("SELECT 口径 FROM 水位线").fetchone()["口径"]
            self.assertEqual(账口径, 规)
            self.assertEqual(账口径, 水位口径)
            # 同一窗键只有一行，无双套关闭结论并存。
            n = conn.execute("SELECT COUNT(*) AS c FROM 热度窗 WHERE 状态='已关闭'").fetchone()["c"]
            键数 = conn.execute(
                "SELECT COUNT(DISTINCT 窗键) AS c FROM 热度窗 WHERE 状态='已关闭'"
            ).fetchone()["c"]
            self.assertEqual(n, 键数)
        finally:
            conn.close()

    def test_并发锁冲突时装载重试仍整票成功(self):
        import time
        from app.db import 连接
        from app.modules import 口径账本
        from app.seed import 此刻

        self.灌("双钟水位样例")
        拿锁 = threading.Event()

        def 持锁改钟():
            conn = 连接()
            try:
                conn.execute("BEGIN IMMEDIATE")
                拿锁.set()
                time.sleep(2)  # 持写锁 2s（小于 busy_timeout 10s），期间灌入方须等待
                口径账本.改钟重放(conn, "处理时", 批号="锁内改钟", 时刻=此刻())
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        t = threading.Thread(target=持锁改钟)
        t.start()
        self.assertTrue(拿锁.wait(timeout=10))
        # 改钟事务持锁期间灌入：busy_timeout 等待锁释放，随后整票成功，按新世代口径落库。
        r = self.灌体({
            "批次编号": "批-锁等待",
            "事件": [{
                "事件编号": "C2", "房间键": "房A", "事件类型": "点赞",
                "事件时": "2026-11-22T12:04:05Z",
                "处理时": "2026-11-22T12:08:10Z",
                "点赞增量": 2,
            }],
        })
        t.join(timeout=30)
        self.assertFalse(t.is_alive())
        self.assertEqual(r["口径"], "处理时")
        self.assertTrue(self.核证()["valid"])


class 老bug库迁移(unittest.TestCase):
    def test_旧schema与空白壳迁移后核证有效(self):
        import sqlite3
        from pathlib import Path
        tmp = tempfile.mkdtemp()
        os.environ["数据目录"] = tmp
        from app import db
        db.数据目录 = Path(tmp)
        db.库路径 = db.数据目录 / "播浪.db"
        # 手工造一个 bug 期老库：无「状态」列、无「账本世代」列、带空白壳账本与已关闭窗。
        c = sqlite3.connect(db.库路径)
        c.executescript(
            """
            CREATE TABLE 站规 (键 TEXT PRIMARY KEY, 值 TEXT NOT NULL);
            INSERT INTO 站规 VALUES ('时钟口径','事件时'),('窗长秒','60'),('允许迟到秒','30');
            CREATE TABLE 直播间 (房间键 TEXT PRIMARY KEY, 标题 TEXT, 主播 TEXT, 开播事件时 TEXT, 状态 TEXT);
            INSERT INTO 直播间 VALUES ('房A','晚间热聊','主播小浪','2026-11-22T12:00:00Z','直播中');
            CREATE TABLE 水位线 (房间键 TEXT PRIMARY KEY, 口径 TEXT, 水位 TEXT, 审计事件时 TEXT, 审计处理时 TEXT, 允许迟到秒 INTEGER, 更新处理时 TEXT);
            INSERT INTO 水位线 VALUES ('房A','事件时','2026-11-22T12:02:10Z','2026-11-22T12:02:10Z','2026-11-22T12:06:00Z',30,'2026-11-22T12:06:00Z');
            CREATE TABLE 热度窗 (窗键 TEXT PRIMARY KEY, 房间键 TEXT, 窗起事件时 TEXT, 窗止事件时 TEXT, 状态 TEXT, 点赞合计 INTEGER, 送礼合计 INTEGER, 事件笔数 INTEGER, 关闭处理时 TEXT, 版本 INTEGER);
            INSERT INTO 热度窗 VALUES ('房A|2026-11-22T12:00:00Z','房A','2026-11-22T12:00:00Z','2026-11-22T12:01:00Z','已关闭',3,50,2,'2026-11-22T12:01:01Z',1);
            CREATE TABLE 互动事件 (事件编号 TEXT PRIMARY KEY, 房间键 TEXT, 事件类型 TEXT, 事件时 TEXT, 处理时 TEXT, 观众键 TEXT, 点赞增量 INTEGER, 送礼额 INTEGER, 命运 TEXT, 窗键 TEXT, 批次编号 TEXT);
            INSERT INTO 互动事件 VALUES ('E1','房A','点赞','2026-11-22T12:00:10Z','2026-11-22T12:00:11Z','观1',3,0,'已入窗','房A|2026-11-22T12:00:00Z','老批');
            CREATE TABLE 装载批次 (编号 TEXT PRIMARY KEY, 时刻 TEXT, 报告 TEXT);
            CREATE TABLE 撤回单 (编号 INTEGER PRIMARY KEY AUTOINCREMENT, 窗键 TEXT, 房间键 TEXT, 原因 TEXT, 旧点赞 INTEGER, 新点赞 INTEGER, 旧送礼 INTEGER, 新送礼 INTEGER, 处理时 TEXT, 事件编号 TEXT);
            CREATE TABLE 旁路匣 (编号 INTEGER PRIMARY KEY AUTOINCREMENT, 原因 TEXT, 载荷 TEXT, 时刻 TEXT);
            CREATE TABLE 窗贯验 (编号 INTEGER PRIMARY KEY AUTOINCREMENT, 时刻 TEXT, 事件数 INTEGER, 已关闭窗数 INTEGER, 撤回数 INTEGER, 旁路数 INTEGER, 是否通过 INTEGER, 说明 TEXT);
            CREATE TABLE 口径账本 (编号 INTEGER PRIMARY KEY AUTOINCREMENT, 房间键 TEXT, 口径 TEXT, 生效水位 TEXT, 账本世代 INTEGER, 批号 TEXT, 时刻 TEXT);
            INSERT INTO 口径账本(房间键,口径,生效水位,账本世代,批号,时刻) VALUES ('房A','','',1,'半截改钟','2026-11-23T00:00:00Z');
            """
        )
        c.commit(); c.close()

        from app.seed import 初始化库
        初始化库()  # 触发迁移
        from app.modules import 口径账本
        from app.db import 连接
        conn = 连接()
        try:
            核 = 口径账本.查账本(conn)
            self.assertTrue(核["valid"], 核["问题"])
            账 = conn.execute("SELECT * FROM 口径账本 WHERE 状态='现行'").fetchone()
            self.assertEqual(dict(账)["口径"], "事件时")
            self.assertEqual(dict(账)["账本世代"], 1)
            空壳 = conn.execute("SELECT COUNT(*) AS c FROM 口径账本 WHERE 口径=''").fetchone()["c"]
            self.assertEqual(空壳, 0)
            窗 = dict(conn.execute("SELECT * FROM 热度窗").fetchone())
            self.assertEqual(窗["账本世代"], 1)
        finally:
            conn.close()

        # 迁移后可继续灌流且整票仍按追认世代口径工作。
        from app.services import 装载
        r = 装载.装一批({
            "批次编号": "迁移后批",
            "事件": [{
                "事件编号": "M1", "房间键": "房A", "事件类型": "点赞",
                "事件时": "2026-11-22T12:02:40Z", "处理时": "2026-11-22T12:02:42Z",
                "点赞增量": 2,
            }],
        })
        self.assertEqual(r["口径"], "事件时")
        self.assertTrue(self.核证_local()["valid"])

    def 核证_local(self):
        from app.db import 连接
        from app.modules import 口径账本
        conn = 连接()
        try:
            return 口径账本.查账本(conn)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
