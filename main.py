"""
DCF 估值报告系统 - 主入口

使用方法:
    python main.py --ts_code 600519.SH --token YOUR_TUSHARE_TOKEN
    python main.py --ts_code 600519.SH --token YOUR_TOKEN --format md --output report.md

示例:
    python main.py --ts_code 000858.SZ --token e91fa33c43f0ef8f82dea43708d22da5860d0f976e1ef95a991c1d8b
"""
import argparse
import os
import sys
import yaml
from datetime import datetime

# 解决 Windows GBK 控制台编码问题
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore

from data.tushare_client import TushareClient
from data.fetch_financials import FinancialDataFetcher
from models.wacc import WACCCalculator
from models.dcf_model import DCFModel
from models.monte_carlo import MonteCarloEngine
from report.generator import ReportGenerator


def load_config(path: str = "config/assumptions.yaml") -> dict:
    """加载假设参数配置"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_latest_close_price(client: TushareClient, ts_code: str) -> float:
    """获取最新收盘价"""
    from datetime import datetime, timedelta
    today = datetime.now().strftime("%Y%m%d")
    # 往前提30天确保有数据
    start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    df = client.get_daily(ts_code, start, today)
    if df is not None and not df.empty:
        return float(df.iloc[0]["close"])
    return 0.0


def main():
    parser = argparse.ArgumentParser(description="DCF 估值报告生成系统")
    parser.add_argument("--ts_code", required=True, help="股票代码，如 600519.SH")
    parser.add_argument("--token", default="e91fa33c43f0ef8f82dea43708d22da5860d0f976e1ef95a991c1d8b",
                        help="Tushare API token")
    parser.add_argument("--format", choices=["html", "md", "both"], default="both",
                        help="输出格式")
    parser.add_argument("--output", default=None, help="输出文件路径（不含格式时自动命名）")
    parser.add_argument("--config", default="config/assumptions.yaml", help="假设参数配置文件路径")
    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)

    # 初始化数据层
    print(f"[1/4] 初始化 Tushare 数据源...")
    client = TushareClient(args.token)
    fetcher = FinancialDataFetcher(client)

    # 拉取数据
    print(f"[2/4] 获取 {args.ts_code} 财务数据...")
    try:
        snapshot = fetcher.fetch_snapshot(args.ts_code)
    except Exception as e:
        print(f"  错误: 获取财务数据失败 - {e}")
        sys.exit(1)

    # 获取公司名称
    try:
        basic_info = client.get_stock_basic(args.ts_code)
        if basic_info is not None and not basic_info.empty:
            company_name = str(basic_info.iloc[0].get("name", args.ts_code))
        else:
            company_name = args.ts_code
    except Exception:
        company_name = args.ts_code

    # 获取最新股价
    print(f"[3/4] 获取最新行情数据...")
    close_price = get_latest_close_price(client, args.ts_code)
    snapshot["close_price"] = close_price if close_price > 0 else snapshot.get("total_mv", 0) / 1e8

    if not snapshot.get("total_mv"):
        print("  警告: 未获取到市值数据，将使用估算值")
        snapshot["total_mv"] = snapshot.get("total_equity", 0) * 2

    # 打印关键数据摘要
    print(f"  营业收入: {snapshot.get('revenue', 0)/1e8:.2f} 亿")
    print(f"  净利润: {snapshot.get('net_profit', 0)/1e8:.2f} 亿")
    print(f"  经营现金流: {snapshot.get('operating_cash_flow', 0)/1e8:.2f} 亿")
    print(f"  自由现金流: {snapshot.get('free_cash_flow', 0)/1e8:.2f} 亿")
    print(f"  总市值: {snapshot.get('total_mv', 0)/1e8:.2f} 亿")
    print(f"  最新收盘价: {close_price:.2f} 元")

    # 建模
    print(f"[4/4] 运行蒙特卡洛模拟（主估值方法）...")
    wacc_calc = WACCCalculator(
        risk_free_rate=config["risk_free_rate"],
        equity_risk_premium=config["equity_risk_premium"],
        tax_rate=config["tax_rate"],
    )
    dcf = DCFModel(
        wacc_calculator=wacc_calc,
        projection_years=config["projection_years"],
    )

    base_fcff = snapshot.get("free_cash_flow", 0)
    if base_fcff <= 0:
        print("  警告: 当期 FCFF 为负，使用经营性现金流替代")
        base_fcff = snapshot.get("operating_cash_flow", 0) * 0.7

    operating_margin = snapshot.get("operating_profit", 0) / max(snapshot.get("revenue", 1), 1)

    base_params = {
        "base_fcff": base_fcff,
        "revenue": snapshot.get("revenue", 0),
        "total_debt": snapshot.get("total_debt", 0),
        "cash": snapshot.get("cash", 0),
        "total_equity": snapshot.get("total_equity", 0),
        "beta": config["beta"],
        "debt_spread": config["debt_spread"],
        "tax_rate": config["tax_rate"],
        "short_term_growth": config["short_term_growth"],
        "perpetual_growth": config["perpetual_growth_rate"],
        "total_mv": snapshot.get("total_mv", 0),
        "close_price": close_price,
        "total_share": snapshot.get("total_share", 0),
        "projection_years": config["projection_years"],
        "risk_free_rate": config["risk_free_rate"],
        "equity_risk_premium": config["equity_risk_premium"],
        "operating_margin": operating_margin,
        "danda_to_revenue": config.get("danda_to_revenue", 0.05),
        "capex_to_revenue": config.get("capex_to_revenue", 0.06),
        "wc_increase_to_revenue": config.get("wc_increase_to_revenue", 0.03),
    }

    # 蒙特卡洛模拟（主估值方法）
    mc_config = config.get("monte_carlo", {})
    mc_engine = MonteCarloEngine(
        model=dcf,
        base_params=base_params,
        mc_config=mc_config,
        n_simulations=mc_config.get("n_simulations", 2000),
        seed=mc_config.get("random_seed", 42),
    )
    mc_result = mc_engine.run()

    p = mc_result["percentiles"]
    print(f"  均值={mc_result['mean_price']:.2f} | 标准差={mc_result['std_price']:.2f}")
    print(f"  P5={p['p5']:.2f} | P25={p['p25']:.2f} | P50={p['p50']:.2f} | P75={p['p75']:.2f} | P95={p['p95']:.2f}")
    print(f"  上涨概率={mc_result['prob_upside_pct']} (涨超15%: {mc_result['prob_upside_15pct_pct']})")

    # 目标股价 = MC 均值
    implied_price = mc_result["mean_price"]
    upside = (implied_price - close_price) / close_price if close_price > 0 else 0
    print(f"  目标股价（MC均值）: {implied_price:.2f} 元")
    print(f"  当前股价: {close_price:.2f} 元")
    print(f"  上涨空间: {upside*100:.1f}%")
    print(f"  WACC: {wacc_calc.calculate(total_debt=snapshot.get('total_debt',0), total_equity=snapshot.get('total_equity',0), beta=config['beta'], debt_spread=config['debt_spread'])['wacc']:.2%}")

    # FCFF 参考路径（确定性计算，用于报告投影表）
    result = dcf.run(
        base_fcff=base_fcff,
        revenue=snapshot.get("revenue", 0),
        total_debt=snapshot.get("total_debt", 0),
        cash=snapshot.get("cash", 0),
        total_equity=snapshot.get("total_equity", 0),
        beta=config["beta"],
        debt_spread=config["debt_spread"],
        tax_rate=config["tax_rate"],
        revenue_growth=config["short_term_growth"],
        perpetual_growth=config["perpetual_growth_rate"],
        total_mv=snapshot.get("total_mv", 0),
        close_price=close_price,
        total_share=snapshot.get("total_share", 0),
        operating_margin=operating_margin,
        danda_to_revenue=config.get("danda_to_revenue", 0.05),
        capex_to_revenue=config.get("capex_to_revenue", 0.06),
        wc_increase_to_revenue=config.get("wc_increase_to_revenue", 0.03),
    )
    result["ts_code"] = args.ts_code
    result["company_name"] = company_name
    result["report_date"] = snapshot.get("report_date", datetime.now().strftime("%Y%m%d"))
    result["revenue"] = snapshot.get("revenue", 0)
    result["net_profit"] = snapshot.get("net_profit", 0)
    result["operating_cash_flow"] = snapshot.get("operating_cash_flow", 0)
    result["roe"] = snapshot.get("roe", 0)

    # 用 MC 均值覆盖为目标股价
    result["implied_price"] = round(implied_price, 2)
    result["current_price"] = round(close_price, 2)
    result["upside"] = round(upside, 4)
    result["upside_pct"] = f"{round(upside * 100, 1)}%"
    result["monte_carlo"] = mc_result

    # 用 MC 平均 FCFF 路径替换确定性投影表
    mean_fcffs = mc_result.get("mean_fcffs", [])
    if mean_fcffs:
        wacc_rate = result.get("wacc", 0.093)
        mc_projections = []
        for t, fcff in enumerate(mean_fcffs):
            pv = fcff / (1 + wacc_rate) ** (t + 1)
            mc_projections.append({"year": t + 1, "fcff": round(fcff, 2), "pv_fcff": round(pv, 2)})
        result["projections"] = mc_projections
        result["pv_fcff_sum"] = round(sum(p["pv_fcff"] for p in mc_projections), 2)

    # 报告生成
    print(f"\n生成报告...")
    generator = ReportGenerator()

    ts_code_safe = args.ts_code.replace(".", "_")
    date_str = datetime.now().strftime("%Y%m%d")

    if args.format in ("html", "both"):
        if args.output:
            html_path = args.output
        else:
            html_path = f"report/{ts_code_safe}_dcf_report_{date_str}.html"
        os.makedirs(os.path.dirname(html_path), exist_ok=True)
        html_path = generator.generate_html(result, html_path)
        print(f"  HTML 报告: {html_path}")

    if args.format in ("md", "both"):
        md_content = generator.generate_markdown(result)
        if args.output and args.format == "md":
            md_path = args.output
        else:
            md_path = f"report/{ts_code_safe}_dcf_report_{date_str}.md"
        os.makedirs(os.path.dirname(md_path), exist_ok=True)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"  Markdown 报告: {md_path}")

    print(f"\n✓ DCF 估值报告生成完成！")


if __name__ == "__main__":
    main()
