"""Chift's numbered pages, whatever the provider paginates with underneath."""

from __future__ import annotations

from conftest import assert_schema, company_body


def test_pages_are_disjoint_and_agree_on_the_total(chift, company):
    total = chift.get("/contacts", page=1, size=1).json()["total"]
    for _ in range(max(0, 5 - total)):  # three pages of two need five contacts
        assert_schema(chift.post("/contacts", company_body()), "ContactItemOut")

    pages = [
        assert_schema(chift.get("/contacts", page=n, size=2), "ChiftPage_ContactItemOut_")
        for n in (1, 2, 3)
    ]
    totals = {p["total"] for p in pages}
    assert len(totals) == 1, f"total changed between pages: {totals}"
    total = totals.pop()
    ids = [item["id"] for p in pages for item in p["items"]]
    assert len(ids) == len(set(ids)), "the same record appears on two pages"
    for n, p in enumerate(pages, start=1):
        assert p["page"] == n
        assert len(p["items"]) == min(2, max(0, total - (n - 1) * 2)), f"page {n}"


def test_a_page_past_the_end_is_empty(chift, company):
    total = chift.get("/contacts", page=1, size=100).json()["total"]
    beyond = total // 100 + 2
    page = assert_schema(chift.get("/contacts", page=beyond, size=100), "ChiftPage_ContactItemOut_")
    assert page["items"] == [] and page["total"] == total
