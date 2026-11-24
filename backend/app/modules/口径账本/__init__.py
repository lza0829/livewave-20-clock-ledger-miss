"""口径账本：时钟口径的唯一权威，接管此后一切抬升与关窗。

设计取舍（全局只贯彻一种）——强制切换重放：
- 首次选定口径时同票写入（房间、口径、生效水位、账本世代），账本世代即钟的锁。
- 水位写闸、关窗扫描、旁路界只吃账本现行口径与本房账本世代，禁止回读站规另算一套。
- 改钟必须同票：作废旧账本（状态=已作废）→ 按新钟重放未关闭边界（已关闭窗
  结论冻结、不得回溯）→ 写新世代账本与站规，整票同成败；禁止只改站规字段就换钟。
- 无新账本世代不得产生任何关闭结论；同一时刻只允许一套账本世代在写。

硬约束（在 查账本/钉账/改钟重放/装载 中强制）：
1. 禁止选定成功而账本口径空（空壳世代一律 valid=false 且不被采信）。
2. 禁止无新账本世代却两套钟混出关闭结论（关窗行带账本世代戳，世代只能前进）。
3. 改钟与关窗扫描并发时整票同成败（SQLite 写事务串行化 + busy 等待，冲突即回滚）。
"""
from app.services import 时间, 热度窗

状态 = "已实现"

口径事件时 = "事件时"
口径处理时 = "处理时"
口径集 = (口径事件时, 口径处理时)

账本现行 = "现行"
账本作废 = "已作废"

旁路原因口径冲突 = "口径冲突失败闭"


class 账本冲突(Exception):
    """账本硬约束被触发：整票失败闭。"""


def _行(conn, sql, args=()):
    return conn.execute(sql, args).fetchone()


def 现行账本行(conn, 房间键: str | None = None):
    """某房现行世代行（无则 None）。空口径空壳不算现行。"""
    if 房间键 is None:
        return _行(
            conn,
            "SELECT * FROM 口径账本 WHERE 状态=? AND 口径!='' ORDER BY 账本世代 DESC LIMIT 1",
            (账本现行,),
        )
    return _行(
        conn,
        "SELECT * FROM 口径账本 WHERE 房间键=? AND 状态=? AND 口径!='' ORDER BY 账本世代 DESC LIMIT 1",
        (房间键, 账本现行),
    )


def 下一世代(conn) -> int:
    行 = _行(conn, "SELECT COALESCE(MAX(账本世代),0) AS g FROM 口径账本")
    return int(行["g"] if 行 else 0) + 1


def 全局口径(conn) -> str:
    """权威口径只采信账本现行世代；系统全空（尚未选定）才回退站规默认钟。"""
    行 = 现行账本行(conn)
    if 行 and 行["口径"] in 口径集:
        return 行["口径"]
    规 = _行(conn, "SELECT 值 FROM 站规 WHERE 键='时钟口径'")
    值 = 规["值"] if 规 else 口径事件时
    return 值 if 值 in 口径集 else 口径事件时


def 现行口径(conn, 房间键: str = "") -> str:
    """兼容旧调用方：优先账本，缺省回退站规。"""
    行 = 现行账本行(conn, 房间键 or None)
    if 行 and 行["口径"] in 口径集:
        return 行["口径"]
    规 = _行(conn, "SELECT 值 FROM 站规 WHERE 键='时钟口径'")
    值 = 规["值"] if 规 else 口径事件时
    return 值 if 值 in 口径集 else 口径事件时


def 钉账(conn, 房间键: str, 口径: str, 生效水位: str, 批号: str, 时刻: str, 世代: int | None = None):
    """同票落一版现行账本。硬约束：口径与生效水位禁止空白，世代只能前进。"""
    if 口径 not in 口径集:
        raise 账本冲突(f"禁止选定成功而账本口径空/非法:{口径!r}")
    if not 生效水位:
        raise 账本冲突("禁止账本生效水位空白")
    旧 = 现行账本行(conn, 房间键)
    if 旧:
        raise 账本冲突(f"房{房间键}已有现行世代{旧['账本世代']}，改钟须走强制切换重放")
    世代 = int(世代) if 世代 is not None else 下一世代(conn)
    conn.execute(
        "INSERT INTO 口径账本(房间键,口径,生效水位,账本世代,批号,时刻,状态) VALUES (?,?,?,?,?,?,?)",
        (房间键, 口径, 生效水位, 世代, 批号, 时刻, 账本现行),
    )
    return 世代


