"""
基金数据获取模块 — 基于 AkShare 封装
- 基金列表: fund_open_fund_rank_em (排行数据)
- 历史净值: fund_open_fund_info_em (单只基金净值曲线)
"""

import akshare as ak
import pandas as pd
from typing import Optional

# 支持的类型映射
FUND_TYPE_MAP = {
    "全部": "全部",
    "股票型": "股票型",
    "混合型": "混合型",
    "债券型": "债券型",
    "指数型": "指数型",
    "QDII": "QDII",
    "FOF": "FOF",
    "LOF": "LOF",
}


def fetch_fund_list(fund_type: str = "全部") -> pd.DataFrame:
    """
    获取公募基金排行列表（含近期收益、净值、手续费等）。
    fund_type: "全部" / "股票型" / "混合型" / "债券型" / "指数型" / "QDII" / "FOF" / "LOF"
    """
    ak_type = FUND_TYPE_MAP.get(fund_type, "全部")
    df = ak.fund_open_fund_rank_em(symbol=ak_type)

    if df is None or df.empty:
        return pd.DataFrame()

    # 统一列名（AkShare 返回中文列名）
    col_map = {
        "序号": "rank",
        "基金代码": "code",
        "基金简称": "name",
        "日期": "date",
        "单位净值": "nav",
        "累计净值": "acc_nav",
        "日增长率": "daily_return",
        "近1周": "ret_1w",
        "近1月": "ret_1m",
        "近3月": "ret_3m",
        "近6月": "ret_6m",
        "近1年": "ret_1y",
        "近2年": "ret_2y",
        "近3年": "ret_3y",
        "今年来": "ret_ytd",
        "成立来": "ret_since_start",
        "自定义": "custom",
        "手续费": "fee",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # 添加类型列
    if "type" not in df.columns:
        df["type"] = fund_type

    # 清理数字列
    for col in ["nav", "acc_nav"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def fetch_fund_nav(fund_code: str, start_date: str = "20200101", end_date: str = "20251231") -> pd.DataFrame:
    """
    获取单只基金的历史净值数据（全部历史然后按日期筛选）。
    """
    try:
        df = ak.fund_open_fund_info_em(
            symbol=str(fund_code),
            indicator="单位净值走势",
            period="成立来",
        )
    except Exception:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    # 标准化列名
    col_map = {
        "净值日期": "date",
        "单位净值": "nav",
        "日增长率": "daily_return",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    if "date" not in df.columns:
        return pd.DataFrame()

    # 日期处理
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    # 按日期范围筛选
    if start_date:
        start_dt = pd.to_datetime(start_date, format="%Y%m%d", errors="coerce")
        if pd.notna(start_dt):
            df = df[df["date"] >= start_dt]
    if end_date:
        end_dt = pd.to_datetime(end_date, format="%Y%m%d", errors="coerce")
        if pd.notna(end_dt):
            df = df[df["date"] <= end_dt]

    # 数值清理
    if "nav" in df.columns:
        df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
    if "daily_return" in df.columns:
        df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce")

    return df


def fetch_single_fund_info(fund_code: str) -> dict:
    """
    获取单只基金的详细信息（通过 fund_individual_basic_info_xq）。
    """
    try:
        df = ak.fund_individual_basic_info_xq(symbol=str(fund_code))
        if df is not None and not df.empty:
            # df 通常是一个包含 'item' / 'value' 的表格
            info = {}
            if "item" in df.columns and "value" in df.columns:
                for _, row in df.iterrows():
                    info[str(row["item"])] = str(row["value"])
            return info
    except Exception:
        pass
    return {}


# ── SQLite 缓存版 ──────────────────────────────────────

import db as cache_db


def fetch_fund_list_cached(fund_type: str = "全部", force_refresh: bool = False) -> tuple[pd.DataFrame, bool]:
    """
    获取基金列表（优先 SQLite 缓存，过期自动刷新）。
    返回 (DataFrame, 是否来自缓存)。
    """
    if not force_refresh and cache_db.is_fund_list_fresh(fund_type):
        df = cache_db.get_cached_fund_list(fund_type)
        if df is not None and not df.empty:
            return df, True

    # 缓存过期或强制刷新
    df = fetch_fund_list(fund_type)
    if not df.empty:
        cache_db.save_fund_list(fund_type, df)
    return df, False


def fetch_fund_nav_cached(fund_code: str, start_date: str = "20200101",
                          end_date: str = "20251231", force_refresh: bool = False) -> tuple[pd.DataFrame, bool]:
    """
    获取基金净值（优先 SQLite 缓存，过期自动从 AkShare 刷新）。
    返回 (DataFrame, 是否来自缓存)。
    判断逻辑: 如果请求区间结束日期距今>3天，直接用缓存；否则检查是否已有最新数据。
    """
    code = str(fund_code)

    if not force_refresh:
        cached = cache_db.get_cached_nav(code, start_date, end_date)
        if cached is not None and len(cached) >= 10:
            # 检查是否需要刷新: 仅当请求区间覆盖最近3天才检查新鲜度
            try:
                end_dt = pd.to_datetime(end_date, format="%Y%m%d")
                if end_dt > pd.Timestamp.now() - pd.Timedelta(days=3):
                    # 请求包含近期数据，检查 SQLite 是否有最新
                    if not cache_db.is_nav_fresh(code):
                        pass  # 需要刷新，走下面的 AkShare 路径
                    else:
                        return cached, True
                else:
                    # 请求的是历史数据，有缓存就够了
                    return cached, True
            except Exception:
                pass

    # 从 AkShare 获取并写入缓存
    df = fetch_fund_nav(code, start_date, end_date)
    if not df.empty and "nav" in df.columns:
        cache_db.save_nav(code, df)
    return df, False
