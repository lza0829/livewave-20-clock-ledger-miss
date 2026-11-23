import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import 夹具目录, 连接
from app.modules import 双钟水位线
from app.services import 装载, 贯验, 目录

路由 = APIRouter(prefix="/api")


class 装载请求(BaseModel):
    批次编号: str = ""
    尝试切换口径: str = ""
    事件: list = Field(default_factory=list)


class 口径请求(BaseModel):
    口径: str


@路由.get("/健康")
def 健康():
    return {
        "正常": True,
        "项目": "播浪",
        "骨架": "互动事件入流→事件时间水位线推进→热度窗关闭发射→迟到修正撤回→窗输出与撤回互证",
    }


@路由.get("/总览")
def 取总览():
    return 目录.总览()


@路由.get("/站规")
def 站规():
    conn = 连接()
    try:
        return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 站规")}
    finally:
        conn.close()


@路由.get("/直播间")
def 列直播间():
    conn = 连接()
    try:
        rooms = [dict(r) for r in conn.execute("SELECT * FROM 直播间 ORDER BY 房间键")]
        for r in rooms:
            wm = conn.execute("SELECT * FROM 水位线 WHERE 房间键=?", (r["房间键"],)).fetchone()
            r["水位线"] = dict(wm) if wm else None
        return rooms
    finally:
        conn.close()


@路由.get("/事件")
def 列事件(命运: str = ""):
    conn = 连接()
    try:
        if 命运:
            rows = conn.execute(
                "SELECT * FROM 互动事件 WHERE 命运=? ORDER BY 事件时 DESC LIMIT 200", (命运,)
            )
        else:
            rows = conn.execute("SELECT * FROM 互动事件 ORDER BY 事件时 DESC LIMIT 200")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@路由.get("/水位线")
def 列水位线():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 水位线 ORDER BY 房间键")]
    finally:
        conn.close()


@路由.get("/双钟水位")
def 双钟水位():
    """双钟水位只读接口：房间、（按口径的）事件时水位或处理时水位、口径、valid。"""
    conn = 连接()
    try:
        return 双钟水位线.双钟视图(conn)
    finally:
        conn.close()


@路由.post("/口径")
def 切口径(体: 口径请求):
    """全局时钟口径切换：失败闭——已有流数据拒绝，仅全空可原子切换。"""
    conn = 连接()
    try:
        成, 消息 = 双钟水位线.切换口径(conn, 体.口径)
        if not 成:
            raise HTTPException(409, 消息)
        conn.commit()
        return {"口径": 双钟水位线.全局口径(conn), "消息": 消息}
    finally:
        conn.close()


@路由.get("/热度窗")
def 列热度窗(状态: str = ""):
    conn = 连接()
    try:
        if 状态:
            rows = conn.execute(
                "SELECT * FROM 热度窗 WHERE 状态=? ORDER BY 窗起事件时 DESC", (状态,)
            )
        else:
            rows = conn.execute("SELECT * FROM 热度窗 ORDER BY 窗起事件时 DESC")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@路由.get("/撤回单")
def 列撤回():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 撤回单 ORDER BY 编号 DESC LIMIT 100")]
    finally:
        conn.close()


@路由.get("/旁路匣")
def 列旁路():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 旁路匣 ORDER BY 编号 DESC LIMIT 100")]
    finally:
        conn.close()


@路由.get("/批次")
def 列批次():
    conn = 连接()
    try:
        out = []
        for r in conn.execute("SELECT * FROM 装载批次 ORDER BY 时刻 DESC LIMIT 30"):
            d = dict(r)
            try:
                d["报告"] = json.loads(d["报告"])
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


@路由.post("/装载")
def 做装载(体: 装载请求):
    return 装载.装一批(体.model_dump())


@路由.post("/装载/夹具")
def 装夹具(名: str = "准时热度样例"):
    路径 = 夹具目录 / f"{名}.json"
    if not 路径.exists():
        raise HTTPException(404, f"夹具不存在:{名}")
    return 装载.装一批(json.loads(路径.read_text(encoding="utf-8")))


@路由.post("/贯验")
def 做贯验():
    return 贯验.跑贯验()


@路由.get("/贯验")
def 列贯验():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 窗贯验 ORDER BY 编号 DESC LIMIT 20")]
    finally:
        conn.close()


@路由.get("/空桩")
def 空桩():
    from app import modules

    return modules.列表()

from app.modules import 口径账本 as 账


@路由.get("/核证/口径账本")
def 取口径账本(房间键: str | None = None):
    conn = 连接()
    try:
        return 账.查账本(conn, 房间键)
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

