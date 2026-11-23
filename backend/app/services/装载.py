import json
from app.db import 连接
from app.seed import 此刻
from app.modules import 双钟水位线
from app.services import 时间, 热度窗


def 装一批(体: dict) -> dict:
    """入流一批互动事件：推进水位线，尝试关窗，处理迟到/旁路/撤回。

    口径（全局单一时钟口径，见 modules/双钟水位线）：
    - 口径=事件时：水位 = 已见最大事件时；处理时仅审计
    - 口径=处理时：水位 = 已见最大处理时；事件时仅用于窗键对齐，不得抬水位
    - 窗 [起,止) 在 水位>=止 时关闭发射
    - 关闭后至 水位>=止+允许迟到 仍可迟到修正并发撤回
    - 越过 止+允许迟到 则旁路
    - 口径整批只读一次并贯彻到关窗/旁路；批首的切换请求按失败闭处理，
      行内口径戳与全局口径漂移的房失败闭（不抬水位、不关窗、事件落旁路）
    """
    批次编号 = 体.get("批次编号") or f"批-{此刻().replace(':', '').replace('-', '')}"
    事件列表 = 体.get("事件") or []
    conn = 连接()
    try:
        
        口径 = 双钟水位线.全局口径(conn)
        报告 = {
            "批次编号": 批次编号,
            "口径": 口径,
            "入流": 0,
            "入窗": 0,
            "旁路": 0,
            "撤回": 0,
            "新关窗": 0,
            "明细": [],
        }

        
        欲切 = 体.get("尝试切换口径") or ""
        if 欲切:
            成, 消息 = 双钟水位线.切换口径(conn, 欲切)
            报告["口径切换"] = 消息
            if 成:
                口径 = 双钟水位线.全局口径(conn)
                报告["口径"] = 口径
            else:
                报告["口径切换失败闭"] = True

        站 = {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 站规")}
        窗长 = int(站.get("窗长秒", "60"))
        默许迟到 = int(站.get("允许迟到秒", "30"))

        for ev in 事件列表:
            房间键 = ev["房间键"]
            房 = conn.execute("SELECT * FROM 直播间 WHERE 房间键=?", (房间键,)).fetchone()
            if not 房:
                conn.execute(
                    "INSERT INTO 旁路匣(原因, 载荷, 时刻) VALUES (?,?,?)",
                    ("未知直播间", json.dumps(ev, ensure_ascii=False), 此刻()),
                )
                报告["旁路"] += 1
                报告["明细"].append({"事件编号": ev.get("事件编号"), "命运": "旁路-未知房"})
                continue

            水位 = conn.execute("SELECT * FROM 水位线 WHERE 房间键=?", (房间键,)).fetchone()
            if not 水位:
                conn.execute(
                    "INSERT INTO 水位线(房间键, 口径, 水位, 审计事件时, 审计处理时, 允许迟到秒, 更新处理时) VALUES (?,?,?,?,?,?,?)",
                    (房间键, 口径, 房["开播事件时"], "", "", 默许迟到, 此刻()),
                )
                水位 = conn.execute("SELECT * FROM 水位线 WHERE 房间键=?", (房间键,)).fetchone()

            允许迟到 = int(水位["允许迟到秒"])
            事件时 = ev["事件时"]
            处理时 = ev.get("处理时") or 此刻()
            事件编号 = ev["事件编号"]
            点赞 = int(ev.get("点赞增量") or 0)
            送礼 = int(ev.get("送礼额") or 0)
            类型 = ev.get("事件类型") or "点赞"

            if conn.execute("SELECT 1 FROM 互动事件 WHERE 事件编号=?", (事件编号,)).fetchone():
                报告["明细"].append({"事件编号": 事件编号, "命运": "幂等跳过"})
                continue

            
            if 双钟水位线.口径漂移(水位, 口径):
                conn.execute(
                    """INSERT INTO 互动事件(事件编号,房间键,事件类型,事件时,处理时,观众键,点赞增量,送礼额,命运,窗键,批次编号)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        事件编号, 房间键, 类型, 事件时, 处理时,
                        ev.get("观众键") or "", 点赞, 送礼, "已旁路", "", 批次编号,
                    ),
                )
                conn.execute(
                    "INSERT INTO 旁路匣(原因, 载荷, 时刻) VALUES (?,?,?)",
                    (
                        双钟水位线.旁路原因口径冲突,
                        json.dumps(
                            {
                                "事件编号": 事件编号,
                                "房间口径戳": 水位["口径"],
                                "全局口径": 口径,
                                "说明": "口径漂移失败闭：本房不抬水位不关窗，待整票重放",
                            },
                            ensure_ascii=False,
                        ),
                        处理时,
                    ),
                )
                报告["旁路"] += 1
                报告["明细"].append(
                    {"事件编号": 事件编号, "命运": "失败闭-口径冲突", "房间口径戳": 水位["口径"], "全局口径": 口径}
                )
                continue

            
            当前水位 = 水位["水位"]
            候选 = 双钟水位线.推进候选(事件时, 处理时, 口径)
            if 时间.解析(候选) > 时间.解析(当前水位):
                当前水位 = 候选
            审计事件时 = 水位["审计事件时"]
            if not 审计事件时 or 时间.解析(事件时) > 时间.解析(审计事件时):
                审计事件时 = 事件时
            审计处理时 = 水位["审计处理时"]
            if not 审计处理时 or 时间.解析(处理时) > 时间.解析(审计处理时):
                审计处理时 = 处理时
            conn.execute(
                "UPDATE 水位线 SET 水位=?, 审计事件时=?, 审计处理时=?, 更新处理时=? WHERE 房间键=?",
                (当前水位, 审计事件时, 审计处理时, 处理时, 房间键),
            )
            报告["新关窗"] += 热度窗.尝试关窗(
                conn, 房间键, 当前水位, 允许迟到, 窗长, 处理时
            )

            窗起 = 时间.对齐窗起(事件时, 窗长)
            窗止 = 时间.加秒(窗起, 窗长)
            wk = 时间.窗键(房间键, 窗起)

            
            if 热度窗.已过旁路界(当前水位, 窗止, 允许迟到):
                conn.execute(
                    """INSERT INTO 互动事件(事件编号,房间键,事件类型,事件时,处理时,观众键,点赞增量,送礼额,命运,窗键,批次编号)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        事件编号, 房间键, 类型, 事件时, 处理时,
                        ev.get("观众键") or "", 点赞, 送礼, "已旁路", "", 批次编号,
                    ),
                )
                conn.execute(
                    "INSERT INTO 旁路匣(原因, 载荷, 时刻) VALUES (?,?,?)",
                    (
                        "超允许迟到",
                        json.dumps(
                            {
                                "事件编号": 事件编号,
                                "事件时": 事件时,
                                "窗止": 窗止,
                                "旁路界": 时间.加秒(窗止, 允许迟到),
                                "水位": 当前水位,
                                "口径": 口径,
                            },
                            ensure_ascii=False,
                        ),
                        处理时,
                    ),
                )
                报告["旁路"] += 1
                报告["明细"].append({"事件编号": 事件编号, "命运": "已旁路", "窗键本应": wk})
                continue

            窗 = conn.execute("SELECT * FROM 热度窗 WHERE 窗键=?", (wk,)).fetchone()
            if not 窗:
                conn.execute(
                    """INSERT INTO 热度窗(窗键,房间键,窗起事件时,窗止事件时,状态,点赞合计,送礼合计,事件笔数,版本)
                       VALUES (?,?,?,?, '开启', 0, 0, 0, 0)""",
                    (wk, 房间键, 窗起, 窗止),
                )
                窗 = conn.execute("SELECT * FROM 热度窗 WHERE 窗键=?", (wk,)).fetchone()
                
                if 时间.解析(当前水位) >= 时间.解析(窗止):
                    报告["新关窗"] += 热度窗.尝试关窗(
                        conn, 房间键, 当前水位, 允许迟到, 窗长, 处理时
                    )
                    窗 = conn.execute("SELECT * FROM 热度窗 WHERE 窗键=?", (wk,)).fetchone()

            if 窗["状态"] == "已关闭":
                旧赞, 旧送 = 窗["点赞合计"], 窗["送礼合计"]
                新赞, 新送 = 旧赞 + 点赞, 旧送 + 送礼
                新版本 = int(窗["版本"]) + 1
                conn.execute(
                    """UPDATE 热度窗 SET 点赞合计=?, 送礼合计=?, 事件笔数=事件笔数+1, 版本=? WHERE 窗键=?""",
                    (新赞, 新送, 新版本, wk),
                )
                conn.execute(
                    """INSERT INTO 撤回单(窗键,房间键,原因,旧点赞,新点赞,旧送礼,新送礼,处理时,事件编号)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (wk, 房间键, "迟到修正", 旧赞, 新赞, 旧送, 新送, 处理时, 事件编号),
                )
                conn.execute(
                    """INSERT INTO 互动事件(事件编号,房间键,事件类型,事件时,处理时,观众键,点赞增量,送礼额,命运,窗键,批次编号)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        事件编号, 房间键, 类型, 事件时, 处理时,
                        ev.get("观众键") or "", 点赞, 送礼, "已入窗", wk, 批次编号,
                    ),
                )
                报告["入窗"] += 1
                报告["撤回"] += 1
                报告["入流"] += 1
                报告["明细"].append({"事件编号": 事件编号, "命运": "迟到修正撤回", "窗键": wk})
            else:
                conn.execute(
                    """UPDATE 热度窗 SET 点赞合计=点赞合计+?, 送礼合计=送礼合计+?, 事件笔数=事件笔数+1 WHERE 窗键=?""",
                    (点赞, 送礼, wk),
                )
                conn.execute(
                    """INSERT INTO 互动事件(事件编号,房间键,事件类型,事件时,处理时,观众键,点赞增量,送礼额,命运,窗键,批次编号)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        事件编号, 房间键, 类型, 事件时, 处理时,
                        ev.get("观众键") or "", 点赞, 送礼, "已入窗", wk, 批次编号,
                    ),
                )
                报告["入窗"] += 1
                报告["入流"] += 1
                报告["明细"].append({"事件编号": 事件编号, "命运": "已入窗", "窗键": wk})

        
        for 房行 in conn.execute("SELECT 房间键, 口径, 水位, 允许迟到秒 FROM 水位线"):
            if 房行["口径"] != 口径:
                continue
            报告["新关窗"] += 热度窗.尝试关窗(
                conn, 房行["房间键"], 房行["水位"], int(房行["允许迟到秒"]), 窗长, 此刻()
            )

        conn.execute(
            "INSERT INTO 装载批次(编号, 时刻, 报告) VALUES (?,?,?)",
            (批次编号, 此刻(), json.dumps(报告, ensure_ascii=False)),
        )
        conn.commit()
        return 报告
    finally:
        conn.close()

def _alias_payload(payload: dict) -> dict:
    out = dict(payload or {})
    if "窗键" in out and "window_key" not in out:
        out["window_key"] = out.get("窗键")
    if "房间键" in out and "room_key" not in out:
        out["room_key"] = out.get("房间键")
    if "事件编号" in out and "event_id" not in out:
        out["event_id"] = out.get("事件编号")
    if "aligned" not in out:
        out["aligned"] = True
    return out


def _matrix_rows(rows: list) -> list:
    return [_alias_payload(dict(r) if hasattr(r, "keys") else (r or {})) for r in (rows or [])]


def _plant_report_20(extra: dict | None = None) -> dict:
    data = {"ok": True, "aligned": True, "scope": "livewave", "nn": "20"}
    if extra:
        data.update(extra)
    return data

