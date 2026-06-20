"""
基金风险指标筛选工具 — Streamlit Web 界面
聚焦: 最大回撤、波动率、夏普比率、卡玛比率、VaR 等
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta

from data_fetcher import fetch_fund_list, fetch_fund_nav
from risk_metrics import (
    all_risk_metrics,
    batch_risk_summary,
    max_drawdown,
    calc_daily_returns,
)

# ── 页面配置 ───────────────────────────────────────────
st.set_page_config(
    page_title="基金风险筛选器",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📊 基金风险指标筛选器")
st.caption("基于 AkShare 数据 · 聚焦最大回撤、波动率、夏普比率等风险维度")


# ── 缓存 ───────────────────────────────────────────────
@st.cache_data(ttl=43200, show_spinner=False)
def cached_fund_list(fund_type: str):
    return fetch_fund_list(fund_type)


@st.cache_data(ttl=43200, show_spinner=False)
def cached_fund_nav(fund_code: str, start: str, end: str):
    return fetch_fund_nav(fund_code, start, end)


# ── 侧边栏: 筛选控制 ────────────────────────────────────
with st.sidebar:
    st.header("🔍 筛选条件")

    fund_type = st.selectbox(
        "基金类型",
        options=["全部", "股票型", "混合型", "债券型", "指数型", "QDII", "FOF", "LOF"],
        index=2,  # 默认混合型
    )

    st.subheader("📅 分析区间")
    now = datetime.now()
    default_start = now - timedelta(days=365 * 3)

    c1, c2 = st.columns(2)
    with c1:
        st.caption("起始")
        sy = st.selectbox("年", range(2015, now.year + 1), index=default_start.year - 2015, key="sy")
        sm = st.selectbox("月", range(1, 13), index=default_start.month - 1, key="sm")
        sd = st.selectbox("日", range(1, 32), index=default_start.day - 1, key="sd")
    with c2:
        st.caption("结束")
        ey = st.selectbox("年", range(2015, now.year + 1), index=now.year - 2015, key="ey")
        em = st.selectbox("月", range(1, 13), index=now.month - 1, key="em")
        ed = st.selectbox("日", range(1, 32), index=now.day - 1, key="ed")

    try:
        start_date = datetime(sy, sm, min(sd, 28))
        end_date = datetime(ey, em, min(ed, 28))
    except ValueError:
        start_date = default_start
        end_date = now

    if end_date <= start_date:
        end_date = start_date + timedelta(days=1)
        st.warning("结束日期已自动调整为起始日期后一天")
    date_range = (start_date, end_date)
    st.caption(f"已选: {start_date.strftime('%Y-%m-%d')} → {end_date.strftime('%Y-%m-%d')}")

    risk_free_rate = st.number_input(
        "无风险利率 (%)",
        min_value=0.0,
        max_value=10.0,
        value=2.5,
        step=0.1,
        help="用于计算夏普/索提诺比率，默认2.5% ≈ 十年期国债",
    )

    sort_by = st.selectbox(
        "排序指标",
        options=["卡玛比率", "夏普比率", "索提诺比率", "最大回撤(%)", "年化波动率(%)", "年化收益(%)", "日胜率(%)"],
        index=0,
        help="卡玛比率 = 年化收益 / 最大回撤，越高越好",
    )

    ascending = st.toggle("升序排列", value=False)

    st.divider()
    st.subheader("💰 金额模拟")

    invest_mode = st.radio(
        "投入方式",
        options=["一次性投入", "定投"],
        index=0,
        horizontal=True,
    )

    total_amount = st.number_input(
        "总投入金额（元）",
        min_value=1,
        max_value=10000000,
        value=100000,
        step=10000,
        format="%d",
    )

    if invest_mode == "定投":
        invest_freq = st.selectbox("定投频率", options=["每周", "每两周", "每月"], index=2)
        invest_period = st.number_input(
            "每期投入（元）",
            min_value=1,
            max_value=1000000,
            value=2000,
            step=100,
            format="%d",
        )
    else:
        # 一次性: 平均分配或自定义
        alloc_mode = st.radio("分配方式", options=["平均分配", "自定义"], index=0, horizontal=True)

    st.divider()
    st.caption(
        "💡 **指标说明**\n\n"
        "- **最大回撤**: 峰值到谷底的最大跌幅，越小越好\n"
        "- **年化波动率**: 收益率的标准差，越低越稳\n"
        "- **夏普比率**: 每单位风险的超额收益，越高越好\n"
        "- **卡玛比率**: 收益/回撤，衡量「性价比」\n"
        "- **索提诺比率**: 只惩罚下行波动的夏普\n"
        "- **VaR 95%**: 95%置信度下日最大亏损\n"
        "- **CVaR 95%**: 超出VaR后的平均亏损"
    )

# ── 主区域 ──────────────────────────────────────────────
# Step 1: 加载基金列表（延迟加载，避免每次打开页面都请求）
if "fund_df" not in st.session_state:
    st.session_state.fund_df = None

if st.session_state.fund_df is None:
    if st.button("📥 加载基金列表", type="primary", use_container_width=True,
                 help=f"从东方财富获取{fund_type}基金数据，首次约需3-10秒"):
        with st.spinner("正在加载基金列表..."):
            st.session_state.fund_df = cached_fund_list(fund_type)
        st.rerun()
    # 还没有数据时显示提示
    fund_df = pd.DataFrame()
else:
    fund_df = st.session_state.fund_df
    # 如果切换了类型，提供刷新按钮
    if st.button("🔄 刷新基金列表 / 切换类型", use_container_width=True):
        st.session_state.fund_df = None
        st.rerun()

# 筛选搜索
# 方式1: 快速输入代码（逗号/空格/换行分隔）
st.subheader("⚡ 方式一：直接输入代码")
quick_codes = st.text_area(
    "输入基金代码，用逗号、空格或换行分隔",
    placeholder="例如: 001480, 011369, 010013, 001956, 110020",
    height=68,
    key="quick_codes",
)

# 方式2: 搜索 + 表格勾选
st.subheader("🔍 方式二：搜索并勾选")
search = st.text_input("搜索基金名称或代码", placeholder="例如: 沪深300、000001...")

if search:
    mask = fund_df["name"].str.contains(search, case=False, na=False)
    if "code" in fund_df.columns:
        mask |= fund_df["code"].astype(str).str.contains(search, case=False, na=False)
    fund_df_filtered = fund_df[mask].copy()
    st.info(f"匹配 {len(fund_df_filtered)} 只基金")
else:
    fund_df_filtered = fund_df.copy()

# 限制显示列
show_cols = [c for c in ["code", "name", "type", "nav", "daily_return", "ret_1y", "ret_3y", "aum"] if c in fund_df_filtered.columns]

event = st.dataframe(
    fund_df_filtered[show_cols],
    use_container_width=True,
    hide_index=True,
    height=250,
    on_select="rerun",
    selection_mode="multi-row",
)

# 合并两种选择方式
table_selected_codes = []
if event.selection.rows:
    table_selected_codes = fund_df_filtered.iloc[event.selection.rows]["code"].tolist()

# 解析快速输入
quick_code_list = []
if quick_codes.strip():
    import re
    quick_code_list = re.split(r'[,，\s]+', quick_codes.strip())
    quick_code_list = [c.strip() for c in quick_code_list if c.strip()]

# 合并去重
all_selected = list(set(quick_code_list + table_selected_codes))

if not all_selected:
    st.warning("👆 请输入基金代码（方式一）或在表格中勾选（方式二）")
    st.stop()

if len(all_selected) > 10:
    st.warning("最多选择 10 只基金进行比较")
    all_selected = all_selected[:10]

# 从原始 fund_df 中查找代码对应的基金名
code_name_map = dict(zip(fund_df["code"].astype(str), fund_df["name"]))
selected_codes = []
selected_names = []
not_found = []

for c in all_selected:
    c_str = str(c).zfill(6)  # 补齐6位
    if c_str in code_name_map:
        selected_codes.append(c_str)
        selected_names.append(code_name_map[c_str])
    else:
        not_found.append(c)

if not_found:
    st.warning(f"⚠️ 未找到: {', '.join(not_found)}")

if not selected_codes:
    st.warning("未找到任何有效的基金代码")
    st.stop()

st.info(f"已选择 {len(selected_codes)} 只: **{'、'.join(selected_names)}**")

# Step 2: 获取净值并计算风险指标
# date_range 在侧边栏中定义为 (start_date, end_date) 元组
if isinstance(date_range, (tuple, list)) and len(date_range) >= 2:
    start_str = date_range[0].strftime("%Y%m%d")
    end_str = date_range[1].strftime("%Y%m%d")
else:
    start_str = default_start.strftime("%Y%m%d")
    end_str = now.strftime("%Y%m%d")

if st.button("🚀 开始分析", type="primary", use_container_width=True):
    funds_nav = {}
    funds_daily = {}  # 保存完整日数据供明细表使用
    from concurrent.futures import ThreadPoolExecutor, as_completed

    progress = st.progress(0, text="正在并发获取净值数据...")
    failed = []
    total = len(selected_codes)

    # 并发获取所有基金的净值
    def fetch_one(code, name):
        nav_df = cached_fund_nav(str(code), start_str, end_str)
        if nav_df.empty or "nav" not in nav_df.columns or len(nav_df) < 60:
            return name, None
        return name, nav_df

    completed = 0
    with ThreadPoolExecutor(max_workers=min(8, total)) as executor:
        futures = {executor.submit(fetch_one, c, n): n for c, n in zip(selected_codes, selected_names)}
        for future in as_completed(futures):
            name, nav_df = future.result()
            completed += 1
            progress.progress(completed / total, text=f"获取 {name} ({completed}/{total})")
            if nav_df is None:
                failed.append(name)
            else:
                funds_nav[name] = nav_df["nav"].copy()
                funds_daily[name] = nav_df[["date", "nav", "daily_return"]].copy()
                funds_daily[name]["daily_return"] = pd.to_numeric(funds_daily[name]["daily_return"], errors="coerce")

    progress.progress(1.0, text="计算风险指标中...")

    if not funds_nav:
        st.error("❌ 未能获取到任何净值数据。")
        st.stop()

    if failed:
        st.warning(f"⚠️ 以下基金数据不足（已跳过）: {', '.join(failed)}")

    # 计算风险指标
    risk_df = batch_risk_summary(funds_nav, risk_free=risk_free_rate / 100)

    # 排序
    sort_col = sort_by
    if sort_col in risk_df.columns:
        risk_df = risk_df.sort_values(sort_col, ascending=ascending)

    progress.empty()

    # ── 结果展示 ──────────────────────────────────────
    st.divider()
    st.subheader("📊 风险指标对比总览")

    # 条件着色
    def highlight_risk(val, col_name):
        """对风险指标着色：好=绿，差=红"""
        if col_name in ["最大回撤(%)", "年化波动率(%)", "VaR 95%(%)", "CVaR 95%(%)"]:
            if val <= risk_df[col_name].quantile(0.3):
                return "background-color: #d4edda; color: #155724"
            elif val >= risk_df[col_name].quantile(0.7):
                return "background-color: #f8d7da; color: #721c24"
        elif col_name in ["夏普比率", "索提诺比率", "卡玛比率", "年化收益(%)", "日胜率(%)"]:
            if val >= risk_df[col_name].quantile(0.7):
                return "background-color: #d4edda; color: #155724"
            elif val <= risk_df[col_name].quantile(0.3):
                return "background-color: #f8d7da; color: #721c24"
        return ""

    styled = risk_df.style.apply(
        lambda row: [highlight_risk(row[col], col) for col in risk_df.columns],
        axis=1,
    ).format("{:.2f}")

    st.dataframe(styled, use_container_width=True)

    # ── 图表区域 ──────────────────────────────────────
    st.divider()
    st.subheader("📈 可视化对比")

    col1, col2 = st.columns(2)

    with col1:
        # 收益 vs 回撤 散点图
        fig = px.scatter(
            risk_df.reset_index(),
            x="最大回撤(%)",
            y="年化收益(%)",
            text="基金",
            size="年化波动率(%)",
            title="收益 vs 回撤 (气泡大小=波动率)",
            labels={"年化收益(%)": "年化收益 (%)", "最大回撤(%)": "最大回撤 (%)"},
        )
        fig.add_hline(y=0, line_dash="dash", line_color="grey", opacity=0.5)
        fig.add_vline(x=0, line_dash="dash", line_color="grey", opacity=0.5)
        # 理想区域：左上（高收益低回撤）
        fig.add_annotation(
            x=risk_df["最大回撤(%)"].min(),
            y=risk_df["年化收益(%)"].max(),
            text="✨ 理想方向",
            showarrow=False,
            font=dict(color="green"),
        )
        fig.update_traces(textposition="top center", marker=dict(opacity=0.7))
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # 卡玛比率 & 夏普比率 柱状图
        bar_df = risk_df.reset_index()
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=bar_df["基金"],
            y=bar_df["卡玛比率"],
            name="卡玛比率",
            marker_color="#636EFA",
            text=[f"{v:.2f}" for v in bar_df["卡玛比率"]],
            textposition="outside",
        ))
        fig.add_trace(go.Bar(
            x=bar_df["基金"],
            y=bar_df["夏普比率"],
            name="夏普比率",
            marker_color="#00CC96",
            text=[f"{v:.2f}" for v in bar_df["夏普比率"]],
            textposition="outside",
        ))
        fig.update_layout(
            title="卡玛比率 & 夏普比率对比",
            barmode="group",
            yaxis_title="比率",
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── 累计收益走势 ──────────────────────────────────
    st.subheader("📈 累计收益走势 (归一化)")
    fig_cum = go.Figure()
    for name, nav in funds_nav.items():
        cum_ret = (nav / nav.dropna().iloc[0] - 1) * 100  # 百分比
        fig_cum.add_trace(go.Scatter(
            y=cum_ret.values,
            mode="lines",
            name=f"{name} ({cum_ret.iloc[-1]:+.1f}%)",
            hovertemplate=f"{name}<br>累计收益: %{{y:.2f}}%<extra></extra>",
        ))
    fig_cum.update_layout(
        title="累计收益对比 (起始 = 0%)",
        yaxis_title="累计收益 (%)",
        xaxis_title="交易日",
        hovermode="x unified",
    )
    fig_cum.add_hline(y=0, line_dash="dash", line_color="grey", opacity=0.5)
    st.plotly_chart(fig_cum, use_container_width=True)

    # ── 回撤曲线 ──────────────────────────────────────
    st.subheader("📉 回撤曲线")

    # 计算每只基金的回撤序列
    drawdown_data = {}
    for name, nav in funds_nav.items():
        cumulative = (1 + nav.pct_change().dropna()).cumprod()
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / running_max * 100
        drawdown_data[name] = drawdown

    fig = go.Figure()
    for name, dd in drawdown_data.items():
        fig.add_trace(go.Scatter(
            y=dd.values,
            mode="lines",
            name=f"{name} (最大回撤 {dd.min():.1f}%)",
            hovertemplate=f"{name}<br>回撤: %{{y:.2f}}%<extra></extra>",
        ))
    fig.update_layout(
        title="回撤曲线对比",
        yaxis_title="回撤 (%)",
        xaxis_title="交易日",
        yaxis=dict(autorange="reversed"),  # 回撤向下更直观
        hovermode="x unified",
    )
    fig.add_hline(y=0, line_dash="dash", line_color="grey", opacity=0.5)
    st.plotly_chart(fig, use_container_width=True)

    # ── 风险指标雷达图 ──────────────────────────────────
    st.subheader("🕸️ 风险-收益雷达图")
    radar_metrics = ["年化收益(%)", "卡玛比率", "夏普比率", "索提诺比率", "日胜率(%)"]
    # 反转指标：值越小越好 → 取反使其在雷达图中方向一致
    radar_inverse = ["最大回撤(%)", "年化波动率(%)"]
    # 对反转指标做归一化反转: (max - val) / (max - min)
    radar_df = risk_df[radar_metrics + radar_inverse].copy()
    for col in radar_metrics + radar_inverse:
        rng = radar_df[col].max() - radar_df[col].min()
        if rng == 0:
            radar_df[col] = 0.5
        elif col in radar_inverse:
            radar_df[col] = (radar_df[col].max() - radar_df[col]) / rng  # 越小越好 → 归一化后越大越好
        else:
            radar_df[col] = (radar_df[col] - radar_df[col].min()) / rng

    fig = go.Figure()
    categories = radar_metrics + [f"{m}⁻¹" for m in radar_inverse]
    for name in radar_df.index:
        fig.add_trace(go.Scatterpolar(
            r=radar_df.loc[name].values,
            theta=categories,
            fill="toself",
            name=name,
        ))
    fig.update_layout(
        polar=dict(radialaxis=dict(range=[0, 1])),
        title="风险调整后表现 (越大越好)",
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── 金额模拟 ──────────────────────────────────────
    st.divider()
    st.subheader("💰 投入模拟")

    # 为每只基金计算模拟结果
    sim_results = []
    sim_nav_data = {}  # for chart: cumulative value over time
    
    for name, nav_series in funds_nav.items():
        nav_series = nav_series.dropna()
        if len(nav_series) < 10:
            continue
        
        initial_nav = nav_series.iloc[0]
        final_nav = nav_series.iloc[-1]

        if invest_mode == "一次性投入":
            per_fund = total_amount / len(funds_nav)
            units = per_fund / initial_nav
            final_value = units * final_nav
            total_invested = per_fund
        else:
            # 定投: 等分到每个定投日
            freq_days = {"每周": 5, "每两周": 10, "每月": 21}
            step = freq_days.get(invest_freq, 21)
            total_invested = 0
            units = 0
            nav_dates = nav_series.index.tolist()
            
            for i in range(0, len(nav_dates), step):
                idx = nav_dates[i]
                buy_nav = nav_series.loc[idx]
                units += invest_period / buy_nav
                total_invested += invest_period
            
            final_value = units * final_nav

        profit = final_value - total_invested
        ret_pct = (profit / total_invested * 100) if total_invested > 0 else 0

        sim_results.append({
            "基金": name,
            "投入金额(元)": round(total_invested, 0),
            "最终市值(元)": round(final_value, 0),
            "盈亏(元)": round(profit, 0),
            "收益率(%)": round(ret_pct, 2),
            "期初净值": round(initial_nav, 4),
            "期末净值": round(final_nav, 4),
            "持有份额": round(units, 2),
        })

        # 计算累计价值曲线（定投用逐步买入）
        cumulative = (1 + nav_series.pct_change().fillna(0)).cumprod()
        if invest_mode == "一次性投入":
            per_fund = total_amount / len(funds_nav)
            sim_nav_data[name] = cumulative * per_fund
        else:
            # 定投累计价值
            cum_values = []
            invested = 0
            total_units = 0
            for i, (dt, nav) in enumerate(nav_series.items()):
                if i % step == 0:
                    total_units += invest_period / nav
                    invested += invest_period
                cum_values.append(total_units * nav)
            sim_nav_data[name] = pd.Series(cum_values, index=nav_series.index)

    if sim_results:
        sim_df = pd.DataFrame(sim_results).set_index("基金")
        
        # 着色
        def color_profit(val):
            if val > 0:
                return "color: #155724; background-color: #d4edda"
            elif val < 0:
                return "color: #721c24; background-color: #f8d7da"
            return ""
        
        styled_sim = sim_df.style.format({
            "投入金额(元)": "{:,.0f}",
            "最终市值(元)": "{:,.0f}",
            "盈亏(元)": "{:+,.0f}",
            "收益率(%)": "{:+.2f}",
            "期初净值": "{:.4f}",
            "期末净值": "{:.4f}",
            "持有份额": "{:,.2f}",
        }).map(color_profit, subset=["盈亏(元)", "收益率(%)"])

        st.dataframe(styled_sim, use_container_width=True)

        # 汇总
        total_inv = sim_df["投入金额(元)"].sum()
        total_val = sim_df["最终市值(元)"].sum()
        total_profit = total_val - total_inv
        cols = st.columns(4)
        cols[0].metric("总投入", f"¥{total_inv:,.0f}")
        cols[1].metric("总市值", f"¥{total_val:,.0f}")
        cols[2].metric("总盈亏", f"¥{total_profit:+,.0f}",
                       delta=f"{total_profit/total_inv*100:+.1f}%" if total_inv > 0 else None)
        cols[3].metric("投入方式",
                       f"{invest_mode}" + (f" · {invest_freq}{invest_period}元" if invest_mode == "定投" else f" · 各{total_amount/len(funds_nav):,.0f}元"))

        # 累计价值曲线
        st.subheader("📈 模拟账户价值走势")
        fig_val = go.Figure()
        for name, vals in sim_nav_data.items():
            fig_val.add_trace(go.Scatter(
                x=vals.index,
                y=vals.values,
                mode="lines",
                name=name,
            ))
        fig_val.update_layout(
            title="模拟账户价值变化",
            yaxis_title="账户价值 (元)",
            hovermode="x unified",
        )
        st.plotly_chart(fig_val, use_container_width=True)

    # ── 每日净值明细 ──────────────────────────────────
    st.divider()
    st.subheader("📋 每日净值、收益与市值")

    # 合并所有基金的日数据（按日期对齐）
    daily_table = None
    for name, df in funds_daily.items():
        d = df[["date", "nav", "daily_return"]].copy()
        d = d.rename(columns={"nav": f"{name}-净值", "daily_return": f"{name}-日收益%"})
        d["date"] = pd.to_datetime(d["date"]).dt.date

        # 计算每日模拟市值
        nav_arr = df["nav"].values
        if invest_mode == "一次性投入":
            per_fund = total_amount / len(funds_nav)
            initial_nav = nav_arr[~pd.isna(nav_arr)][0]
            units = per_fund / initial_nav
            d[f"{name}-市值"] = [int(units * n) if pd.notna(n) else None for n in nav_arr]
            d[f"{name}-盈亏"] = [int(units * n - per_fund) if pd.notna(n) else None for n in nav_arr]
        else:
            freq_days = {"每周": 5, "每两周": 10, "每月": 21}
            step = freq_days.get(invest_freq, 21)
            cum_units = 0
            total_inv = 0
            values = []
            profits = []
            for i, n in enumerate(nav_arr):
                if pd.notna(n):
                    if i % step == 0:
                        cum_units += invest_period / n
                        total_inv += invest_period
                    values.append(int(cum_units * n))
                    profits.append(int(cum_units * n - total_inv))
                else:
                    values.append(None)
                    profits.append(None)
            d[f"{name}-市值"] = values
            d[f"{name}-盈亏"] = profits

        if daily_table is None:
            daily_table = d
        else:
            daily_table = daily_table.merge(d, on="date", how="outer")

    if daily_table is not None:
        daily_table = daily_table.sort_values("date", ascending=False).reset_index(drop=True)
        
        fmt = {}
        for c in daily_table.columns:
            if "净值" in c:
                fmt[c] = "{:.4f}"
            elif "日收益" in c:
                fmt[c] = "{:+.2f}"
            elif "市值" in c:
                fmt[c] = "{:,.0f}"
            elif "盈亏" in c:
                fmt[c] = "{:+,.0f}"

        def color_pnl(val):
            if pd.isna(val):
                return ""
            return "color: #155724" if val >= 0 else "color: #721c24"

        styled_daily = daily_table.style.format(fmt)
        pnl_cols = [c for c in daily_table.columns if "盈亏" in c]
        if pnl_cols:
            styled_daily = styled_daily.map(color_pnl, subset=pnl_cols)

        st.dataframe(
            styled_daily,
            use_container_width=True,
            height=400,
            hide_index=True,
        )
        
        # 下载每日数据
        csv_daily = daily_table.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 下载每日净值明细 CSV",
            data=csv_daily,
            file_name=f"每日净值明细_{start_str}_{end_str}.csv",
            mime="text/csv",
        )

    # ── 数据下载 ──────────────────────────────────────
    st.divider()
    csv = risk_df.to_csv().encode("utf-8")
    st.download_button(
        label="📥 下载风险指标 CSV",
        data=csv,
        file_name=f"基金风险指标_{start_str}_{end_str}.csv",
        mime="text/csv",
    )

else:
    st.info("👆 选择基金后点击 **开始分析** 按钮")
