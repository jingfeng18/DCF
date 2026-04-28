"""
报告生成器

将 DCF 估值结果输出为 HTML 和 Markdown 格式。
"""
import os
from datetime import datetime
from typing import Dict, Optional


class ReportGenerator:
    """估值报告生成器"""

    def __init__(self, template_dir: str = None):
        if template_dir is None:
            template_dir = os.path.join(os.path.dirname(__file__), "template.html")
        self.template_path = template_dir

    def _load_template(self) -> str:
        """加载 HTML 模板"""
        if os.path.exists(self.template_path):
            with open(self.template_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def _build_distribution_bars(self, mc: Dict) -> str:
        """构建 CSS 柱状图 HTML"""
        bins = mc.get("histogram_bins", [])
        counts = mc.get("histogram_counts", [])
        if not bins or not counts:
            return "<div style='color:#999;'>暂无数据</div>"

        max_count = max(counts)
        if max_count == 0:
            return "<div style='color:#999;'>暂无数据</div>"

        bar_max_height = 150
        bars = []
        for bin_val, count in zip(bins, counts):
            h = max(4, int(count / max_count * bar_max_height))
            bars.append(
                f'<div class="dist-bar-wrap">'
                f'<div class="dist-bar" style="height:{h}px;"></div>'
                f'<div class="dist-bar-label">{bin_val:.0f}</div>'
                f'</div>'
            )
        return "\n".join(bars)

    def generate_html(self, result: Dict, output_path: str):
        """生成 HTML 报告"""
        w = result.get("wacc_details", {})
        mc = result.get("monte_carlo", {})

        # ===== MC 统计量 =====
        mc_median = f"{mc.get('median_price', 0):.2f}"
        mc_std = f"{mc.get('std_price', 0):.2f}"
        p = mc.get("percentiles", {})
        p5_v = f"{p.get('p5', 0):.2f}"
        p10_v = f"{p.get('p10', 0):.2f}"
        p25_v = f"{p.get('p25', 0):.2f}"
        p75_v = f"{p.get('p75', 0):.2f}"
        p90_v = f"{p.get('p90', 0):.2f}"
        p95_v = f"{p.get('p95', 0):.2f}"
        ci_range_str = f"{p5_v} ~ {p95_v}"
        prob_upside = mc.get("prob_upside_pct", "N/A")
        dist_bars = self._build_distribution_bars(mc)

        # 置信带位置
        mc_min = mc.get("min_price", 0)
        mc_max = mc.get("max_price", 0)
        mc_mean = mc.get("mean_price", 0)
        p5_v_float = p.get("p5", 0)
        p95_v_float = p.get("p95", 0)
        full_range = mc_max - mc_min
        if full_range > 0:
            ci_left = (p5_v_float - mc_min) / full_range * 100
            ci_width = (p95_v_float - p5_v_float) / full_range * 100
            mean_pct = (mc_mean - mc_min) / full_range * 100
        else:
            ci_left, ci_width, mean_pct = 0, 100, 50

        # ===== 报告头部信息 =====
        ts_code = result.get("ts_code", "N/A")
        company_name = result.get("company_name", ts_code)
        report_date = result.get("report_date", datetime.now().strftime("%Y-%m-%d"))
        current_price = result.get("current_price", 0)
        implied_price = result.get("implied_price", 0)
        upside = result.get("upside_pct", "N/A")
        recommendation = "买入" if result.get("upside", 0) > 0.15 else (
            "持有" if result.get("upside", 0) > 0 else "卖出"
        )
        risk_level = "低" if result.get("wacc", 0) < 0.08 else (
            "中" if result.get("wacc", 0) < 0.12 else "高"
        )

        upside_val = result.get("upside", 0)
        rec_class = "buy" if upside_val > 0.15 else ("hold" if upside_val > 0 else "sell")
        upside_cls = "upside-up" if upside_val >= 0 else "upside-down"

        template = self._load_template()
        if not template:
            template = self._default_html_template()

        replacements = {
            "{{COMPANY_NAME}}": company_name,
            "{{TS_CODE}}": ts_code,
            "{{REPORT_DATE}}": report_date,
            "{{CURRENT_PRICE}}": f"{current_price:.2f}",
            "{{IMPLIED_PRICE}}": f"{implied_price:.2f}",
            "{{UPSIDE}}": upside,
            "{{UPSIDE_CLASS}}": upside_cls,
            "{{RECOMMENDATION}}": recommendation,
            "{{REC_CLASS}}": rec_class,
            "{{RISK_LEVEL}}": risk_level,
            "{{CI_RANGE}}": ci_range_str,
            "{{PROB_UPSIDE}}": prob_upside,
            "{{MC_MEDIAN}}": mc_median,
            "{{MC_STD}}": mc_std,
            "{{P5_VAL}}": p5_v,
            "{{P10_VAL}}": p10_v,
            "{{P25_VAL}}": p25_v,
            "{{P75_VAL}}": p75_v,
            "{{P90_VAL}}": p90_v,
            "{{P95_VAL}}": p95_v,
            "{{CI_LEFT}}": f"{ci_left:.1f}",
            "{{CI_WIDTH}}": f"{ci_width:.1f}",
            "{{MEAN_PCT}}": f"{mean_pct:.1f}",
            "{{DIST_BARS}}": dist_bars,
            "{{WACC}}": f"{result.get('wacc', 0):.2%}",
            "{{COST_OF_EQUITY}}": f"{w.get('cost_of_equity', 0):.2%}",
            "{{COST_OF_DEBT}}": f"{w.get('cost_of_debt', 0):.2%}",
            "{{AFTER_TAX_COST_OF_DEBT}}": f"{w.get('after_tax_cost_of_debt', 0):.2%}",
            "{{DEBT_WEIGHT}}": f"{w.get('debt_weight', 0):.2%}",
            "{{EQUITY_WEIGHT}}": f"{w.get('equity_weight', 0):.2%}",
            "{{BETA}}": f"{w.get('beta', 0):.2f}",
            "{{RISK_FREE_RATE}}": f"{w.get('risk_free_rate', 0):.2%}",
            "{{EQUITY_RISK_PREMIUM}}": f"{w.get('equity_risk_premium', 0):.2%}",
            "{{REC_CLASS}}": rec_class,
            "{{CURRENT_YEAR}}": str(datetime.now().year),
        }

        html = template
        for key, val in replacements.items():
            html = html.replace(key, str(val))

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        return output_path

    def _default_html_template(self) -> str:
        """内建默认 HTML 模板（当 template.html 不存在时使用）"""
        return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DCF 估值报告 - {{COMPANY_NAME}}</title>
<style>
  :root { --primary: #1a4b8c; --success: #0f9d58; --danger: #d93025; --bg: #f5f6f8; --card: #fff; --text-secondary: #5f6368; --border: #e0e3e6; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: var(--bg); color: #202124; padding: 20px; }
  .container { max-width: 1000px; margin: 0 auto; }
  .header { background: linear-gradient(135deg, #1a4b8c, #2d7bcb); color: #fff; padding: 32px; border-radius: 12px; margin-bottom: 24px; }
  .header h1 { font-size: 22px; margin-bottom: 4px; }
  .header-grid { display: flex; gap: 16px; margin-top: 16px; flex-wrap: wrap; }
  .header-item { background: rgba(255,255,255,0.15); padding: 12px 20px; border-radius: 8px; flex: 1; min-width: 120px; text-align: center; }
  .header-item .label { font-size: 12px; opacity: 0.8; }
  .header-item .value { font-size: 20px; font-weight: 700; }
  .card { background: var(--card); border-radius: 12px; padding: 24px; margin-bottom: 20px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
  .card h2 { font-size: 18px; margin-bottom: 16px; border-bottom: 2px solid var(--primary); color: var(--primary); }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { padding: 10px 14px; text-align: right; border-bottom: 1px solid var(--border); }
  th { background: #f1f3f4; font-weight: 600; color: var(--text-secondary); }
  td:first-child, th:first-child { text-align: left; }
  .footer { text-align: center; color: var(--text-secondary); font-size: 12px; padding: 20px; }
  .dist-chart { display: flex; align-items: flex-end; height: 160px; gap: 6px; margin: 16px 0; }
  .dist-bar-wrap { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; }
  .dist-bar { width: 100%; border-radius: 4px 4px 0 0; min-height: 4px; background: linear-gradient(180deg, #2d7bcb, #1a4b8c); }
  .dist-bar-label { font-size: 10px; color: var(--text-secondary); margin-top: 6px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>DCF 估值报告</h1>
    <div class="subtitle">{{COMPANY_NAME}} ({{TS_CODE}}) | {{REPORT_DATE}}</div>
    <div class="header-grid">
      <div class="header-item"><div class="label">当前股价</div><div class="value">{{CURRENT_PRICE}} 元</div></div>
      <div class="header-item"><div class="label">目标股价</div><div class="value">{{IMPLIED_PRICE}} 元</div></div>
      <div class="header-item"><div class="label">上涨空间</div><div class="value">{{UPSIDE}}</div></div>
      <div class="header-item"><div class="label">置信区间</div><div class="value">{{CI_RANGE}}</div></div>
    </div>
  </div>
  <div class="card"><h2>蒙特卡洛估值分布</h2>{{DIST_BARS}}</div>
  <div class="card"><h2>WACC 明细</h2><table>
    <tr><th>参数</th><th>数值</th><th>说明</th></tr>
    <tr><td>无风险利率</td><td>{{RISK_FREE_RATE}}</td><td style="font-size:12px;color:var(--text-secondary);">10 年期国债收益率</td></tr>
    <tr><td>ERP</td><td>{{EQUITY_RISK_PREMIUM}}</td><td style="font-size:12px;color:var(--text-secondary);">市场超额回报</td></tr>
    <tr><td>Beta</td><td>{{BETA}}</td><td style="font-size:12px;color:var(--text-secondary);">系统性风险</td></tr>
    <tr><td>Ke</td><td>{{COST_OF_EQUITY}}</td><td style="font-size:12px;color:var(--text-secondary);">股东必要回报率</td></tr>
    <tr><td>WACC</td><td>{{WACC}}</td><td style="font-size:12px;color:var(--text-secondary);">加权平均资本成本</td></tr>
  </table></div>
  <div class="footer"><p>DCF Valuation Engine | {{CURRENT_YEAR}}</p></div>
</div>
</body>
</html>"""

    def generate_markdown(self, result: Dict) -> str:
        """生成 Markdown 报告"""
        w = result.get("wacc_details", {})
        proj = result.get("projections", [])
        mc = result.get("monte_carlo", {})
        ts_code = result.get("ts_code", "N/A")
        company_name = result.get("company_name", ts_code)
        report_date = result.get("report_date", datetime.now().strftime("%Y-%m-%d"))

        lines = []
        lines.append(f"# DCF 估值报告：{company_name} ({ts_code})")
        lines.append(f"**报告日期：{report_date}**")
        lines.append("")

        # ===== 核心估值摘要 =====
        lines.append("## 核心估值摘要")
        lines.append("")
        lines.append(f"| 指标 | 数值 |")
        lines.append(f"| --- | --- |")
        lines.append(f"| 当前股价 | {result.get('current_price', 0):.2f} 元 |")
        lines.append(f"| 目标股价（MC均值） | {result.get('implied_price', 0):.2f} 元 |")
        lines.append(f"| 上涨空间 | {result.get('upside_pct', 'N/A')} |")
        lines.append(f"| 投资建议 | {self._recommendation(result.get('upside', 0))} |")
        lines.append(f"| 风险等级 | {self._risk_level(result.get('wacc', 0))} |")
        if mc and "percentiles" in mc:
            p = mc["percentiles"]
            lines.append(f"| 90% 置信区间 | {p['p5']:.2f} ~ {p['p95']:.2f} 元 |")
            lines.append(f"| 上涨概率 | {mc.get('prob_upside_pct', 'N/A')} |")
        lines.append("")

        # ===== 蒙特卡洛 =====
        if mc and "percentiles" in mc:
            lines.append("## 蒙特卡洛模拟（主估值方法）")
            lines.append("")
            p = mc["percentiles"]
            lines.append(f"- 模拟次数: {mc.get('n_simulations', 0)}")
            lines.append(f"- 均值（目标价）: {mc.get('mean_price', 0):.2f} 元")
            lines.append(f"- 中位数: {mc.get('median_price', 0):.2f} 元")
            lines.append(f"- 标准差: {mc.get('std_price', 0):.2f} 元")
            lines.append(f"- 上涨概率: {mc.get('prob_upside_pct', 'N/A')}")
            lines.append(f"- 上涨超 15% 概率: {mc.get('prob_upside_15pct_pct', 'N/A')}")
            lines.append("")
            lines.append("| 分位 | P5 | P10 | P25 | P50 | P75 | P90 | P95 |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
            lines.append(f"| 股价 | {p['p5']:.2f} | {p['p10']:.2f} | {p['p25']:.2f} | {p['p50']:.2f} | {p['p75']:.2f} | {p['p90']:.2f} | {p['p95']:.2f} |")
            lines.append("")
            lines.append("```")
            lines.append(self._build_histogram_text(mc))
            lines.append("```")
            lines.append("")

        # ===== 情景分析 =====
        scenarios = result.get("scenarios", {})
        if scenarios:
            lines.append("## 情景分析")
            lines.append("")
            header = "| 指标 | 悲观情景 | 基准情景 | 乐观情景 |"
            sep = "| --- | --- | --- | --- |"
            lines.append(header)
            lines.append(sep)
            indicators = [
                ("隐含股价", "implied_price", "{:.2f} 元"),
                ("企业价值", "enterprise_value", "{:,.0f}"),
                ("股权价值", "equity_value", "{:,.0f}"),
                ("WACC", "wacc", "{:.2%}"),
            ]
            for label, key, fmt in indicators:
                vals = []
                for sc_name in ["bear", "base", "bull"]:
                    if sc_name in scenarios:
                        v = scenarios[sc_name].get(key, 0)
                        vals.append(fmt.format(v) if isinstance(v, (int, float)) else str(v))
                    else:
                        vals.append("N/A")
                lines.append(f"| {label} | {vals[0]} | {vals[1]} | {vals[2]} |")
            lines.append("")

        # ===== FCFF 明细 =====
        lines.append("## FCFF 预测与贴现")
        lines.append("")
        lines.append(f"| 年份 | FCFF | 现值 | FCFF/收入 |")
        lines.append(f"| --- | --- | --- | --- |")
        short_term_g = result.get("short_term_growth", 0)
        base_revenue = result.get("revenue", 0)
        for p in proj:
            year = p["year"]
            rev_t = base_revenue * (1 + short_term_g) ** year
            ratio = p["fcff"] / rev_t if rev_t > 0 else 0
            lines.append(f"| {year} | {p['fcff']:,.2f} | {p['pv_fcff']:,.2f} | {ratio:.2%} |")
        lines.append(f"| FCFF 现值合计 | | {result.get('pv_fcff_sum', 0):,.2f} | |")
        lines.append(f"| 终值现值 | | {result.get('pv_terminal_value', 0):,.2f} | |")
        lines.append(f"| **企业价值** | | **{result.get('enterprise_value', 0):,.2f}** | |")
        lines.append("")

        # ===== WACC 明细 =====
        lines.append("## WACC 计算明细")
        lines.append("")
        lines.append(f"| 参数 | 数值 |")
        lines.append(f"| --- | --- |")
        lines.append(f"| 无风险利率 | {w.get('risk_free_rate', 0):.2%} |")
        lines.append(f"| 股权风险溢价 | {w.get('equity_risk_premium', 0):.2%} |")
        lines.append(f"| Beta | {w.get('beta', 0):.2f} |")
        lines.append(f"| 股权成本 (Ke) | {w.get('cost_of_equity', 0):.2%} |")
        lines.append(f"| 债务成本 (Kd) | {w.get('cost_of_debt', 0):.2%} |")
        lines.append(f"| 税后债务成本 | {w.get('after_tax_cost_of_debt', 0):.2%} |")
        lines.append(f"| 债务权重 | {w.get('debt_weight', 0):.2%} |")
        lines.append(f"| 股权权重 | {w.get('equity_weight', 0):.2%} |")
        lines.append(f"| **WACC** | **{result.get('wacc', 0):.2%}** |")
        lines.append("")

        lines.append("---")
        lines.append("*本报告基于公开数据和定量模型生成，仅供参考，不构成投资建议。*")

        return "\n".join(lines)

    def _build_histogram_text(self, mc: Dict) -> str:
        """从蒙特卡洛结果构建文本直方图"""
        bins = mc.get("histogram_bins", [])
        counts = mc.get("histogram_counts", [])
        if not bins or not counts:
            return "暂无数据"

        max_count = max(counts)
        if max_count == 0:
            return "暂无数据"

        bar_max = 20
        lines = []
        for bin_val, count in zip(bins, counts):
            bar_len = max(1, int(count / max_count * bar_max))
            bar = "█" * bar_len
            lines.append(f"{bin_val:>8.2f} |{bar} {count}")
        return "\n".join(lines)

    def _recommendation(self, upside: float) -> str:
        if upside > 0.15:
            return "买入"
        elif upside > 0:
            return "持有"
        return "卖出"

    def _risk_level(self, wacc: float) -> str:
        if wacc < 0.08:
            return "低"
        elif wacc < 0.12:
            return "中"
        return "高"
