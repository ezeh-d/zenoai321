"""Conversion engine (#28): real converters, verified writes, honest limits."""

from __future__ import annotations

import json

import pytest

import reyes_agent.content.convert as cv


def test_csv_to_xlsx_and_back(tmp_path):
    src = tmp_path / "d.csv"; src.write_text("a,b\n1,2\n3,4\n")
    xlsx = tmp_path / "d.xlsx"
    r = cv.convert(src, xlsx)
    assert r["ok"] and xlsx.exists() and r["route"] == "pure-python"
    back = cv.convert(xlsx, tmp_path / "back.csv")
    assert back["ok"] and (tmp_path / "back.csv").read_text().strip().startswith("a,b")


def test_text_to_docx_then_docx_to_txt(tmp_path):
    src = tmp_path / "n.txt"; src.write_text("Hello world\nSecond line")
    docx = tmp_path / "n.docx"
    assert cv.convert(src, docx)["ok"] and docx.exists()
    out = tmp_path / "n2.txt"
    assert cv.convert(docx, out)["ok"]
    assert "Hello world" in out.read_text()


def test_markdown_to_html(tmp_path):
    src = tmp_path / "n.md"; src.write_text("# Title\n\nSome **bold** text.")
    dest = tmp_path / "n.html"
    r = cv.convert(src, dest)
    assert r["ok"]
    html = dest.read_text()
    assert "<h1>Title</h1>" in html and "<strong>bold</strong>" in html


def test_image_to_pdf(tmp_path):
    from PIL import Image
    img = tmp_path / "pic.png"
    Image.new("RGB", (32, 32), (10, 20, 30)).save(img)
    pdf = tmp_path / "pic.pdf"
    r = cv.convert(img, pdf)
    assert r["ok"] and pdf.exists()
    assert pdf.read_bytes().startswith(b"%PDF")


def test_unsupported_pair_is_honest(tmp_path):
    src = tmp_path / "n.json"; src.write_text('{"a":1}')
    r = cv.convert(src, tmp_path / "n.pptx")
    assert r["ok"] is False and "no converter" in r["error"]


def test_same_format_is_refused(tmp_path):
    src = tmp_path / "d.csv"; src.write_text("a\n1\n")
    r = cv.convert(src, tmp_path / "e.csv")
    assert r["ok"] is False and "both" in r["error"]


def test_missing_source_is_honest():
    r = cv.convert("/no/such.docx", "/tmp/out.pdf")
    assert r["ok"] is False and "is not a file" in r["error"]


def test_office_to_pdf_reports_when_libreoffice_absent(tmp_path, monkeypatch):
    # force "soffice not found" so we assert the honest path, not the machine's state
    monkeypatch.setattr(cv, "_soffice", lambda: "")
    src = tmp_path / "n.txt"; src.write_text("x")   # txt not a soffice source
    docx = tmp_path / "d.docx"; cv.convert(src, docx)   # make a real docx first
    r = cv.convert(docx, tmp_path / "d.pdf")
    assert r["ok"] is False and "LibreOffice" in r["error"]


def test_available_conversions_lists_pure_pairs():
    caps = cv.available_conversions()
    assert "csv->xlsx" in caps["pure_python"] and "md->html" in caps["pure_python"]


# --- tool -------------------------------------------------------------------
def test_content_convert_tool(tmp_path):
    import reyes_agent.tools.system  # noqa: F401
    from reyes_agent.tools import TOOLS
    src = tmp_path / "in.csv"; src.write_text("x,y\n1,2\n")
    out = json.loads(TOOLS["content_convert"].func(
        target=str(src), dest=str(tmp_path / "out.xlsx")))
    assert out["ok"] and (tmp_path / "out.xlsx").exists()


def test_content_convert_is_routable():
    from reyes_agent.routing.capability import CAPABILITIES
    assert "content_convert" in CAPABILITIES["files"]
