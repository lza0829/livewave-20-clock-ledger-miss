import React, { useEffect, useState } from "react";
import { 取, 递 } from "../api.js";

export default function 水位线页() {
  const [图, 设图] = useState(null);
  const [讯, 设讯] = useState("");
  const 刷 = () => 取("/双钟水位").then(设图);
  useEffect(() => { 刷(); }, []);
  const 切 = async (口径) => {
    try {
      const r = await 递("/口径", { 口径 });
      设讯(r.消息);
    } catch (e) {
      设讯(`失败闭拒绝：${e.message}`);
    }
    刷();
  };
  if (!图) return <p className="讯">加载中…</p>;
  return (
    <div>
      <h1 className="题">② 水位线</h1>
      <p className="述">
        全局<strong>单一时钟口径</strong>：口径=事件时 → 水位=已见最大事件时（处理时仅审计）；
        口径=处理时 → 水位=已见最大处理时（事件时仅对齐窗键）。规则：水位 ≥ 窗止 → 关窗发射；水位 ≥ 窗止 + 允许迟到 → 该窗拒收迟到（进旁路）。
        每只钟各算各的关窗是被禁止的——关窗/旁路只认「水位」一列。
      </p>
      <div className="提示条">
        当前全局口径：<strong>{图.全局口径}</strong>（水位即{图.全局口径 === "事件时" ? "事件时" : "处理时"}水位）。
        口径权威在账本（钉死：{String(图.账本钉死)}）：改钟走强制切换重放——同票作废旧世代、按新钟重放未关闭边界、写新世代，
        旧关闭集冻结不回溯；只改站规字段不换钟。
      </div>
      <div className="行">
        <button className="次" onClick={() => 切("事件时")}>切到事件时口径</button>
        <button className="次" onClick={() => 切("处理时")}>切到处理时口径</button>
        <button className="次" onClick={刷}>刷新水位</button>
      </div>
      {讯 && <div className="报箱 码">{讯}</div>}
      {!图.房间.length ? (
        <div className="空态">无直播间</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>房间</th><th>标题</th><th>口径戳</th><th>账本世代</th><th>水位（权威）</th><th>valid</th>
              <th>审计事件时</th><th>审计处理时</th><th>允许迟到秒</th><th>水位更新处理时</th>
            </tr>
          </thead>
          <tbody>
            {图.房间.map((w) => (
              <tr key={w.房间键}>
                <td>{w.房间键}</td><td>{w.标题}</td><td>{w.口径}</td><td>{w.账本世代 || "—"}</td>
                <td className="码">{w.水位}</td>
                <td><span className={`徽章 ${w.有效 ? "通" : "败"}`}>{w.有效 ? "有效" : "口径漂移"}</span></td>
                <td className="码">{w.审计事件时 || "—"}</td>
                <td className="码">{w.审计处理时 || "—"}</td>
                <td>{w.允许迟到秒}</td>
                <td className="码">{w.更新处理时 || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
