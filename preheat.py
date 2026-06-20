"""
预热脚本 — 每天定时运行，提前把数据拉到 SQLite 缓存
用法:
  python preheat.py              # 预热默认类型 + 热门基金
  python preheat.py --all        # 预热全部类型
  python preheat.py --funds 20   # 每个类型预热前 20 只
"""

import sys
import time
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 修复 Windows GBK 编码
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# 确保当前目录在 path 中
sys.path.insert(0, ".")

from data_fetcher import fetch_fund_list, fetch_fund_nav
from db import init_db, save_fund_list, save_nav, get_cache_stats

# ── 配置 ───────────────────────────────────────────────
DEFAULT_TYPES = ["混合型", "股票型", "指数型", "债券型", "QDII"]
TOP_N = 10  # 每个类型预热前 N 只基金
NAV_YEARS = 2  # 拉取近 N 年净值


def warm_fund_list(fund_type: str) -> int:
    """预热基金列表，返回基金数量"""
    print(f"  📋 拉取 {fund_type} 列表...", end=" ", flush=True)
    t0 = time.time()
    df = fetch_fund_list(fund_type)
    if not df.empty:
        save_fund_list(fund_type, df)
    elapsed = time.time() - t0
    print(f"{len(df)} 只 ({elapsed:.1f}s)")
    return len(df)


def warm_fund_nav(code: str, name: str, years: int = 2) -> bool:
    """预热单只基金净值，返回是否成功"""
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = f"{datetime.now().year - years}0101"
    try:
        df = fetch_fund_nav(str(code), start_date, end_date)
        if not df.empty and "nav" in df.columns and len(df) >= 30:
            save_nav(str(code), df)
            return True
    except Exception:
        pass
    return False


def warm_top_funds(fund_type: str, top_n: int = 10, years: int = 2) -> tuple[int, int]:
    """预热前 N 只基金的净值"""
    df = fetch_fund_list(fund_type)
    if df.empty:
        return 0, 0

    top = df.head(top_n)
    codes = top["code"].tolist()
    names = top["name"].tolist()
    total = len(codes)
    success = 0

    print(f"  📈 预热 {fund_type} TOP{total} 净值...")

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(warm_fund_nav, c, n, years): (c, n)
            for c, n in zip(codes, names)
        }
        completed = 0
        for future in as_completed(futures):
            code, name = futures[future]
            completed += 1
            ok = future.result()
            if ok:
                success += 1
            status = "✅" if ok else "❌"
            print(f"    [{completed}/{total}] {status} {name} ({code})")

    return total, success


def main():
    parser = argparse.ArgumentParser(description="基金数据预热脚本")
    parser.add_argument("--all", action="store_true", help="预热全部类型")
    parser.add_argument("--funds", type=int, default=TOP_N,
                        help=f"每个类型预热前 N 只基金 (默认 {TOP_N})")
    parser.add_argument("--types", nargs="+", default=DEFAULT_TYPES,
                        help="要预热的基金类型")
    parser.add_argument("--years", type=int, default=NAV_YEARS,
                        help="拉取近 N 年净值")
    args = parser.parse_args()

    init_db()
    print(f"🔥 基金数据预热 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   类型: {', '.join(args.types)}")
    print(f"   每类 TOP{args.funds} · 近{args.years}年净值")
    print("-" * 50)

    total_funds = 0
    total_nav_ok = 0
    total_nav = 0

    for ftype in args.types:
        # 预热列表
        n = warm_fund_list(ftype)
        total_funds += n

        # 预热净值
        tried, ok = warm_top_funds(ftype, args.funds, args.years)
        total_nav += tried
        total_nav_ok += ok

    print("-" * 50)
    print(f"✅ 完成! 列表 {total_funds} 只 · 净值 {total_nav_ok}/{total_nav} 只成功")

    stats = get_cache_stats()
    print(f"📦 缓存: {stats['已缓存基金数']} 只 · "
          f"{stats['净值记录数']} 条净值 · "
          f"{stats['数据库大小']}")


if __name__ == "__main__":
    main()
