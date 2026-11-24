import React, { useEffect, useState } from "react";
import { 取 } from "../api.js";

export default function 口径账本() {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState("");
  const reload = () => {
    setErr("");
    取("/核证/口径账本").then(setRows).catch((e) => setErr(String(e.message || e)));
  };
  useEffect(() => { reload(); }, []);
  return (
    <div>
      <h1 className="题">口径账本核证</h1>
      <p className="述">
        账本是时钟口径的唯一权威：首次选定同票钉账（房间/口径/生效水位/账本世代），
        抬升、关窗扫描、旁路界只吃现行世代；改钟强制切换重放，旧世代作废、旧关闭集冻结不回溯。
      </p>
      {err && <pre className="码">{err}</pre>}
      <button className="次" onClick={reload}>刷新</button>
      {rows && (
        <div className="提示条">
          核证：{rows.valid ? "✅ valid" : "❌ 失败"}　钉死：{String(rows.钉死)}
          采信现行站规：{String(rows.采信现行站规)}　现行口径：{rows.现行口径 || "—"}
          {rows.问题?.length > 0 && (
            <span className="报箱 码">{"\n" + rows.问题.map((p) => "· " + p).join("\n")}</span>
          )}
        </div>
      )}
      <div className="段">
        <div className="段题">账本世代链（新→旧）</div>
        {!rows?.账本?.length ? (
          <div className="空态">尚无账本：系统全空未选定口径，首批事件入流时同票钉首世代。</div>
        ) : (
          <table>
            <thead>
              <tr><th>世代</th><th>房间</th><th>口径</th><th>生效水位</th><th>状态</th><th>批号</th><th>时刻</th></tr>
            </thead>
            <tbody>
              {rows.账本.map((r) => (
                <tr key={r.编号}>
                  <td>{r.账本世代}</td><td>{r.房间键}</td><td>{r.口径 || "—空壳—"}</td>
                  <td className="码">{r.生效水位 || "—空白—"}</td><td>{r.状态}</td>
                  <td>{r.批号}</td><td className="码">{r.时刻}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <pre className="码">{rows ? JSON.stringify(rows, null, 2) : "（空）"}</pre>
    </div>
  );
}
