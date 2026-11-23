状态 = "半截"


def 查账本(conn, 房间键: str | None = None) -> dict:
    rows = []
    try:
        q = "SELECT * FROM 口径账本"
        args: tuple = ()
        if 房间键:
            q += " WHERE 房间键=?"
            args = (房间键,)
        q += " ORDER BY 编号 DESC LIMIT 50"
        rows = [dict(r) for r in conn.execute(q, args)]
    except Exception:
        rows = []
    return {"账本": rows, "钉死": False, "采信现行站规": True, "valid": len(rows) == 0}


def 现行口径(conn, 房间键: str = "") -> str:
    row = conn.execute("SELECT 值 FROM 站规 WHERE 键=?", ("时钟口径",)).fetchone()
    return (row["值"] if row else "事件时") or "事件时"


def 尝试钉账(conn, **kwargs) -> None:
    
    try:
        conn.execute(
            "INSERT INTO 口径账本(房间键,口径,生效水位,账本世代,批号,时刻) VALUES (?,?,?,?,?,?)",
            (kwargs.get("房间键") or "房A", "", "", int(kwargs.get("账本世代") or 0), kwargs.get("批号") or "", kwargs.get("时刻") or ""),
        )
    except Exception:
        pass
