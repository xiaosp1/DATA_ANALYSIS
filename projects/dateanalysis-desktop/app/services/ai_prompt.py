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

HEAD_TAIL_SYSTEM_PROMPT = (
    "你是脱模工艺分析助手，专门分析【机头工艺参数】对【机尾指数-s】的影响。"
    "指数-s含义：脱模后手套挂的手指数，=4为完美脱模，偏离4（挂多/挂少）都是缺陷。"
    "用中文回答，面向工艺工程师；结论具体可执行，不说空话套话，不编造数据；"
    "总回答控制在 1000 字以内，结构如下："
    "1) 核心结论（3句话以内，哪些机头参数最影响指数-s，方向是什么）"
    "2) Top 3 关键机头参数的量化分析（相关系数、理想窗口、偏离影响）"
    "3) 推荐工艺窗口（综合Top特征给出建议的参数范围）"
    "4) 风险点与下一步建议（样本不足/相关性弱/数据质量提示）"
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


def build_head_tail_prompt(report: dict[str, Any]) -> list[dict[str, str]]:
    """W12 机尾指数-s 归因 prompt。仅传聚合统计，不传原始行数据。"""
    meta = report.get("meta", {}) or {}
    tdist = report.get("target_dist", {}) or {}
    attr = list(report.get("attribution", []) or [])
    rules = list(report.get("top_rules", []) or [])
    win = report.get("overall_suggested_window", {}) or {}
    warns = list(meta.get("warnings", []) or [])

    n_rows = int(meta.get("n_rows", 0) or 0)
    target_col = str(meta.get("target_col", "[机尾]指数-s"))
    ideal = float(meta.get("ideal_value", 4.0) or 4.0)

    lines: list[str] = []
    lines.append("【机头→机尾 指数-s 归因报告（仅聚合统计，无原始行数据）】")
    lines.append(f"目标列：{target_col}；理想值：{int(ideal) if float(ideal).is_integer() else ideal}（完美脱模）；有效配对样本数 N={n_rows}。")
    pct_ideal = float(tdist.get("pct_ideal", 0.0) or 0.0) * 100
    pct_near = float(tdist.get("pct_near_ideal", 0.0) or 0.0) * 100
    mean = tdist.get("mean")
    std = tdist.get("std")
    lines.append(
        f"目标分布：均值={_fmt_num(mean)}，σ={_fmt_num(std)}，"
        f"精确等于理想的占比 {pct_ideal:.1f}%，近理想(|Δ|≤0.5)占比 {pct_near:.1f}%。"
    )
    vc = tdist.get("value_counts") or {}
    if vc:
        vc_str = ", ".join(f"{k}:{v}" for k, v in list(vc.items())[:8])
        lines.append(f"指数-s 值频次 Top：{vc_str}。")

    lines.append("")
    lines.append("一、Top 10 机头特征相关系数表（按 |Spearman| 降序）：")
    top_attr = attr[:10]
    if top_attr:
        lines.append("| 特征 | N | Pearson | Spearman | 方向 | 理想时μ±σ | 偏离时μ±σ | 推荐理想窗口 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for a in top_attr:
            feat = str(a.get("feature", ""))
            n = int(a.get("n", 0) or 0)
            pr = a.get("pearson_r")
            sr = a.get("spearman_r")
            direction = a.get("direction", "")
            mi = a.get("mean_when_ideal")
            si = a.get("std_when_ideal")
            mo = a.get("mean_when_off")
            so = a.get("std_when_off")
            wi = a.get("window_ideal") or (None, None)
            ideal_str = (
                f"{_fmt_num(mi)}±{_fmt_num(si)}"
                if mi is not None and si is not None
                else "-"
            )
            off_str = (
                f"{_fmt_num(mo)}±{_fmt_num(so)}"
                if mo is not None and so is not None
                else "-"
            )
            win_str = f"[{_fmt_num(wi[0])}, {_fmt_num(wi[1])}]" if wi[0] is not None else "-"
            lines.append(
                f"| {feat} | {n} | {_fmt_num(pr,3)} | {_fmt_num(sr,3)} | {direction} | {ideal_str} | {off_str} | {win_str} |"
            )
    else:
        lines.append("（无可用特征）")

    lines.append("")
    lines.append("二、Top 5 高近理想率单特征阈值规则（WHEN 特征≤/>X THEN 近理想率=Y%）：")
    if rules:
        for i, r in enumerate(rules[:5], start=1):
            feat = str(r.get("feature", ""))
            op = "≤" if r.get("op") == "<=" else ">"
            thr = r.get("threshold")
            n = int(r.get("n", 0) or 0)
            pct = float(r.get("pct_near_ideal", 0.0) or 0.0) * 100
            tm = r.get("target_mean")
            lines.append(
                f"  {i}) WHEN {feat} {op} {_fmt_num(thr,2)} THEN 近理想率={pct:.1f}% (N={n}, 目标均值={_fmt_num(tm,2)})"
            )
    else:
        lines.append("（未挖掘出显著规则，可能样本不足或区分度弱）")

    lines.append("")
    lines.append("三、综合建议工艺窗口（Top 3 特征理想样本 μ±σ）：")
    if win:
        for feat, info in win.items():
            lines.append(
                f"  - {feat}：推荐范围 [{_fmt_num(info.get('lo'),2)}, {_fmt_num(info.get('hi'),2)}]，中心μ={_fmt_num(info.get('mean'),2)}"
            )
    else:
        lines.append("（暂无稳定窗口）")

    if warns:
        lines.append("")
        lines.append("四、数据/计算风险提示：")
        for w in warns[:10]:
            lines.append(f"  - {w}")

    lines.append("")
    lines.append("请基于以上聚合统计给出结构化分析（按系统提示的4段式）。")

    return [
        {"role": "system", "content": HEAD_TAIL_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]
