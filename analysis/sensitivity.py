"""
敏感性分析与情景分析模块

- 敏感性分析：WACC × 永续增长率 双变量矩阵
- 情景分析：乐观/基准/悲观三种情景对比
"""
from typing import Dict, List, Tuple
import numpy as np

from models.wacc import WACCCalculator
from models.dcf_model import DCFModel


class SensitivityAnalyzer:
    """敏感性分析器"""

    def __init__(self, model: DCFModel):
        self.model = model

    def wacc_growth_sensitivity(
        self,
        base_params: Dict,
        wacc_range: Tuple[float, float, int] = (0.06, 0.14, 9),
        growth_range: Tuple[float, float, int] = (0.01, 0.05, 5),
    ) -> Dict:
        """WACC × 永续增长率 双变量敏感性分析
        返回 matrix 和 labels，便于热力图可视化。
        """
        wacc_min, wacc_max, wacc_steps = wacc_range
        g_min, g_max, g_steps = growth_range

        wacc_values = np.linspace(wacc_min, wacc_max, wacc_steps)
        growth_values = np.linspace(g_min, g_max, g_steps)

        matrix = []
        for g in growth_values:
            row = []
            for w in wacc_values:
                base_fcff = base_params.get("base_fcff", 0)
                revenue = base_params.get("revenue", 0)
                total_debt = base_params.get("total_debt", 0)
                cash = base_params.get("cash", 0)
                total_equity = base_params.get("total_equity", 0)
                beta = base_params.get("beta", 1.0)
                debt_spread = base_params.get("debt_spread", 0.02)
                tax_rate = base_params.get("tax_rate", 0.25)
                short_term_g = base_params.get("short_term_growth", 0.10)
                total_mv = base_params.get("total_mv", 0)
                close_price = base_params.get("close_price", 0)

                # 使用给定的 WACC 而非重新计算
                wacc_calc = WACCCalculator(
                    risk_free_rate=base_params.get("risk_free_rate", 0.028),
                    equity_risk_premium=base_params.get("equity_risk_premium", 0.065),
                    tax_rate=tax_rate,
                )
                local_model = DCFModel(
                    wacc_calc, projection_years=base_params.get("projection_years", 5)
                )

                # 直接注入 WACC（覆盖计算值）
                wacc_result_override = wacc_calc.calculate(
                    total_debt=total_debt,
                    total_equity=total_equity,
                    beta=beta,
                    debt_spread=debt_spread,
                )
                wacc_result_override["wacc"] = w

                # 手动计算
                fcffs = local_model.project_fcff(
                    base_fcff, revenue, short_term_g,
                    base_params.get("danda_to_revenue", 0.05),
                    base_params.get("capex_to_revenue", 0.06),
                    base_params.get("wc_increase_to_revenue", 0.03),
                    tax_rate,
                    operating_margin=base_params.get("operating_margin"),
                )
                tv = local_model.calculate_terminal_value(fcffs[-1], w, g)
                pv_fcffs = local_model.discount_cash_flows(fcffs, w)
                pv_tv = tv / (1 + w) ** local_model.projection_years
                ev = sum(pv_fcffs) + pv_tv
                eq_val = local_model.calculate_equity_value(ev, total_debt, cash)
                shares = local_model.get_current_shares(total_mv, close_price)
                price = eq_val / shares if shares > 0 else 0
                row.append(round(price, 2))
            matrix.append(row)

        return {
            "wacc_values": [round(v, 3) for v in wacc_values],
            "growth_values": [round(v, 3) for v in growth_values],
            "matrix": matrix,
            "wacc_labels": [f"{v*100:.1f}%" for v in wacc_values],
            "growth_labels": [f"{v*100:.1f}%" for v in growth_values],
        }

    def scenario_analysis(
        self,
        base_params: Dict,
        scenarios: Dict[str, Dict],
    ) -> Dict[str, Dict]:
        """多情景分析

        Args:
            base_params: 基准财务参数
            scenarios: {
                "bull": {"short_term_growth": 0.15, ...},
                "base": {...},
                "bear": {...}
            }

        Returns:
            { "bull": {估值结果}, "base": {估值结果}, "bear": {估值结果} }
        """
        results = {}
        for name, params in scenarios.items():
            merged = {**base_params, **params}
            wacc_calc = WACCCalculator(
                risk_free_rate=merged.get("risk_free_rate", 0.028),
                equity_risk_premium=merged.get("equity_risk_premium", 0.065),
                tax_rate=merged.get("tax_rate", 0.25),
            )
            local_model = DCFModel(
                wacc_calc, projection_years=base_params.get("projection_years", 5)
            )
            result = local_model.run(
                base_fcff=merged["base_fcff"],
                revenue=merged["revenue"],
                total_debt=merged["total_debt"],
                cash=merged["cash"],
                total_equity=merged["total_equity"],
                beta=merged["beta"],
                debt_spread=merged.get("debt_spread", 0.02),
                tax_rate=merged.get("tax_rate", 0.25),
                revenue_growth=merged["short_term_growth"],
                perpetual_growth=merged["perpetual_growth"],
                total_mv=merged["total_mv"],
                close_price=merged["close_price"],
                danda_to_revenue=merged.get("danda_to_revenue", 0.05),
                capex_to_revenue=merged.get("capex_to_revenue", 0.06),
                wc_increase_to_revenue=merged.get("wc_increase_to_revenue", 0.03),
                operating_margin=merged.get("operating_margin"),
            )
            results[name] = result
        return results
