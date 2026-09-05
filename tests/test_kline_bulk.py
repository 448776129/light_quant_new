"""OPT-001 K 线批量写入

原实现逐行「先 UPDATE，无命中再 INSERT」，每根 K 线 2 条 SQL。
批量导入数百个标的（每标的数千行）时串行耗时达分钟级。
"""
from __future__ import annotations

import time

N_ROWS = 20000


def _rows(n: int, price_off: float = 0.0):
    out = []
    for i in range(n):
        d = (i // 86400) % 28 + 1
        t = f"{(i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d}"
        out.append({"Datetime": f"2020-01-{d:02d} {t}", "Open": 100.0 + i,
                    "High": 101.0 + i, "Low": 99.0 + i, "Close": 100.5 + i + price_off,
                    "Adj Close": 100.5 + i + price_off, "Volume": 1000 + i})
    return out


def test_upsert_counts_insert_then_update():
    from light_quant_new.market import storage as mstorage
    rows = _rows(500)
    assert mstorage.upsert_kline("X", "1d", rows) == (500, 0), "首次应全部为新增"
    assert mstorage.upsert_kline("X", "1d", rows) == (0, 500), "重复导入应全部为更新"
    assert mstorage.kline_range("X", "1d")["n"] == 500, "重复导入不应产生重复行"


def test_upsert_refreshes_price():
    from light_quant_new.market import storage as mstorage
    rows = _rows(50)
    mstorage.upsert_kline("Y", "1d", rows)
    first = mstorage.get_klines("Y", "1d", limit=1)[0]

    changed = _rows(50, price_off=999.0)
    ins, upd = mstorage.upsert_kline("Y", "1d", changed)
    after = mstorage.get_klines("Y", "1d", limit=1)[0]

    assert (ins, upd) == (0, 50)
    assert after["close"] == first["close"] + 999.0, "更新未生效"
    assert mstorage.kline_range("Y", "1d")["n"] == 50


def test_upsert_uses_batched_execution():
    """核心优化验证（与磁盘快慢无关）：upsert_kline 必须把 2N 条逐行 SQL
    压成极少几条——1 次 SELECT(查已有) + 1 次 executemany(批量插入)。

    优化前：每根 K 线「先 UPDATE 再 INSERT」= 2N 条 SQL（2 万行 = 4 万条），
    在远程/高延迟数据源下耗时随行数线性膨胀。
    """
    from light_quant_new.core import storage as core_storage
    from light_quant_new.market import storage as mstorage

    class _CountingConn:
        def __init__(self, real):
            self._real = real
            self.execute_calls = 0
            self.executemany_calls = 0

        def execute(self, sql, params=()):
            self.execute_calls += 1
            return self._real.execute(sql, params)

        def executemany(self, sql, params):
            self.executemany_calls += 1
            return self._real.executemany(sql, params)

        def __getattr__(self, name):
            return getattr(self._real, name)

    real_conn = core_storage._conn()
    wrapper = _CountingConn(real_conn)
    _orig_conn = core_storage._conn
    core_storage._conn = lambda: wrapper
    try:
        rows = _rows(N_ROWS)
        ins, upd = mstorage.upsert_kline("BATCH", "1m", rows)
        assert (ins, upd) == (N_ROWS, 0), f"批量插入计数异常: {(ins, upd)}"
        # 1 次 SELECT(查已有行) + 1 次 executemany(批量 INSERT)
        assert wrapper.execute_calls <= 1, f"查已有行不应多次执行: {wrapper.__dict__}"
        assert wrapper.executemany_calls == 1, \
            f"应使用单条 executemany 批量插入: {wrapper.__dict__}"

        # 再做一次全更新路径，确认同样走单条 executemany
        wrapper.execute_calls = 0
        wrapper.executemany_calls = 0
        ins2, upd2 = mstorage.upsert_kline("BATCH", "1m", rows)
        assert (ins2, upd2) == (0, N_ROWS), f"重复导入计数异常: {(ins2, upd2)}"
        assert wrapper.executemany_calls == 1, \
            f"更新路径也应走单条 executemany: {wrapper.__dict__}"
    finally:
        core_storage._conn = _orig_conn


def test_bulk_upsert_reasonable_time():
    """回归护栏：2 万行单标的写入不应出现灾难性退化（环境磁盘慢时放宽上限）。

    注：绝对耗时受沙箱/CI 磁盘（WAL fsync）影响，本用例只防回归，
    真正的「少 SQL」优化由 test_upsert_uses_batched_execution 保证。
    """
    from light_quant_new.market import storage as mstorage
    rows = _rows(N_ROWS)
    t0 = time.time()
    mstorage.upsert_kline("SLOW", "1m", rows)
    elapsed = time.time() - t0
    assert mstorage.kline_range("SLOW", "1m")["n"] == N_ROWS, "行数不符"
    assert elapsed < 8.0, (
        f"写入 {N_ROWS} 行耗时 {elapsed:.2f}s（{N_ROWS / elapsed:,.0f} 行/秒），"
        f"疑似出现灾难性退化")


def test_empty_rows_is_noop():
    from light_quant_new.market import storage as mstorage
    assert mstorage.upsert_kline("Z", "1d", []) == (0, 0)
    assert mstorage.upsert_kline("Z", "1d", [{"Datetime": ""}, {"Open": 1}]) == (0, 0)
