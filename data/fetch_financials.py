"""
财务数据获取与预处理层

从 Tushare 取数（兼容标准版接口，英文列名）并转换为 DCF 模型所需的标准化格式。
"""
import pandas as pd
from typing import Dict, Optional
from datetime import datetime

from data.tushare_client import TushareClient


class FinancialDataFetcher:
    """财务数据获取与清洗（兼容标准版 Tushare Pro，英文列名）"""

    def __init__(self, client: TushareClient):
        self.client = client

    def _get_latest_report_date(self, ts_code: str) -> str:
        """获取最新可用的年报报告期（YYYYMMDD格式）"""
        df = self.client.get_income_stmt(ts_code, start_date="20190101")
        if df is None or df.empty:
            raise ValueError(f"无法获取 {ts_code} 的财务数据")
        annual = df[df["end_date"].str.endswith("1231")].copy()
        if annual.empty:
            df["end_date_dt"] = pd.to_datetime(df["end_date"])
            latest = df.loc[df["end_date_dt"].idxmax(), "end_date"]
            return latest
        annual["end_date_dt"] = pd.to_datetime(annual["end_date"])
        latest = annual.loc[annual["end_date_dt"].idxmax(), "end_date"]
        return latest

    def _get_latest_row(self, df: pd.DataFrame) -> pd.Series:
        """获取 DataFrame 中最新年份的数据行（优先年报）"""
        if df is None or df.empty:
            return pd.Series(dtype=float)
        df_copy = df.copy()
        annual = df_copy[df_copy["end_date"].str.endswith("1231")]
        if not annual.empty:
            df_copy = annual
        df_copy["end_date_dt"] = pd.to_datetime(df_copy["end_date"])
        df_copy = df_copy.sort_values("end_date_dt", ascending=False)
        return df_copy.iloc[0]

    def _safe_float(self, series: pd.Series, key: str) -> float:
        """安全获取 Series 中的数值"""
        val = series.get(key, 0)
        try:
            return float(val) if pd.notna(val) else 0.0
        except (ValueError, TypeError):
            return 0.0

    def fetch_snapshot(self, ts_code: str) -> Dict:
        """获取指定股票最新的财务数据快照

        Returns:
            dict: 包含收入、利润、资产负债、现金流等核心指标
        """
        report_date = self._get_latest_report_date(ts_code)
        year = report_date[:4]

        inc = self.client.get_income_stmt(ts_code, start_date=f"{int(year)-3}0101")
        bal = self.client.get_balancesheet(ts_code, start_date=f"{int(year)-3}0101")
        cf = self.client.get_cashflow(ts_code, start_date=f"{int(year)-3}0101")
        indicators = self.client.get_fina_indicator(ts_code, start_date=f"{int(year)-3}0101")

        # daily_basic 取最近交易日
        from datetime import timedelta
        today_dt = datetime.now()
        start_str = (today_dt - timedelta(days=20)).strftime("%Y%m%d")
        end_str = today_dt.strftime("%Y%m%d")
        daily_basic = self.client.get_daily_basic(ts_code, start_date=start_str, end_date=end_str)
        if daily_basic is None or daily_basic.empty:
            # 尝试用更早的日期
            start_str = (today_dt - timedelta(days=60)).strftime("%Y%m%d")
            daily_basic = self.client.get_daily_basic(ts_code, start_date=start_str, end_date=end_str)

        inc_latest = self._get_latest_row(inc)
        bal_latest = self._get_latest_row(bal)
        cf_latest = self._get_latest_row(cf)

        result = {}
        result["ts_code"] = ts_code
        result["report_date"] = report_date

        # --- 利润表（English columns） ---
        result["revenue"] = self._safe_float(inc_latest, "revenue")
        result["operating_profit"] = self._safe_float(inc_latest, "operate_profit")
        result["total_profit"] = self._safe_float(inc_latest, "total_profit")
        result["net_profit"] = self._safe_float(inc_latest, "n_income")
        result["net_profit_parent"] = self._safe_float(inc_latest, "n_income_attr_p")
        # 利息费用
        result["interest_expense"] = self._safe_float(inc_latest, "fin_exp_int_exp")
        if result["interest_expense"] == 0:
            result["interest_expense"] = self._safe_float(inc_latest, "fin_exp")

        # 折旧与摊销（从利润表或现金流表获取）
        depr_fa = self._safe_float(cf_latest, "depr_fa_coga_dpba")
        amort_intan = self._safe_float(cf_latest, "amort_intang_assets")
        result["depreciation_amortization"] = depr_fa + amort_intan
        if result["depreciation_amortization"] == 0:
            result["depreciation_amortization"] = self._safe_float(inc_latest, "ebitda") - self._safe_float(inc_latest, "ebit") + result["interest_expense"]

        # --- 资产负债表 ---
        result["total_assets"] = self._safe_float(bal_latest, "total_assets")
        result["total_liabilities"] = self._safe_float(bal_latest, "total_liab")
        result["total_equity"] = self._safe_float(bal_latest, "total_hldr_eqy_inc_min_int")
        result["equity_parent"] = self._safe_float(bal_latest, "total_hldr_eqy_exc_min_int")
        result["cash"] = self._safe_float(bal_latest, "money_cap")

        st_borr = self._safe_float(bal_latest, "st_borr")
        lt_borr = self._safe_float(bal_latest, "lt_borr")
        bond_pay = self._safe_float(bal_latest, "bond_payable")
        result["total_debt"] = st_borr + lt_borr + bond_pay

        result["current_assets"] = self._safe_float(bal_latest, "total_cur_assets")
        result["current_liabilities"] = self._safe_float(bal_latest, "total_cur_liab")

        # --- 现金流 ---
        result["operating_cash_flow"] = self._safe_float(cf_latest, "n_cashflow_act")
        result["capex"] = self._safe_float(cf_latest, "c_pay_acq_const_fiolta")
        # Tushare 直接提供的自由现金流
        result["free_cash_flow"] = self._safe_float(cf_latest, "free_cashflow")
        if result["free_cash_flow"] == 0:
            result["free_cash_flow"] = result["operating_cash_flow"] - result["capex"]

        # --- 财务指标 ---
        if indicators is not None and not indicators.empty:
            ind_latest = indicators.iloc[0]
            result["roe"] = self._safe_float(ind_latest, "roe")
            result["eps"] = self._safe_float(ind_latest, "eps")
            result["bps"] = self._safe_float(ind_latest, "bps")
            result["profit_margin"] = self._safe_float(ind_latest, "netprofit_margin")
        else:
            result["roe"] = 0.0
            result["eps"] = 0.0
            result["bps"] = 0.0
            result["profit_margin"] = 0.0

        # --- 市值数据 ---
        # Tushare daily_basic 中 total_mv 单位为千元, total_share 单位为万股
        # 统一转换为元
        if daily_basic is not None and not daily_basic.empty:
            db = daily_basic.iloc[0]
            result["total_mv"] = self._safe_float(db, "total_mv") * 10000
            result["circ_mv"] = self._safe_float(db, "circ_mv") * 10000
            result["pe_ttm"] = self._safe_float(db, "pe_ttm")
            result["pb"] = self._safe_float(db, "pb")
            result["total_share"] = self._safe_float(db, "total_share") * 10000
        else:
            result["total_mv"] = 0.0
            result["circ_mv"] = 0.0
            result["pe_ttm"] = 0.0
            result["pb"] = 0.0
            result["total_share"] = 0.0

        # --- 历史收入序列 ---
        result["historical_revenue"] = self._get_historical_series(inc, "revenue")

        return result

    def _get_historical_series(self, df: pd.DataFrame, column: str) -> Dict[str, float]:
        """从报表DataFrame提取多期历史序列"""
        series = {}
        if df is None or df.empty:
            return series
        annual = df[df["end_date"].str.endswith("1231")].copy()
        if annual.empty:
            annual = df.copy()
        for _, row in annual.iterrows():
            date = row["end_date"]
            try:
                val = float(row.get(column, 0) or 0)
                series[date[:4]] = val
            except (ValueError, TypeError):
                continue
        return dict(sorted(series.items()))

    def get_historical_fcf(self, ts_code: str, years: int = 5) -> pd.Series:
        """获取历史自由现金流序列"""
        report_date = self._get_latest_report_date(ts_code)
        start_year = int(report_date[:4]) - years
        cf = self.client.get_cashflow(ts_code, start_date=f"{start_year}0101")
        if cf is None or cf.empty:
            return pd.Series(dtype=float)

        annual_cf = cf[cf["end_date"].str.endswith("1231")].copy()
        if annual_cf.empty:
            annual_cf = cf.copy()

        fcf_list = {}
        for _, row in annual_cf.iterrows():
            year = row["end_date"][:4]
            fcf = self._safe_float(row, "free_cashflow")
            if fcf == 0:
                ocf = self._safe_float(row, "n_cashflow_act")
                capex = self._safe_float(row, "c_pay_acq_const_fiolta")
                fcf = ocf - capex
            fcf_list[year] = fcf

        return pd.Series(fcf_list).sort_index()
