"""
自检脚本 — 每轮修改后运行，验证所有功能正常
用法: python check.py
"""

import sys
import time
import traceback
import os

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

PASS = 0
FAIL = 0
ERRORS = []


def check(name, fn):
    global PASS, FAIL
    t0 = time.time()
    try:
        fn()
        print(f"  OK {name} ({time.time() - t0:.1f}s)")
        PASS += 1
    except Exception as e:
        print(f"  FAIL {name} ({time.time() - t0:.1f}s): {e}")
        FAIL += 1
        ERRORS.append((name, str(e)))


def main():
    global PASS, FAIL
    print("Fund Screener Self-Check")
    print("=" * 50)

    # 1. imports
    print("\n--- Modules ---")
    check("db", lambda: __import__("db"))
    check("data_fetcher", lambda: __import__("data_fetcher"))
    check("risk_metrics", lambda: __import__("risk_metrics"))
    check("preheat", lambda: __import__("preheat"))

    # 2. database
    print("\n--- SQLite ---")
    from db import init_db, get_cache_stats

    def _db():
        init_db()
        s = get_cache_stats()
        if not s.get("数据库大小"):
            raise Exception("stats empty")

    check("init_db + stats", _db)

    # 3. favorites
    print("\n--- Favorites ---")
    from db import add_favorite, remove_favorite, is_favorite, get_favorites, get_favorite_codes
    tc = "999999"
    tn = "TEST_FAV_FUND"

    check("add_favorite", lambda: add_favorite(tc, tn, "测试型"))

    def _is():
        if not is_favorite(tc):
            raise Exception("not found")
    check("is_favorite", _is)

    def _list():
        if len(get_favorites()) == 0:
            raise Exception("empty list")
    check("get_favorites", _list)

    def _codes():
        if tc not in get_favorite_codes():
            raise Exception("code not in set")
    check("get_favorite_codes", _codes)

    check("remove_favorite", lambda: remove_favorite(tc))
    check("removed check", lambda: None if not is_favorite(tc) else (_ for _ in ()).throw(Exception("still exists")))

    # 4. fund list
    print("\n--- Fund List ---")
    from data_fetcher import fetch_fund_list_cached

    def _fl():
        df, _ = fetch_fund_list_cached("股票型")
        if df.empty:
            raise Exception("empty")
        if "code" not in df.columns:
            raise Exception("missing code")
        if len(df) < 100:
            raise Exception(f"too few: {len(df)}")
    check("stock fund list", _fl)

    # 5. NAV
    print("\n--- NAV ---")
    from data_fetcher import fetch_fund_nav_cached

    def _nav():
        df, _ = fetch_fund_nav_cached("000001", "20240101", "20250630")
        if df.empty:
            raise Exception("empty")
        if "nav" not in df.columns:
            raise Exception("missing nav")
        if len(df) < 30:
            raise Exception(f"too few rows: {len(df)}")
    check("000001 NAV", _nav)

    # 6. risk metrics
    print("\n--- Risk ---")
    from risk_metrics import all_risk_metrics

    def _risk():
        df, _ = fetch_fund_nav_cached("000001", "20240101", "20250630")
        m = all_risk_metrics(df["nav"].dropna())
        for k in ["年化收益(%)", "最大回撤(%)", "夏普比率", "卡玛比率"]:
            if k not in m:
                raise Exception(f"missing: {k}")
    check("risk calc", _risk)

    # 7. preheat
    print("\n--- Preheat ---")
    import subprocess

    def _preheat():
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run(
            [sys.executable, "preheat.py", "--funds", "2", "--types", "股票型"],
            capture_output=True, text=True, timeout=60, env=env, cwd=".",
        )
        if r.returncode != 0:
            raise Exception(f"rc={r.returncode} stderr={r.stderr[-200:]}")
    check("preheat 2 funds", _preheat)

    # 8. app syntax
    print("\n--- app.py ---")
    import ast
    check("syntax", lambda: ast.parse(open("app.py", encoding="utf-8").read()))

    # summary
    print("\n" + "=" * 50)
    total = PASS + FAIL
    if FAIL == 0:
        print(f"ALL {total} CHECKS PASSED")
    else:
        print(f"PASS: {PASS}/{total}")
        print(f"FAIL: {FAIL}")
        for n, e in ERRORS:
            print(f"  [{n}] {e}")

    return FAIL == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
