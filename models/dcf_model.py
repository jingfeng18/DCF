"""
DCF（贴现现金流）估值模型

基于 FCFF 的两阶段模型：
  阶段1：显式预测期（通常5年），逐年贴现
  阶段2：终值（Terminal Value），基于永续增长法
"""
from typing import Dict, List, Optional
from models.wacc import WACCCalculator


class DCFModel:
    """两阶段 FCFF 贴现模型"""

    def __init__(
        self,
        wacc_calculator: WACCCalculator,
        projection_years: int = 5,
    ):
        self.wacc_calculator = wacc_calculator
        self.projection_years = projection_years

    def project_fcff(
        self,
        base_fcff: float,
        revenue: float,
        revenue_growth: float,
        danda_to_revenue: float,
        capex_to_revenue: float,
        wc_increase_to_revenue: float,
        tax_rate: float,
        operating_margin: Optional[float] = None,
    ) -> List[float]:
        """预测未来 FCFF

        两种模式：
          1. 简化模式（operating_margin=None）:
             FCFF_t = base_fcff × (1+g)^t
          2. 逐项拆解模式（operating_margin=给定值）:
             Revenue_t = Revenue_0 × (1+g)^t
             EBIT_t    = Revenue_t × operating_margin
             FCFF_t    = EBIT_t×(1-T) + D&A - Capex - ΔWC
        """
        fcffs = []
        if operating_margin is None:
            # 简化模式：增长率外推
            for t in range(1, self.projection_years + 1):
                growth_factor = (1 + revenue_growth) ** t
                projected_fcff = base_fcff * growth_factor
                fcffs.append(projected_fcff)
        else:
            # 逐项拆解模式
            for t in range(1, self.projection_years + 1):
                rev_t = revenue * (1 + revenue_growth) ** t
                ebit = rev_t * operating_margin
                danda = rev_t * danda_to_revenue
                capex = rev_t * capex_to_revenue
                wc = rev_t * wc_increase_to_revenue
                fcff = ebit * (1 - tax_rate) + danda - capex - wc
                fcffs.append(fcff)
        return fcffs

    def calculate_terminal_value(self, last_fcff: float, wacc: float, perpetual_growth: float) -> float:
        """计算终值（永续增长模型）: TV = FCFF_n × (1+g) / (WACC - g)"""
        if wacc <= perpetual_growth:
            raise ValueError("WACC 必须大于永续增长率")
        return last_fcff * (1 + perpetual_growth) / (wacc - perpetual_growth)

    def discount_cash_flows(self, cash_flows: List[float], wacc: float) -> List[float]:
        """将未来现金流折现到现值"""
        pvs = []
        for t, cf in enumerate(cash_flows, start=1):
            pv = cf / (1 + wacc) ** t
            pvs.append(pv)
        return pvs

    def calculate_equity_value(
        self,
        enterprise_value: float,
        total_debt: float,
        cash: float,
    ) -> float:
        """企业价值 → 股权价值: Equity Value = EV - Debt + Cash"""
        return enterprise_value - total_debt + cash

    def calculate_implied_share_price(
        self,
        equity_value: float,
        shares_outstanding: float,
    ) -> float:
        """估算每股内在价值"""
        if shares_outstanding == 0:
            raise ValueError("总股本不能为零")
        return equity_value / shares_outstanding

    def get_current_shares(self, total_mv: float, close_price: float, total_share: float = 0) -> float:
        """计算总股本，优先使用直接提供的总股本"""
        if total_share > 0:
            return total_share
        if close_price == 0:
            return 0
        return total_mv / close_price

    def run(
        self,
        base_fcff: float,
        revenue: float,
        total_debt: float,
        cash: float,
        total_equity: float,
        beta: float,
        debt_spread: float,
        tax_rate: float,
        revenue_growth: float,
        perpetual_growth: float,
        total_mv: float,
        close_price: float,
        total_share: float = 0,
        danda_to_revenue: float = 0.05,
        capex_to_revenue: float = 0.06,
        wc_increase_to_revenue: float = 0.03,
        operating_margin: Optional[float] = None,
    ) -> Dict:
        """运行 DCF 估值主流程

        Returns:
            dict: 包含详细估值结果
        """
        # 1. 计算 WACC
        wacc_result = self.wacc_calculator.calculate(
            total_debt=total_debt,
            total_equity=total_equity,
            beta=beta,
            debt_spread=debt_spread,
        )
        wacc = wacc_result["wacc"]

        # 2. 预测 FCFF
        fcffs = self.project_fcff(
            base_fcff=base_fcff,
            revenue=revenue,
            revenue_growth=revenue_growth,
            danda_to_revenue=danda_to_revenue,
            capex_to_revenue=capex_to_revenue,
            wc_increase_to_revenue=wc_increase_to_revenue,
            tax_rate=tax_rate,
            operating_margin=operating_margin,
        )

        # 3. 计算终值
        tv = self.calculate_terminal_value(fcffs[-1], wacc, perpetual_growth)

        # 4. 贴现
        pv_fcffs = self.discount_cash_flows(fcffs, wacc)
        pv_tv = tv / (1 + wacc) ** self.projection_years

        # 5. 企业价值
        ev = sum(pv_fcffs) + pv_tv

        # 6. 股权价值与每股价值
        equity_value = self.calculate_equity_value(ev, total_debt, cash)
        shares = self.get_current_shares(total_mv, close_price, total_share)
        implied_price = (
            self.calculate_implied_share_price(equity_value, shares) if shares > 0 else 0
        )

        # 计算 upsides
        upside = (implied_price - close_price) / close_price if close_price > 0 else 0

        # 各年 FCFF 明细
        projections = []
        for t in range(self.projection_years):
            projections.append(
                {
                    "year": t + 1,
                    "fcff": round(fcffs[t], 2),
                    "pv_fcff": round(pv_fcffs[t], 2),
                }
            )

        year_labels = [
            f"第{t+1}年"
            if t < self.projection_years - 1
            else f"第{t+1}年(终值)"
            for t in range(self.projection_years)
        ]

        return {
            "wacc_details": wacc_result,
            "wacc": round(wacc, 4),
            "projections": projections,
            "terminal_value": round(tv, 2),
            "pv_terminal_value": round(pv_tv, 2),
            "pv_fcff_sum": round(sum(pv_fcffs), 2),
            "enterprise_value": round(ev, 2),
            "equity_value": round(equity_value, 2),
            "shares_outstanding": round(shares, 2),
            "implied_price": round(implied_price, 2),
            "current_price": round(close_price, 2),
            "upside": round(upside, 4),
            "upside_pct": f"{round(upside * 100, 1)}%",
            "total_debt": round(total_debt, 2),
            "cash": round(cash, 2),
            "base_fcff": round(base_fcff, 2),
            "short_term_growth": revenue_growth,
            "perpetual_growth": perpetual_growth,
            "projection_years": self.projection_years,
        }
