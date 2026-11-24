import os
import sqlite3
from pathlib import Path

数据目录 = Path(os.environ.get("数据目录", Path(__file__).resolve().parent.parent / "data"))
夹具目录 = Path(os.environ.get("夹具目录", Path(__file__).resolve().parent.parent.parent / "fixtures"))
库路径 = 数据目录 / "播浪.db"


def 连接() -> sqlite3.Connection:
    数据目录.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(库路径, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    # WAL：单写多读，写事务排队拿锁，配合 busy_timeout 让改钟/关窗并发整票串行化，
    # 避免 deferred 事务读→写升级时撞锁立刻 SQLITE_BUSY 落下半截票。
    c.execute("PRAGMA journal_mode = WAL")
    # 改钟与关窗扫描并发：锁等待 10s，冲突方整票回滚而非半截写入。
    c.execute("PRAGMA busy_timeout = 10000")
    return c
