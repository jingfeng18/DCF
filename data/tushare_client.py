"""
Tushare API 客户端封装
"""
import pandas as pd
import tushare as ts
from typing import Optional


class TushareClient:
    """统一 Tushare API 访问入口"""

    def __init__(self, token: str):
        ts.set_token(token)
        self.api = ts.pro_api()

    def get_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取日线行情"""
        return self.api.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)

    def get_income_stmt(self, ts_code: str, start_date: str, end_date: str = None) -> pd.DataFrame:
        """获取利润表（优先VIP，回退普通接口）"""
        for api_name in ["income_vip", "income"]:
            try:
                fn = getattr(self.api, api_name)
                df = fn(ts_code=ts_code, start_date=start_date, end_date=end_date)
                if df is not None and not df.empty:
                    return df
            except Exception:
                continue
        return None

    def get_balancesheet(self, ts_code: str, start_date: str, end_date: str = None) -> pd.DataFrame:
        """获取资产负债表"""
        for api_name in ["balancesheet_vip", "balancesheet"]:
            try:
                fn = getattr(self.api, api_name)
                df = fn(ts_code=ts_code, start_date=start_date, end_date=end_date)
                if df is not None and not df.empty:
                    return df
            except Exception:
                continue
        return None

    def get_cashflow(self, ts_code: str, start_date: str, end_date: str = None) -> pd.DataFrame:
        """获取现金流量表"""
        for api_name in ["cashflow_vip", "cashflow"]:
            try:
                fn = getattr(self.api, api_name)
                df = fn(ts_code=ts_code, start_date=start_date, end_date=end_date)
                if df is not None and not df.empty:
                    return df
            except Exception:
                continue
        return None

    def get_fina_indicator(self, ts_code: str, start_date: str, end_date: str = None) -> pd.DataFrame:
        """获取财务指标（ROE、EPS等）"""
        for api_name in ["fina_indicator_vip", "fina_indicator"]:
            try:
                fn = getattr(self.api, api_name)
                df = fn(ts_code=ts_code, start_date=start_date, end_date=end_date)
                if df is not None and not df.empty:
                    return df
            except Exception:
                continue
        return None

    def get_stock_basic(self, ts_code: str) -> pd.DataFrame:
        """获取股票基本信息"""
        return self.api.stock_basic(ts_code=ts_code)

    def get_daily_basic(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取每日基本面数据（含市值、PE等）"""
        return self.api.daily_basic(ts_code=ts_code, start_date=start_date, end_date=end_date)

    def get_shibor(self, date: str) -> pd.DataFrame:
        """获取Shibor利率（用于无风险利率参考）"""
        return self.api.shibor(date=date)

    def get_index_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取指数日线（用于Beta计算参考）"""
        return self.api.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