def 确保房账本(conn, 房间键: str, 口径: str, 生效水位: str, 批号: str, 时刻: str) -> int:
    """首次选定口径时同票钉账；已存在则只核校，绝不空写。"""
    行 = 现行账本行(conn, 房间键)
    if 行:
        if 行["口径"] != 口径:
            raise 账本冲突(
                f"房{房间键}账本口径={行['口径']} 与全局口径={口径} 漂移，本房失败闭"
            )
        return int(行["账本世代"])
    return 钉账(conn, 房间键, 口径, 生效水位, 批号, 时刻)


def _作废旧世代(conn, 房间键: str) -> None:
    conn.execute(
        "UPDATE 口径账本 SET 状态=? WHERE 房间键=? AND 状态=?",
        (账本作废, 房间键, 账本现行),
    )


def _重放一房(conn, 房间键: str, 新口径: str, 新世代: int, 批号: str, 时刻: str, 窗长: int) -> dict:
    """按新钟重放本房未关闭边界。

    已关闭窗（旧世代结论）冻结不回溯；开启窗按新水位重判关闭并盖新世代戳；
    互动事件/撤回/旁路匣等历史事实保留，重放只改水位线、开启窗状态与账本。
    """
    房 = _行(conn, "SELECT * FROM 直播间 WHERE 房间键=?", (房间键,))
    if not 房:
        raise 账本冲突(f"未知房间，无法重放:{房间键}")
    旧 = 现行账本行(conn, 房间键)
    if 旧 and 旧["口径"] == 新口径:
        return {"房间键": 房间键, "世代": int(旧["账本世代"]), "重放": False}

    事件们 = conn.execute(
        "SELECT * FROM 互动事件 WHERE 房间键=? ORDER BY 事件编号", (房间键,)
    ).fetchall()
    新水位 = 房["开播事件时"]
    审计事件时 = ""
    审计处理时 = ""
    for ev in 事件们:
        候选 = ev["事件时"] if 新口径 == 口径事件时 else ev["处理时"]
        if not 新水位 or 时间.解析(候选) > 时间.解析(新水位):
            新水位 = 候选
        if not 审计事件时 or 时间.解析(ev["事件时"]) > 时间.解析(审计事件时):
            审计事件时 = ev["事件时"]
        if not 审计处理时 or 时间.解析(ev["处理时"]) > 时间.解析(审计处理时):
            审计处理时 = ev["处理时"]

    水位行 = _行(conn, "SELECT * FROM 水位线 WHERE 房间键=?", (房间键,))
    允许迟到 = int(水位行["允许迟到秒"]) if 水位行 else 30
    conn.execute(
        "UPDATE 水位线 SET 口径=?, 水位=?, 审计事件时=?, 审计处理时=?, 更新处理时=? WHERE 房间键=?",
        (新口径, 新水位, 审计事件时, 审计处理时, 时刻, 房间键),
    )

    _作废旧世代(conn, 房间键)
    钉账(conn, 房间键, 新口径, 新水位, 批号, 时刻, 世代=新世代)

    # 未关闭边界重判：只动开启窗，已关闭窗结论冻结；关窗行盖新账本世代戳。
    重放关窗 = 热度窗.尝试关窗(conn, 房间键, 新水位, 允许迟到, 窗长, 时刻, 账本世代=新世代)
    return {"房间键": 房间键, "世代": 新世代, "重放": True, "重放关窗": 重放关窗, "新生效水位": 新水位}


