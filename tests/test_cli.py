"""The commands a person actually types, run against a throwaway database."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from outbound.cli.main import app

runner = CliRunner()
WORKBOOK = Path(__file__).parents[1] / "Quantra_Energy_Outbound_Campaign_Matrix.xlsx"


@pytest.fixture
def url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'cli.db'}"


def run(*args: str, url: str) -> tuple[int, str]:
    result = runner.invoke(app, [*args, "--database-url", url])
    return result.exit_code, result.output


def test_help_lists_the_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("db", "seed", "import-legacy-xlsx"):
        assert command in result.output


def test_db_upgrade_creates_the_schema_and_current_reports_it(url: str) -> None:
    code, out = run("db", "current", url=url)
    assert code == 0 and "not created yet" in out
    code, out = run("db", "upgrade", url=url)
    assert code == 0 and "revision 0002" in out
    code, out = run("db", "current", url=url)
    assert code == 0 and "0002" in out


def test_db_downgrade_steps_back_to_nothing(url: str) -> None:
    run("db", "upgrade", url=url)
    code, _ = run("db", "downgrade", "base", url=url)
    assert code == 0
    assert "not created yet" in run("db", "current", url=url)[1]


def test_seed_is_safe_to_repeat(url: str) -> None:
    run("db", "upgrade", url=url)
    code, first = run("seed", url=url)
    assert code == 0 and "created" in first and "11 country policies added" in first
    code, second = run("seed", url=url)
    assert code == 0 and "already there" in second and "0 country policies added" in second


@pytest.mark.skipif(not WORKBOOK.exists(), reason="the legacy workbook is not in this checkout")
def test_importing_the_legacy_workbook_twice_changes_nothing(url: str) -> None:
    run("db", "upgrade", url=url)
    run("seed", url=url)
    code, first = run("import-legacy-xlsx", str(WORKBOOK), url=url)
    assert code == 0 and "10 imported, 0 already there, 0 rejected" in first
    code, second = run("import-legacy-xlsx", str(WORKBOOK), url=url)
    assert code == 0 and "0 imported, 10 already there" in second


def test_importing_before_seeding_explains_what_to_do(url: str) -> None:
    run("db", "upgrade", url=url)
    code, out = run("import-legacy-xlsx", str(WORKBOOK), url=url)
    assert code == 1 and "outbound seed" in out


def test_importing_a_workbook_that_is_not_the_campaign_matrix_fails_cleanly(
    url: str, tmp_path: Path
) -> None:
    import openpyxl

    book = openpyxl.Workbook()
    book.worksheets[0].append(["Company", "Person"])
    path = tmp_path / "other.xlsx"
    book.save(path)
    run("db", "upgrade", url=url)
    run("seed", url=url)
    code, out = run("import-legacy-xlsx", str(path), url=url)
    assert code == 1 and "Organization URL" in out


def test_a_missing_file_is_refused_by_the_argument_check(url: str) -> None:
    code, _ = run("import-legacy-xlsx", "/no/such/file.xlsx", url=url)
    assert code != 0


# ------------------------------------------------------------------ targets


def seeded(url: str) -> None:
    run("db", "upgrade", url=url)
    run("seed", url=url)


def test_targets_add_creates_a_company_and_repeating_it_merges(url: str) -> None:
    seeded(url)
    code, out = run("targets", "add", "--website", "acme.com", "--country", "UK", url=url)
    assert code == 0 and "accepted acme.com" in out and "1 accepted" in out
    code, out = run("targets", "add", "--website", "https://www.acme.com", url=url)
    assert code == 0 and "merged acme.com" in out


def test_targets_add_needs_something_to_go_on(url: str) -> None:
    seeded(url)
    code, out = run("targets", "add", url=url)
    assert code == 1 and "at least one" in out


def test_targets_import_validates_without_saving(url: str, tmp_path: Path) -> None:
    seeded(url)
    sheet = tmp_path / "targets.csv"
    sheet.write_text("Company,Website\nAcme,acme.com\nBeta,beta.io\nBeta again,beta.io\n")
    code, out = run("targets", "import", str(sheet), "--validate-only", url=url)
    assert code == 0 and "read 3: 2 accepted, 1 merged" in out and "nothing was saved" in out
    code, out = run("targets", "import", str(sheet), url=url)
    assert code == 0 and "read 3: 2 accepted, 1 merged" in out
    code, out = run("targets", "import", str(sheet), url=url)
    assert code == 0 and "read 3: 3 merged" in out


def test_a_name_with_no_search_key_waits_and_can_be_confirmed(url: str) -> None:
    seeded(url)
    code, out = run("targets", "add", "--company", "Acme Energy", url=url)
    assert code == 0 and "needs confirmation" in out and "targets confirm" in out
    code, out = run("targets", "pending", url=url)
    row_id = out.split()[0]
    assert code == 0 and "Acme Energy" in out
    code, out = run("targets", "confirm", row_id, "acme-energy.com", url=url)
    assert code == 0 and out.startswith("accepted acme-energy.com")
    assert "nothing is waiting" in run("targets", "pending", url=url)[1]


def test_confirming_an_unknown_row_is_a_clear_error(url: str) -> None:
    seeded(url)
    code, out = run("targets", "confirm", "nope", "acme.com", url=url)
    assert code == 1 and "nope" in out


def test_targets_commands_need_a_seeded_workspace(url: str) -> None:
    run("db", "upgrade", url=url)
    code, out = run("targets", "add", "--website", "acme.com", url=url)
    assert code == 1 and "outbound seed" in out


# ------------------------------------------------------------------ everyday commands


@pytest.fixture
def isolated(url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A seeded database, run from an empty folder so no developer .env can leak in."""
    seeded(url)
    monkeypatch.chdir(tmp_path)
    return url


