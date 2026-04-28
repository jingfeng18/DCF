"""
蒙特卡洛模拟引擎

对 FCFF 各驱动因子进行概率采样，生成隐含股价的概率分布。
"""
from typing import Dict, List, Optional
import numpy as np

from models.dcf_model import DCFModel


class MonteCarloEngine:
    """蒙特卡洛模拟引擎

    对 revenue 增长率、营业利润率、D&A/收入比、CapEx/收入比、
    营运资本/收入比 进行随机采样，运行 N 次 DCF 得到价格分布。
    """

    def __init__(
        self,
        model: DCFModel,
        base_params: Dict,
        mc_config: Dict,
        n_simulations: int = 5000,
        seed: int = 42,
    ):
        self.model = model
        self.base_params = base_params
        self.mc_config = mc_config
        self.n = n_simulations
        self.rng = np.random.default_rng(seed)

    def _sample_triangular(self, config: Dict) -> float:
        """从三角分布采样"""
        mode = config.get("mode", (config["min"] + config["max"]) / 2)
        return self.rng.triangular(config["min"], mode, config["max"])

    def _sample_normal(self, config: Dict, mean: float) -> float:
        """从正态分布采样（截断在合理范围）"""
        std = config.get("std", 0.02)
        return self.rng.normal(mean, std)

    def _sample_params(self) -> Dict:
        """从概率分布中采样一组 FCFF 驱动参数"""
        dist_config = self.mc_config.get("distributions", {})
        base_g = self.base_params.get("short_term_growth", 0.10)
        base_margin = self.base_params.get("operating_margin", 0.15)

        # 收入增长率：三角分布，mode=短期增长率
        g_cfg = dist_config.get("revenue_growth", {})
        g_cfg["mode"] = base_g
        g = self._sample_triangular(g_cfg)

        # 营业利润率：正态分布，mean=基准利润率
        margin_cfg = dist_config.get("operating_margin", {})
        margin = self._sample_normal(margin_cfg, base_margin)

        # D&A/收入比：三角分布
        danda_cfg = dist_config.get("danda_ratio", {})
        danda = self._sample_triangular(danda_cfg)

        # CapEx/收入比：三角分布
        capex_cfg = dist_config.get("capex_ratio", {})
        capex = self._sample_triangular(capex_cfg)

        # 营运资本/收入比：三角分布
        wc_cfg = dist_config.get("wc_ratio", {})
        wc = self._sample_triangular(wc_cfg)

        return {
            "revenue_growth": max(0.0, g),
            "operating_margin": max(0.0, min(margin, 0.60)),
            "danda_to_revenue": max(0.0, danda),
            "capex_to_revenue": max(0.0, capex),
            "wc_increase_to_revenue": max(0.0, wc),
        }

    def _run_single(self, params: Dict) -> Dict:
        """单次 DCF 计算（使用采样参数）"""
        debt = self.base_params.get("total_debt", 0)
        cash = self.base_params.get("cash", 0)
        tax = self.base_params.get("tax_rate", 0.25)
        g_perp = self.base_params.get("perpetual_growth", 0.03)
        total_mv = self.base_params.get("total_mv", 0)
        close_price = self.base_params.get("close_price", 0)
        total_share = self.base_params.get("total_share", 0)
        revenue = self.base_params.get("revenue", 0)

        # 计算 WACC
        wacc_result = self.model.wacc_calculator.calculate(
            total_debt=debt,
            total_equity=self.base_params.get("total_equity", 0),
            beta=self.base_params.get("beta", 1.0),
            debt_spread=self.base_params.get("debt_spread", 0.02),
        )
        wacc = wacc_result["wacc"]

        # 逐项拆解预测 FCFF
        fcffs = self.model.project_fcff(
            base_fcff=self.base_params.get("base_fcff", 0),
            revenue=revenue,
            revenue_growth=params["revenue_growth"],
            danda_to_revenue=params["danda_to_revenue"],
            capex_to_revenue=params["capex_to_revenue"],
            wc_increase_to_revenue=params["wc_increase_to_revenue"],
            tax_rate=tax,
            operating_margin=params["operating_margin"],
        )

        # 终值与贴现
        tv = self.model.calculate_terminal_value(fcffs[-1], wacc, g_perp)
        pv_fcffs = self.model.discount_cash_flows(fcffs, wacc)
        pv_tv = tv / (1 + wacc) ** self.model.projection_years
        ev = sum(pv_fcffs) + pv_tv

        # 股权价值与股价
        eq_val = self.model.calculate_equity_value(ev, debt, cash)
        shares = self.model.get_current_shares(total_mv, close_price, total_share)
        price = self.model.calculate_implied_share_price(eq_val, shares) if shares > 0 else 0

        return {
            "price": price,
            "wacc": wacc,
            "ev": ev,
            "fcffs": fcffs,
            "params": params,
        }

    def run(self) -> Dict:
        """执行蒙特卡洛模拟

        Returns:
            dict: 包含分布统计和直方图数据
        """
        prices = []
        results = []

        for i in range(self.n):
            params = self._sample_params()
            sim_result = self._run_single(params)
            prices.append(sim_result["price"])
            results.append(sim_result)

        prices_arr = np.array(prices)
        current_price = self.base_params.get("close_price", 0)

        # 百分位数
        p5, p10, p25, p50, p75, p90, p95 = np.percentile(prices_arr, [5, 10, 25, 50, 75, 90, 95])

        # 上涨概率
        prob_upside = float(np.mean(prices_arr > current_price)) if current_price > 0 else 0
        prob_upside_15 = float(np.mean(prices_arr > current_price * 1.15)) if current_price > 0 else 0

        # 直方图（10 个桶）
        hist_counts, hist_edges = np.histogram(prices_arr, bins=10)
        hist_bins = [(hist_edges[i] + hist_edges[i + 1]) / 2 for i in range(len(hist_edges) - 1)]

        # 收集每年 FCFF（用于报告平均路径）
        proj_years = self.model.projection_years
        fcff_by_year = [[] for _ in range(proj_years)]
        for r in results:
            for y in range(proj_years):
                if y < len(r.get("fcffs", [])):
                    fcff_by_year[y].append(r["fcffs"][y])

        mean_fcffs = []
        std_fcffs = []
        for y in range(proj_years):
            arr = np.array(fcff_by_year[y])
            mean_fcffs.append(float(np.mean(arr)))
            std_fcffs.append(float(np.std(arr)))

        return {
            "n_simulations": self.n,
            "mean_price": float(np.mean(prices_arr)),
            "std_price": float(np.std(prices_arr)),
            "min_price": float(np.min(prices_arr)),
            "max_price": float(np.max(prices_arr)),
            "median_price": float(p50),
            "percentiles": {
                "p5": float(p5),
                "p10": float(p10),
                "p25": float(p25),
                "p50": float(p50),
                "p75": float(p75),
                "p90": float(p90),
                "p95": float(p95),
            },
            "prob_upside": round(prob_upside, 4),
            "prob_upside_15pct": round(prob_upside_15, 4),
            "prob_upside_pct": f"{round(prob_upside * 100, 1)}%",
            "prob_upside_15pct_pct": f"{round(prob_upside_15 * 100, 1)}%",
            "histogram_bins": [round(b, 2) for b in hist_bins],
            "histogram_counts": [int(c) for c in hist_counts],
            "mean_fcffs": [round(v, 2) for v in mean_fcffs],
            "std_fcffs": [round(v, 2) for v in std_fcffs],
        }