def 改钟重放(conn, 新口径: str, 批号: str, 时刻: str) -> dict:
    """强制切换重放（整票同成败，由调用方持有事务）。

    - 同口径：无操作。
    - 系统全空（无任何流数据）：只原子改站规与水位行口径戳，无物可重放。
    - 有流数据：逐房作废旧世代 → 按新钟重放未关闭边界 → 同世代写新账本，
      最后才改站规；任一步失败抛 账本冲突，调用方回滚，站规/账本/水位全不动。
    """
    if 新口径 not in 口径集:
        raise 账本冲突(f"未知时钟口径:{新口径}（可选：{'/'.join(口径集)}）")
    旧口径 = 全局口径(conn)
    if 新口径 == 旧口径:
        return {"切换": False, "消息": f"口径已是{旧口径}，未变", "房间": []}

    # 整票同成败：开头即取写锁，与装载/关窗扫描事务在锁外串行；由调用方 commit/rollback。
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")

    有流数据 = any(
        _行(conn, f"SELECT 1 FROM {t} LIMIT 1") is not None
        for t in ("互动事件", "热度窗", "撤回单", "旁路匣")
    )
    if not 有流数据:
        conn.execute("UPDATE 站规 SET 值=? WHERE 键='时钟口径'", (新口径,))
        conn.execute("UPDATE 水位线 SET 口径=?", (新口径,))
        return {"切换": True, "全空切换": True, "旧口径": 旧口径, "新口径": 新口径, "房间": []}

    窗规 = _行(conn, "SELECT 值 FROM 站规 WHERE 键='窗长秒'")
    窗长 = int(窗规["值"] if 窗规 else 60)
    新世代 = 下一世代(conn)
    房键们 = [r["房间键"] for r in conn.execute("SELECT 房间键 FROM 水位线 ORDER BY 房间键")]
    if not 房键们:
        房键们 = [r["房间键"] for r in conn.execute("SELECT 房间键 FROM 直播间 ORDER BY 房间键")]
    明细 = [_重放一房(conn, fk, 新口径, 新世代, 批号, 时刻, 窗长) for fk in 房键们]
    # 站规最后改：前面任一抛错则本行不可达，整票回滚后旧钟原样保留。
    conn.execute("UPDATE 站规 SET 值=? WHERE 键='时钟口径'", (新口径,))
    return {
        "切换": True,
        "全空切换": False,
        "旧口径": 旧口径,
        "新口径": 新口径,
        "账本世代": 新世代,
        "房间": 明细,
    }


def 尝试钉账(conn, **kwargs) -> None:
    """兼容残留调用：转发到同票钉账，禁止再落空白壳。"""
    钉账(
        conn,
        房间键=kwargs.get("房间键") or "房A",
        口径=kwargs.get("口径") or 全局口径(conn),
        生效水位=kwargs.get("生效水位") or "",
        批号=kwargs.get("批号") or "",
        时刻=kwargs.get("时刻") or "",
        世代=int(kwargs["账本世代"]) if kwargs.get("账本世代") else None,
    )


def 查账本(conn, 房间键: str | None = None) -> dict:
    """口径账本核证只读接口：账本世代链 + 硬约束核证 + 与水位/关窗协同核校。"""
    q = "SELECT * FROM 口径账本"
    args: tuple = ()
    if 房间键:
        q += " WHERE 房间键=?"
        args = (房间键,)
    q += " ORDER BY 账本世代 DESC, 编号 DESC LIMIT 50"
    rows = [dict(r) for r in conn.execute(q, args)]

    问题: list[str] = []
    # 约束1：空壳世代（口径或生效水位空白）一律核证失败。
    for r in rows:
        if not r.get("口径") or not r.get("生效水位"):
            问题.append(f"世代{r.get('账本世代')}房{r.get('房间键')}为空白壳（口径/生效水位缺字段）")

    现行 = [r for r in rows if r.get("状态") == 账本现行 and r.get("口径")]
    现行口径集 = {r["口径"] for r in 现行}
    钉死 = bool(现行)
    # 约束2：同一时刻只允许一套现行钟。
    if len(现行口径集) > 1:
        问题.append(f"现行世代并存两套钟:{sorted(现行口径集)}")

    # 协同核校：水位行口径戳/关窗行世代戳必须与账本现行世代一致。
    for r in 现行:
        w = _行(conn, "SELECT * FROM 水位线 WHERE 房间键=?", (r["房间键"],))
        if w is None:
            问题.append(f"房{r['房间键']}账本世代{r['账本世代']}无水位行")
        else:
            if w["口径"] != r["口径"]:
                问题.append(
                    f"房{r['房间键']}水位口径戳={w['口径']}漂移于账本={r['口径']}"
                )
            if w["水位"] != r["生效水位"]:
                问题.append(
                    f"房{r['房间键']}水位={w['水位']}与账本生效水位={r['生效水位']}不符"
                )
        无世代关窗 = _行(
            conn,
            "SELECT 1 FROM 热度窗 WHERE 房间键=? AND 状态='已关闭' AND (账本世代 IS NULL OR 账本世代=0) LIMIT 1",
            (r["房间键"],),
        )
        if 无世代关窗:
            问题.append(f"房{r['房间键']}存在无账本世代戳的关闭结论")

    return {
        "账本": rows,
        "钉死": 钉死,
        "采信现行站规": not 钉死,
        "现行口径": sorted(现行口径集)[0] if len(现行口径集) == 1 else (全局口径(conn) if not 钉死 else ""),
        "valid": not 问题,
        "问题": 问题,
    }