def test_run_without_credentials_says_what_is_missing_and_changes_nothing(isolated: str) -> None:
    run("targets", "add", "--website", "acme.com", url=isolated)
    code, out = run("run", url=isolated)
    assert code == 1 and "not configured" in out
    assert "new" in run("status", url=isolated)[1]


def test_status_shows_counts_holds_and_the_review_queue(isolated: str) -> None:
    run("targets", "add", "--website", "acme.com", url=isolated)
    code, out = run("status", url=isolated)
    assert code == 0 and "new" in out and "none waiting for review" in out


def test_review_list_is_empty_on_a_new_database(isolated: str) -> None:
    code, out = run("review", "list", url=isolated)
    assert code == 0 and "nothing is waiting" in out


def test_reviewing_an_unknown_message_is_a_clear_error(isolated: str) -> None:
    code, out = run("review", "approve", "nope", url=isolated)
    assert code == 1 and "no message" in out
    code, out = run("review", "reject", "nope", "--reason", "x", url=isolated)
    assert code == 1 and "no message" in out


def test_the_quality_report_says_nothing_has_been_sent_yet(isolated: str) -> None:
    code, out = run("report", "quality", url=isolated)
    assert code == 0 and "nothing sent yet" in out and "sent 0" in out


def test_the_cost_report_works_with_no_spend(isolated: str) -> None:
    code, out = run("report", "cost", "--days", "7", url=isolated)
    assert code == 0 and "total $0.0000 over 7 day(s)" in out and "calls: none" in out


def test_the_sender_profile_must_be_confirmed_and_can_be(isolated: str) -> None:
    code, out = run("sender-profile", "show", url=isolated)
    assert code == 0 and "NO - emails will not be written" in out
    declined = runner.invoke(
        app, ["sender-profile", "review", "--database-url", isolated], input="n\n"
    )
    assert declined.exit_code == 1 and "Not confirmed" in declined.output
    assert "NO" in run("sender-profile", "show", url=isolated)[1]
    code, out = run("sender-profile", "review", "--yes", url=isolated)
    assert code == 0 and "reviewed" in out
    assert "NO - emails" not in run("sender-profile", "show", url=isolated)[1]


def test_serve_on_a_database_that_was_never_set_up_says_what_to_run(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPERATOR_PASSWORD_HASH", "x")
    monkeypatch.setenv("SESSION_SECRET", "s" * 40)
    code, out = run("serve", url=url)
    assert code == 1
    assert "has not been set up" in out and "outbound db upgrade" in out and "outbound seed" in out
    assert "no such table" not in out


def test_other_commands_say_the_same_instead_of_a_stack_trace(url: str) -> None:
    code, out = run("status", url=url)
    assert code == 1
    assert "outbound db upgrade" in out and "Traceback" not in out


def test_a_set_up_database_without_the_workspace_says_to_seed(url: str) -> None:
    assert run("db", "upgrade", url=url)[0] == 0
    code, out = run("status", url=url)
    assert code == 1 and "outbound seed" in out
