"""Universe YAML loading, including optional sector labels."""

from __future__ import annotations

from tossai.market.universe import load_universe


def test_loads_symbols_with_optional_sector(tmp_path):
    f = tmp_path / "u.yaml"
    f.write_text(
        "KRX:\n"
        '  - { symbol: "005930", name: "Samsung", sector: "Semiconductor" }\n'
        '  - "000660"\n'                       # bare string, no sector
        "US:\n"
        '  - { symbol: "AAPL", name: "Apple" }\n'  # mapping, no sector
    )
    syms = load_universe(str(f), "BOTH")
    by = {s.symbol: s for s in syms}
    assert by["005930"].sector == "Semiconductor" and by["005930"].name == "Samsung"
    assert by["000660"].sector is None
    assert by["AAPL"].sector is None


def test_market_filter(tmp_path):
    f = tmp_path / "u.yaml"
    f.write_text('KRX:\n  - "005930"\nUS:\n  - "AAPL"\n')
    assert [s.symbol for s in load_universe(str(f), "US")] == ["AAPL"]


def test_missing_file_returns_empty(tmp_path):
    assert load_universe(str(tmp_path / "nope.yaml"), "BOTH") == []
