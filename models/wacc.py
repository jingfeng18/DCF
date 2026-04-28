"""
WACC（加权平均资本成本）计算模块

支持 CAPM 计算股权成本、债务成本估算及加权平均。
"""
from typing import Optional


class WACCCalculator:
    """WACC 计算器"""

    def __init__(
        self,
        risk_free_rate: float = 0.028,
        equity_risk_premium: float = 0.065,
        tax_rate: float = 0.25,
    ):
        self.risk_free_rate = risk_free_rate
        self.equity_risk_premium = equity_risk_premium
        self.tax_rate = tax_rate

    def cost_of_equity_capm(self, beta: float) -> float:
        """CAPM 计算股权成本: Ke = Rf + β × ERP"""
        return self.risk_free_rate + beta * self.equity_risk_premium

    def cost_of_debt(self, debt_spread: float = 0.02) -> float:
        """债务成本: Kd = Rf + spread"""
        return self.risk_free_rate + debt_spread

    def after_tax_cost_of_debt(self, debt_spread: float = 0.02) -> float:
        """税后债务成本: Kd × (1 - T)"""
        return self.cost_of_debt(debt_spread) * (1 - self.tax_rate)

    def calculate(
        self,
        total_debt: float,
        total_equity: float,
        beta: float,
        debt_spread: float = 0.02,
    ) -> dict:
        """完整 WACC 计算

        Args:
            total_debt: 总债务（短期借款+长期借款+应付债券）
            total_equity: 股东权益总额
            beta: 股票的 Beta 系数
            debt_spread: 信用利差

        Returns:
            dict: 包含 WACC 及各组成部分的详情
        """
        total_capital = total_debt + total_equity
        if total_capital == 0:
            raise ValueError("总资本为零，无法计算 WACC")

        # 权重
        wd = total_debt / total_capital  # 债务权重
        we = total_equity / total_capital  # 股权权重

        # 成本
        ke = self.cost_of_equity_capm(beta)
        kd = self.cost_of_debt(debt_spread)
        kd_after_tax = self.after_tax_cost_of_debt(debt_spread)

        # WACC
        wacc = we * ke + wd * kd_after_tax

        return {
            "wacc": round(wacc, 6),
            "cost_of_equity": round(ke, 6),
            "cost_of_debt": round(kd, 6),
            "after_tax_cost_of_debt": round(kd_after_tax, 6),
            "debt_weight": round(wd, 6),
            "equity_weight": round(we, 6),
            "risk_free_rate": self.risk_free_rate,
            "equity_risk_premium": self.equity_risk_premium,
            "beta": beta,
            "tax_rate": self.tax_rate,
        }
