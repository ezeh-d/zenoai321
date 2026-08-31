"""Table intelligence (#23): extract tables to structured data, convert, save."""

from __future__ import annotations

import json

import pytest

from reyes_agent.content import tables as tbl


def test_extract_from_csv(tmp_path):
    f = tmp_path / "d.csv"
    f.write_text("name,score\nAda,9\nBoss,10\n")
    r = tbl.extract_tables(f)
    assert r["ok"] and r["count"] == 1
    t = r["tables"][0]
    assert t["headers"] == ["name", "score"] and t["row_count"] == 2


def test_extract_from_xlsx_with_sheet_provenance(tmp_path):
    from openpyxl import Workbook
    f = tmp_path / "book.xlsx"
    wb = Workbook()
    ws = wb.active; ws.title = "Marks"
    ws.append(["student", "grade"]); ws.append(["Ada", "A"]); ws.append(["Boss", "B"])
    wb.save(f)
    r = tbl.extract_tables(f)
    assert r["ok"] and r["tables"][0]["location"] == "Marks"
    assert r["tables"][0]["headers"] == ["student", "grade"]
    assert r["tables"][0]["row_count"] == 2


def test_extract_from_unsupported_is_honest(tmp_path):
    f = tmp_path / "n.txt"; f.write_text("just prose, no table")
    r = tbl.extract_tables(f)
    assert r["ok"] is False and "no table extractor" in r["error"]


def test_missing_file_is_honest():
    r = tbl.extract_tables("/no/such/file.xlsx")
    assert r["ok"] is False and "is not a file" in r["error"]


# --- conversion -------------------------------------------------------------
_TABLE = {"headers": ["a", "b"], "rows": [["1", "2"], ["3", "4"]]}


def test_to_csv():
    out = tbl.to_csv(_TABLE)
    assert "a,b" in out and "1,2" in out


def test_to_json_makes_records():
    out = json.loads(tbl.to_json(_TABLE))
    assert out == [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]


def test_to_markdown():
    out = tbl.to_markdown(_TABLE)
    assert "| a | b |" in out and "| 1 | 2 |" in out and "---" in out


# --- save (verified) --------------------------------------------------------
def test_save_table_to_csv_is_verified(tmp_path):
    out = tbl.save_table(_TABLE, tmp_path / "out.csv")
    assert out["ok"] and out["verified"]["exists"]
    assert (tmp_path / "out.csv").read_text().count("\n") >= 2


def test_save_table_to_xlsx_reopens(tmp_path):
    dest = tmp_path / "out.xlsx"
    out = tbl.save_table(_TABLE, dest)
    assert out["ok"]
    # round-trip: extract it back
    back = tbl.extract_tables(dest)
    assert back["ok"] and back["tables"][0]["headers"] == ["a", "b"]


def test_save_to_unsupported_ext_is_honest(tmp_path):
    out = tbl.save_table(_TABLE, tmp_path / "out.weird")
    assert out["ok"] is False and "unsupported" in out["error"]


# --- tool -------------------------------------------------------------------
def test_content_tables_tool_extract_and_save(tmp_path):
    import reyes_agent.tools.system  # noqa: F401
    from reyes_agent.tools import TOOLS
    src = tmp_path / "in.csv"; src.write_text("x,y\n1,2\n3,4\n")
    dest = tmp_path / "out.xlsx"
    out = json.loads(TOOLS["content_tables"].func(
        target=str(src), index=0, save_as=str(dest)))
    assert out["ok"] and dest.exists()


def test_content_tables_tool_is_routable():
    from reyes_agent.routing.capability import CAPABILITIES
    assert "content_tables" in CAPABILITIES["files"]
