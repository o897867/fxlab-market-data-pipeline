"""consensus 导入解析单测：两种日期格式、停摆延迟参照月、K/% 单位。"""

import pytest
from macropulse.attribution import consensus_import as ci

pytestmark = pytest.mark.unit


def test_parse_slash_date_pct():
    rows = ci.parse_investing("13/09/2022 (Aug)\t22:30\t0.1%\t-0.1%\n0.0%", "pct")
    assert len(rows) == 1
    r = rows[0]
    assert r["release_date"] == "2022-09-13"
    assert r["ref_month"] == "2022-08-01"
    assert r["actual"] == 0.1 and r["forecast"] == -0.1


def test_parse_named_date():
    rows = ci.parse_investing("Jun 10, 2026 (May)\t22:30\t0.2%\t0.3%\n0.4%", "pct")
    assert rows[0]["release_date"] == "2026-06-10"
    assert rows[0]["ref_month"] == "2026-05-01"


def test_label_ref_month_handles_delay():
    # 停摆延迟：Oct 数据 2026-01 才发，ref 必须按标签=2025-10，而非"发布月−1"=2025-12
    rows = ci.parse_investing("23/01/2026 (Oct)\t01:59\t0.2%\t0.1%\n0.2%", "pct")
    assert rows[0]["ref_month"] == "2025-10-01"


def test_label_year_rollback():
    # Jan 发布、Dec 标签 → 上一年 Dec
    rows = ci.parse_investing("13/01/2022 (Dec)\t00:30\t0.5%\t0.4%\n0.6%", "pct")
    assert rows[0]["ref_month"] == "2021-12-01"


def test_k_unit_parsing():
    txt = ("05/08/2022 (Jul)\t22:30\t528.00K\t250.00K\n398.00K\n"
           "09/01/2021 (Dec)\t00:30\t-140.00K\t71.00K\n336.00K\n"
           "06/08/2021 (Jul)\t22:30\t943.00K\t870.00K\n1,053.00K")
    rows = ci.parse_investing(txt, "k")
    assert rows[0]["actual"] == 528.0 and rows[0]["forecast"] == 250.0
    assert rows[1]["actual"] == -140.0
    assert rows[2]["actual"] == 943.0  # 逗号在 previous 行，不影响


def test_missing_value_is_none():
    # 未来发布：actual/forecast 都空
    rows = ci.parse_investing("02/07/2026 (Jun)\t22:30\n172.00K", "k")
    assert rows[0]["actual"] is None and rows[0]["forecast"] is None


def test_header_line_skipped():
    rows = ci.parse_investing("Release date\tTime\tActual\tForecast\tPrevious\n"
                              "10/06/2026 (May)\t22:30\t0.5%\t0.5%\n0.6%", "pct")
    assert len(rows) == 1 and rows[0]["actual"] == 0.5
