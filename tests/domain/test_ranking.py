from __future__ import annotations

import pytest

from outbound.domain.entities import Contact
from outbound.domain.enums import ContactSource, ContactStatus
from outbound.domain.ranking import (
    normalise_title,
    rank_contacts,
    seniority_of,
    wanted_index,
)

WANTED = ["VP of Sales", "CTO", "Chief Architect", "Director of Product"]


def contact(
    name: str, title: str | None, rank: int = 9, source: ContactSource = ContactSource.SITE
) -> Contact:
    return Contact(
        id=name,
        workspace_id="w",
        company_id="c",
        rank=rank,
        source=source,
        status=ContactStatus.CANDIDATE,
        full_name=name,
        title=title,
    )


def order(contacts: list[Contact], wanted: list[str] = WANTED) -> list[str]:
    return [r.contact.id for r in rank_contacts(contacts, wanted)]


def test_abbreviations_are_spelled_out_before_comparing() -> None:
    assert normalise_title("CTO & Co-Founder") == "chief technology officer & co founder"
    assert normalise_title("SVP, Sales") == "senior vice president sales"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Chief Technology Officer", 1),
        ("CTO", 1),
        ("VP of Sales", 0),
        ("Vice President, Sales EMEA", 0),
        ("Director of Product Management", 3),
        ("Head of Marketing", 4),
        (None, 4),
    ],
)
def test_a_wanted_title_matches_when_all_its_words_are_present(
    title: str | None, expected: int
) -> None:
    assert wanted_index(title, WANTED) == expected


@pytest.mark.parametrize(
    ("title", "label"),
    [
        ("CEO", "c_level"),
        ("Co-Founder", "c_level"),
        ("Founder & Managing Director", "c_level"),
        ("VP Engineering", "vp"),
        ("Head of Data", "director"),
        ("Engineering Manager", "manager"),
        ("Analyst", "other"),
        (None, "other"),
    ],
)
def test_seniority_is_labelled(title: str | None, label: str) -> None:
    assert seniority_of(title) == label


def test_a_wanted_title_beats_a_more_senior_unwanted_one() -> None:
    people = [contact("ceo", "CEO"), contact("cto", "Chief Technology Officer")]
    assert order(people) == ["cto", "ceo"]


def test_the_order_of_the_wanted_titles_matters() -> None:
    people = [contact("cto", "CTO"), contact("vp", "VP of Sales")]
    assert order(people) == ["vp", "cto"]


def test_seniority_breaks_a_tie_among_unwanted_titles() -> None:
    people = [contact("mgr", "Office Manager"), contact("dir", "Director of Finance")]
    assert order(people) == ["dir", "mgr"]


def test_an_operator_given_person_is_always_first() -> None:
    people = [
        contact("cto", "CTO"),
        contact("pa", "Assistant", source=ContactSource.OPERATOR),
    ]
    assert order(people) == ["pa", "cto"]


def test_equal_candidates_keep_their_existing_order() -> None:
    people = [contact("b", "Analyst", rank=2), contact("a", "Analyst", rank=1)]
    assert order(people) == ["a", "b"]


def test_ranks_are_consecutive_and_carry_the_seniority_label() -> None:
    ranked = rank_contacts([contact("x", "CEO"), contact("y", "Analyst")], WANTED)
    assert [(r.rank, r.seniority) for r in ranked] == [(1, "c_level"), (2, "other")]


def test_no_wanted_titles_falls_back_to_seniority() -> None:
    people = [contact("a", "Analyst"), contact("ceo", "CEO")]
    assert order(people, []) == ["ceo", "a"]


def test_a_person_the_operator_chose_outranks_a_better_title() -> None:
    # Rebase: the operator gave the CEO's address and consent; the campaign wants a CTO.
    ceo = contact("sebastian", "CEO and Co-Founder", rank=1)
    cto = contact("mihai", "CTO and Co-Founder", rank=2)
    assert order([ceo, cto]) == ["mihai", "sebastian"]
    ranked = rank_contacts([ceo, cto], WANTED, chosen_ids={"sebastian"})
    assert [r.contact.id for r in ranked] == ["sebastian", "mihai"]
    assert [r.rank for r in ranked] == [1, 2]


def test_chosen_people_keep_the_order_the_operator_left_them_in() -> None:
    first = contact("first", "Engineer", rank=1, source=ContactSource.OPERATOR)
    second = contact("second", "CTO", rank=2)
    ranked = rank_contacts([second, first], WANTED, chosen_ids={"second"})
    assert [r.contact.id for r in ranked] == ["first", "second"]
