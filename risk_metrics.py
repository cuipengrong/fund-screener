"""
风险指标计算模块
基于基金净值序列计算各类风险与收益指标。
"""

import numpy as np
import pandas as pd
from scipy import stats
from typing import Optional


def calc_daily_returns(nav_series: pd.Series) -> pd.Series:
    """从净值序列计算日收益率（百分比形式）。"""
    return nav_series.pct_change().dropna() * 100


def max_drawdown(nav_series: pd.Series) -> float:
    """
    最大回撤（%）：从峰值到谷底的最大跌幅。
    """
    cumulative = (1 + nav_series.pct_change().dropna()).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    return float(drawdown.min() * 100)


def annualized_return(nav_series: pd.Series) -> float:
    """年化收益率（%），基于净值起点到终点。"""
    if len(nav_series) < 2:
        return 0.0
    daily_ret = nav_series.pct_change().dropna()
    trading_days = len(daily_ret)
    total_return = (nav_series.iloc[-1] / nav_series.iloc[0]) - 1
    # 假设每年 252 个交易日
    years = trading_days / 252
    if years <= 0:
        return 0.0
    ann_return = (1 + total_return) ** (1 / years) - 1
    return float(ann_return * 100)


def annualized_volatility(nav_series: pd.Series) -> float:
    """年化波动率（%），即日收益率的年化标准差。"""
    daily_ret = nav_series.pct_change().dropna()
    return float(daily_ret.std() * np.sqrt(252) * 100)


def sharpe_ratio(nav_series: pd.Series, risk_free: float = 0.025) -> float:
    """
    夏普比率：(年化收益 - 无风险利率) / 年化波动率。
    risk_free 默认 2.5%（大致对应国内十年期国债）。
    """
    ann_ret = annualized_return(nav_series)
    ann_vol = annualized_volatility(nav_series)
    if ann_vol == 0:
        return 0.0
    return (ann_ret - risk_free * 100) / ann_vol


def sortino_ratio(nav_series: pd.Series, risk_free: float = 0.025) -> float:
    """
    索提诺比率：只惩罚下行波动。
    """
    daily_ret = nav_series.pct_change().dropna()
    downside = daily_ret[daily_ret < 0]
    if len(downside) == 0 or downside.std() == 0:
        return 0.0
    downside_vol = downside.std() * np.sqrt(252) * 100
    ann_ret = annualized_return(nav_series)
    return (ann_ret - risk_free * 100) / downside_vol


def calmar_ratio(nav_series: pd.Series) -> float:
    """
    卡玛比率：年化收益 / 最大回撤（绝对值）。
    衡量每承受1%回撤能获得的收益。
    """
    ann_ret = annualized_return(nav_series)
    mdd = abs(max_drawdown(nav_series))
    if mdd == 0:
        return 0.0
    return ann_ret / mdd


def var_95(nav_series: pd.Series) -> float:
    """
    VaR (95% 置信度): 在95%的情况下，单日最大亏损不会超过这个值（%）。
    使用历史模拟法。
    """
    daily_ret = nav_series.pct_change().dropna() * 100
    return float(np.percentile(daily_ret, 5))


def cvar_95(nav_series: pd.Series) -> float:
    """
    CVaR (95%): 超过 VaR 的平均亏损（尾部风险）。
    """
    daily_ret = nav_series.pct_change().dropna() * 100
    var = np.percentile(daily_ret, 5)
    tail = daily_ret[daily_ret <= var]
    return float(tail.mean())


def winning_rate(nav_series: pd.Series) -> float:
    """日胜率（%）。"""
    daily_ret = nav_series.pct_change().dropna()
    return float((daily_ret > 0).sum() / len(daily_ret) * 100)


def all_risk_metrics(nav_series: pd.Series, risk_free: float = 0.025) -> dict:
    """一键计算所有风险指标，返回字典。"""
    return {
        "年化收益(%)": round(annualized_return(nav_series), 2),
        "年化波动率(%)": round(annualized_volatility(nav_series), 2),
        "最大回撤(%)": round(max_drawdown(nav_series), 2),
        "夏普比率": round(sharpe_ratio(nav_series, risk_free), 2),
        "索提诺比率": round(sortino_ratio(nav_series, risk_free), 2),
        "卡玛比率": round(calmar_ratio(nav_series), 2),
        "VaR 95%(%)": round(var_95(nav_series), 2),
        "CVaR 95%(%)": round(cvar_95(nav_series), 2),
        "日胜率(%)": round(winning_rate(nav_series), 2),
        "样本天数": len(nav_series),
    }


def batch_risk_summary(funds_nav: dict[str, pd.Series], risk_free: float = 0.025) -> pd.DataFrame:
    """
    批量计算多只基金的风险指标。
    funds_nav: {fund_name: nav_series}
    返回 DataFrame，以基金名为索引。
    """
    records = []
    for name, nav in funds_nav.items():
        metrics = all_risk_metrics(nav, risk_free)
        metrics["基金"] = name
        records.append(metrics)

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.set_index("基金")
    return df
