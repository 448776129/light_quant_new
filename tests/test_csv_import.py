"""BUG-003 本地 CSV 导入：Volume 列解析

yfinance 风格的历史 CSV 中 Volume 常写作浮点/科学计数法（1234567.0、1.2345E7）。
当前用 int("1234567.0") 解析会抛 ValueError 并被静默置为 None，
导致 volume / amihud 两个因子族取不到数据。
"""
from __future__ import annotations

import gzip


def _write_csv(base, name: str = "AAPL.csv", rows: list[str] | None = None):
    d = base / "us" / "kline"
    d.mkdir(parents=True, exist_ok=True)
    body = "Datetime,Open,High,Low,Close,Adj Close,Volume\n" + "\n".join(
        rows or [
            "2024-01-02,1.0,1.1,0.9,1.05,1.05,1234567.0",
            "2024-01-03,1.05,1.15,0.95,1.10,1.10,1.2345E7",
            "2024-01-04,1.10,1.20,1.00,1.15,1.15,98765.00",
        ])
    with gzip.open(d / name, "wt", encoding="utf-8", newline="") as f:
        f.write(body + "\n")
    return base


def test_volume_float_string_is_parsed(tmp_path):
    from light_quant_new.market import client
    base = _write_csv(tmp_path)
    rows = client.read_csv_gzip("AAPL", base_dir=str(base))

    assert len(rows) == 3, f"应解析出 3 行，实际 {len(rows)}"
    vols = [r["Volume"] for r in rows]
    assert all(v is not None for v in vols), f"Volume 解析为 None: {vols}"
    assert vols[0] == 1234567, f"1234567.0 应解析为 1234567，实际 {vols[0]}"
    assert vols[1] == 12345000, f"1.2345E7 应解析为 12345000，实际 {vols[1]}"
    assert vols[2] == 98765, f"98765.00 应解析为 98765，实际 {vols[2]}"


def test_imported_klines_keep_volume(tmp_path, monkeypatch):
    """经服务层导入后，库中的 volume 不应全为空。"""
    from light_quant_new.core import config
    from light_quant_new.market import service, storage

    base = _write_csv(tmp_path, rows=[
        f"2024-01-{i + 1:02d},1.0,1.1,0.9,{1.0 + i * 0.01},{1.0 + i * 0.01},1234567.0"
        for i in range(28)
    ])
    monkeypatch.setattr(config, "KLINE_CSV_DIR", str(base))

    result = service.import_csv_all()
    assert result["inserted"] > 0, f"导入失败: {result}"

    klines = storage.get_klines("AAPL", "1d", limit=5)
    assert klines, "库中无 K 线"
    assert all(k["volume"] is not None for k in klines), \
        f"入库后 volume 为空: {[k['volume'] for k in klines]}"


def test_volume_factor_not_empty_after_import(tmp_path, monkeypatch):
    """volume 因子族在导入后应能算出非空值（回归 BUG-003 的实际影响）。"""
    from light_quant_new.core import config
    from light_quant_new.factors import factor_families as ff
    from light_quant_new.market import service

    base = _write_csv(tmp_path, rows=[
        f"2024-{1 + i // 28:02d}-{(i % 28) + 1:02d},1.0,1.1,0.9,{1.0 + i * 0.01},"
        f"{1.0 + i * 0.01},{100000 + i * 1000}.0"
        for i in range(120)
    ])
    monkeypatch.setattr(config, "KLINE_CSV_DIR", str(base))
    assert service.import_csv_all()["inserted"] > 0

    df = service.get_klines_dataframe(["AAPL"], "1d")
    assert not df.empty, "取数为空"
    s = ff.compute_raw("volume", {"W": 10}, df)
    assert not s.empty, "volume 因子全空（volume 列解析失败）"
