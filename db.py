"""
SQLite 持久化缓存模块
- 净值数据按 (code, date) 存储，重启不丢
- 自动检测数据新鲜度，过期自动刷新
"""

import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "fund_cache.db"


def _conn():
    """获取数据库连接（WAL 模式，支持并发读）"""
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def init_db():
    """初始化表结构"""
    with _conn() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS fund_nav (
                code TEXT NOT NULL,
                date TEXT NOT NULL,
                nav REAL,
                daily_return REAL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (code, date)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS fund_list (
                code TEXT NOT NULL,
                fund_type TEXT NOT NULL,
                name TEXT,
                nav REAL,
                ret_1w REAL, ret_1m REAL, ret_3m REAL, ret_6m REAL,
                ret_1y REAL, ret_2y REAL, ret_3y REAL,
                ret_ytd REAL, ret_since_start REAL,
                daily_return REAL,
                fee TEXT, aum TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (code, fund_type)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                fund_type TEXT,
                added_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_nav_code_date ON fund_nav(code, date)
        """)
        db.commit()


# ── 收藏管理 ───────────────────────────────────────────

def get_favorites() -> list[dict]:
    """获取所有收藏的基金"""
    with _conn() as db:
        rows = db.execute(
            "SELECT code, name, fund_type, added_at FROM favorites ORDER BY added_at DESC"
        ).fetchall()
    return [{"code": r[0], "name": r[1], "fund_type": r[2], "added_at": r[3]} for r in rows]


def get_favorite_codes() -> set[str]:
    """获取收藏的基金代码集合"""
    with _conn() as db:
        rows = db.execute("SELECT code FROM favorites").fetchall()
    return {r[0] for r in rows}


def add_favorite(code: str, name: str, fund_type: str = ""):
    """添加收藏"""
    with _conn() as db:
        db.execute(
            "INSERT OR REPLACE INTO favorites (code, name, fund_type, added_at) VALUES (?,?,?,?)",
            (str(code), str(name)[:100], str(fund_type), datetime.now().isoformat()),
        )
        db.commit()


def remove_favorite(code: str):
    """取消收藏"""
    with _conn() as db:
        db.execute("DELETE FROM favorites WHERE code = ?", (str(code),))
        db.commit()


def is_favorite(code: str) -> bool:
    """检查是否已收藏"""
    with _conn() as db:
        row = db.execute("SELECT 1 FROM favorites WHERE code = ?", (str(code),)).fetchone()
    return row is not None


# ── 净值缓存 ───────────────────────────────────────────

def get_cached_nav(code: str, start: str, end: str) -> pd.DataFrame | None:
    """从 SQLite 读取净值数据，若无或过期返回 None"""
    with _conn() as db:
        df = pd.read_sql_query(
            "SELECT date, nav, daily_return FROM fund_nav WHERE code = ? AND date BETWEEN ? AND ? ORDER BY date",
            db,
            params=(str(code), start, end),
        )
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    return df


def save_nav(code: str, df: pd.DataFrame):
    """保存净值数据到 SQLite（INSERT OR REPLACE）"""
    if df.empty:
        return
    now = datetime.now().isoformat()
    rows = []
    for _, row in df.iterrows():
        d = row["date"]
        if hasattr(d, "strftime"):
            d = d.strftime("%Y%m%d")  # 统一 YYYYMMDD
        rows.append((
            str(code), str(d),
            float(row["nav"]) if pd.notna(row.get("nav")) else None,
            float(row["daily_return"]) if pd.notna(row.get("daily_return")) else None,
            now,
        ))
    with _conn() as db:
        db.executemany(
            "INSERT OR REPLACE INTO fund_nav (code, date, nav, daily_return, updated_at) VALUES (?,?,?,?,?)",
            rows,
        )
        db.commit()


def is_nav_fresh(code: str) -> bool:
    """检查该基金的净值是否已包含最近交易日的数据"""
    today = date.today()
    # 回退 3 天容错（周末/节假日无净值）
    check_date = today.isoformat()
    with _conn() as db:
        row = db.execute(
            "SELECT COUNT(*) FROM fund_nav WHERE code = ? AND date >= ?",
            (str(code), (today - timedelta(days=3)).isoformat()),
        ).fetchone()
    return (row[0] or 0) > 0


# ── 基金列表缓存 ───────────────────────────────────────

def get_cached_fund_list(fund_type: str) -> pd.DataFrame | None:
    """从 SQLite 读取基金列表"""
    with _conn() as db:
        df = pd.read_sql_query(
            "SELECT * FROM fund_list WHERE fund_type = ?",
            db,
            params=(fund_type,),
        )
    if df.empty:
        return None
    return df


def save_fund_list(fund_type: str, df: pd.DataFrame):
    """保存基金列表到 SQLite"""
    if df.empty:
        return
    now = datetime.now().isoformat()
    rows = []
    for _, row in df.iterrows():
        rows.append((
            str(row.get("code", "")), fund_type,
            str(row.get("name", ""))[:100],
            float(row["nav"]) if pd.notna(row.get("nav")) else None,
            float(row["ret_1w"]) if pd.notna(row.get("ret_1w")) else None,
            float(row["ret_1m"]) if pd.notna(row.get("ret_1m")) else None,
            float(row["ret_3m"]) if pd.notna(row.get("ret_3m")) else None,
            float(row["ret_6m"]) if pd.notna(row.get("ret_6m")) else None,
            float(row["ret_1y"]) if pd.notna(row.get("ret_1y")) else None,
            float(row["ret_2y"]) if pd.notna(row.get("ret_2y")) else None,
            float(row["ret_3y"]) if pd.notna(row.get("ret_3y")) else None,
            float(row["ret_ytd"]) if pd.notna(row.get("ret_ytd")) else None,
            float(row["ret_since_start"]) if pd.notna(row.get("ret_since_start")) else None,
            float(row["daily_return"]) if pd.notna(row.get("daily_return")) else None,
            str(row.get("fee", ""))[:20],
            str(row.get("custom", ""))[:50],
            now,
        ))
    with _conn() as db:
        db.execute("DELETE FROM fund_list WHERE fund_type = ?", (fund_type,))
        db.executemany(
            """INSERT INTO fund_list
               (code, fund_type, name, nav,
                ret_1w, ret_1m, ret_3m, ret_6m, ret_1y, ret_2y, ret_3y,
                ret_ytd, ret_since_start, daily_return, fee, aum, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        db.commit()


def is_fund_list_fresh(fund_type: str) -> bool:
    """基金列表是否今天更新过"""
    today = date.today().isoformat()
    with _conn() as db:
        row = db.execute(
            "SELECT COUNT(*) FROM fund_list WHERE fund_type = ? AND date(updated_at) = ?",
            (fund_type, today),
        ).fetchone()
    return (row[0] or 0) > 0


# ── 工具 ───────────────────────────────────────────────

def get_cache_stats() -> dict:
    """返回缓存统计信息"""
    with _conn() as db:
        nav_count = db.execute("SELECT COUNT(*) FROM fund_nav").fetchone()[0]
        list_count = db.execute("SELECT COUNT(DISTINCT fund_type) FROM fund_list").fetchone()[0]
        fund_count = db.execute("SELECT COUNT(DISTINCT code) FROM fund_list").fetchone()[0]
        latest_nav = db.execute("SELECT MAX(updated_at) FROM fund_nav").fetchone()[0]
        latest_list = db.execute("SELECT MAX(updated_at) FROM fund_list").fetchone()[0]
        db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    return {
        "净值记录数": nav_count,
        "基金列表类型数": list_count,
        "已缓存基金数": fund_count,
        "最新净值缓存": latest_nav or "无",
        "最新列表缓存": latest_list or "无",
        "数据库大小": f"{db_size / 1024 / 1024:.1f} MB",
    }


# 首次导入时自动初始化
init_db()
