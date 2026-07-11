"""W8b/W11 AI prompt 构造：仅基于聚合统计，不传原始行数据。

- build_insight_prompt: 一次性「生成解读」消息列表
"""
from __future__ import annotations
from typing import Any

SYSTEM_PROMPT = (
    "你是脱模工艺分析助手，用中文回答，面向工艺工程师。"
    "结论要具体、可执行，不说空话套话，不编造数据，"
    "总回答控制在 800 字以内。"
)


def _fmt_num(v: Any, digits: int = 3) -> str:
    if v is None:
        return "-"
    try:
        f = float(v)
        if f != f:
            return "-"
        return f"{f:.{digits}f}"
    except Exception:
        return str(v)


def build_insight_prompt(report: dict[str, Any]) -> list[dict[str, str]]:
    meta = report.get("meta", {}) or {}
    summary = report.get("summary", {}) or {}
    univariate = report.get("univariate", {}) or {}
    rules = report.get("rules", {}) or {}
    importance = report.get("feature_importance", []) or []
    warns = list(meta.get("warnings", []) or [])

    n_total = int(meta.get("n_rows", 0) or 0)
    state_col = str(meta.get("state_col", "") or "")
    target_states = [str(s) for s in (meta.get("target_states", []) or [])]

    lines: list[str] = []
    lines.append("【工艺分析聚合报告（无原始数据）】")
    lines.append(f"状态列：{state_col}；总样本数：{n_total}。")
    lines.append("")
    lines.append("一、状态分布：")
    unreliable_states: list[str] = []
    if summary:
        for st, info in summary.items():
            cnt = int(info.get("count", 0) or 0)
            pct = float(info.get("pct", 0.0) or 0.0) * 100
            lines.append(f"  - 状态 {st}：N={cnt}，占比 {pct:.1f}%")
            if info.get("unreliable"):
                unreliable_states.append(str(st))
    else:
        lines.append("  （无）")
    if unreliable_states:
        lines.append(f"样本不足（不可靠）的状态：{', '.join(unreliable_states)}。")
    else:
        lines.append("样本不足（不可靠）的状态：无。")

    lines.append("")
    lines.append("二、区分能力 Top 3 特征（按 ANOVA F 值降序）：")
    top_feats = list(importance)[:3]
    if top_feats:
        for feat, fval in top_feats:
            try:
                fv = float(fval)
            except Exception:
                fv = None
            fv_str = "∞" if (fv is not None and fv > 1e15) else _fmt_num(fv, 2)
            lines.append(f"  - {feat}：F={fv_str}")
    else:
        lines.append("  （无）")

    focus_states = [s for s in target_states if str(s) in ("4", "5")]
    if not focus_states:
        focus_states = target_states[:2]
    lines.append("")
    lines.append("三、关键目标状态的工艺窗口与判别规则：")
    for st in focus_states:
        lines.append(f"  ▶ 目标状态 = {st}")
        uni_st = univariate.get(st, {}) if isinstance(univariate, dict) else {}
        uni_feats = uni_st.get("features", {}) if isinstance(uni_st, dict) else {}
        cnt_st = int(uni_st.get("count", 0) or summary.get(st, {}).get("count", 0) or 0)
        lines.append(f"    样本数 N={cnt_st}{'（不足，结论仅作参考）' if cnt_st < 30 else ''}")
        if uni_feats:
            ordered = [f for f, _ in top_feats if f in uni_feats]
            rest = [f for f in uni_feats.keys() if f not in ordered]
            shown = (ordered + rest)[:3]
            for feat in shown:
                info = uni_feats[feat]
                mean = info.get("mean")
                std = info.get("std")
                w1 = info.get("window_1sigma", (None, None))
                lines.append(
                    f"    - {feat}：μ={_fmt_num(mean)}，σ={_fmt_num(std)}，"
                    f"μ±σ=[{_fmt_num(w1[0])}, {_fmt_num(w1[1])}]"
                )
        else:
            lines.append("    （无可用单变量窗口）")
        st_rules = rules.get(st, []) if isinstance(rules, dict) else []
        st_rules_sorted = sorted(
            st_rules, key=lambda r: float(r.get("precision", 0.0) or 0.0), reverse=True
        )[:3]
        if st_rules_sorted:
            lines.append("    Top 3 判别规则（按 precision 降序）：")
            for i, r in enumerate(st_rules_sorted, start=1):
                conds = []
                for c in r.get("conditions", []) or []:
                    op = "≤" if c.get("op") == "<=" else ">"
                    thr = c.get("threshold")
                    conds.append(f"{c.get('feature','?')} {op} {_fmt_num(thr, 2)}")
                when = " AND ".join(conds) if conds else "（全体样本）"
                prec = float(r.get("precision", 0.0) or 0.0) * 100
                rec = float(r.get("recall", 0.0) or 0.0) * 100
                sup = int(r.get("support", 0) or 0)
                lines.append(f"      {i}) WHEN {when} THEN 状态={st} (N={sup}, P={prec:.1f}%, R={rec:.1f}%)")
        else:
            lines.append("    （无高置信规则，可能样本不足）")
    if warns:
        lines.append("")
        lines.append("四、已记录的数据/计算风险提示：")
        for w in warns[:10]:
            lines.append(f"  - {w}")
    lines.append("")
    lines.append("请基于以上聚合统计给出：")
    lines.append("1) 稳定区工艺窗口总结（重点参考指数=4 的 μ±σ 区间）；")
    lines.append("2) 区分指数=4 与 指数=5 的关键特征及阈值建议；")
    lines.append("3) 当前数据/模型的风险点与样本不足说明；")
    lines.append("4) 下一步可执行建议（数据补充、参数调优、工艺试验方向）。")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]
