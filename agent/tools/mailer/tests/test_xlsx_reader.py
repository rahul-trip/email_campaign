from __future__ import annotations

from pathlib import Path

import openpyxl

from agent.tools.mailer.ingestion.xlsx_reader import XlsxSchemaError, read_campaign_rows


def _write_workbook(path: Path, header: list[str], rows: list[tuple]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_reads_only_required_columns_and_skips_incomplete_rows(tmp_path: Path) -> None:
    path = tmp_path / "matrix.xlsx"
    header = [
        "Organization URL",
        "Specific Person to Contact",
        "POC Details & Eccentricities",
        "Direct Business Email",
        "Tailored Pitch Email",
        "Follow-up Text",
        "Points of Commonality",
    ]
    rows = [
        ("Acme\nhttps://acme.example", "Jane\n(CEO)", "eccentric", "jane@acme.example", "Hi Jane, ...", "follow up", "common"),
        ("NoEmail Co\nhttps://noemail.example", "Bob", "quirk", "", "Hi Bob, ...", "follow up", "common"),
        ("NoBody Co\nhttps://nobody.example", "Sam", "quirk", "sam@nobody.example", "", "follow up", "common"),
    ]
    _write_workbook(path, header, rows)

    result = read_campaign_rows(str(path))

    assert len(result) == 1
    assert result[0].to_addr == "jane@acme.example"
    assert result[0].subject == "Acme https://acme.example"
    assert result[0].body == "Hi Jane, ..."


def test_missing_required_column_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.xlsx"
    _write_workbook(path, ["Organization URL", "Direct Business Email"], [("Acme", "a@acme.example")])

    try:
        read_campaign_rows(str(path))
        assert False, "expected XlsxSchemaError"
    except XlsxSchemaError:
        pass
