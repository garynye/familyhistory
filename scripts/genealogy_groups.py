"""Metadata and navigation rules for preserved Legacy Family Tree exports."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GenealogyLink:
    slug: str
    label: str
    title: str


@dataclass(frozen=True)
class GenealogyGroup:
    host: str
    hub_slug: str
    hub_title: str
    summary: str
    people: int
    surnames: int
    reports: tuple[GenealogyLink, ...]
    name_pages: tuple[GenealogyLink, ...]
    surname_page: GenealogyLink
    source_pages: tuple[GenealogyLink, ...] = ()
    top_level_report_slugs: tuple[str, ...] = ()
    download_url: str = ""
    download_label: str = ""

    @property
    def child_slugs(self) -> set[str]:
        links = (*self.reports, *self.name_pages, self.surname_page, *self.source_pages)
        return {link.slug for link in links}

    @property
    def page_titles(self) -> dict[str, str]:
        links = (*self.reports, *self.name_pages, self.surname_page, *self.source_pages)
        return {
            self.hub_slug: self.hub_title,
            **{link.slug: link.title for link in links},
        }


def make_name_pages(prefix: str, labels: tuple[str, ...], title_prefix: str) -> tuple[GenealogyLink, ...]:
    links = []
    for index, label in enumerate(labels):
        suffix = "" if index == 0 else str(index)
        slug = f"{prefix}-names{suffix}"
        links.append(
            GenealogyLink(
                slug=slug,
                label=label,
                title=f"{title_prefix} Name Index — {label}",
            )
        )
    return tuple(links)


ANNE_NAME_LABELS = (
    "No surname",
    "Symbols",
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "M",
    "N",
    "O",
    "P",
    "Q",
    "R",
    "S",
    "T",
    "U",
    "V",
    "W",
    "Y",
)

NYE_NAME_LABELS = (
    "No surname",
    "Symbols",
    "A",
    "B",
    "C",
    "D",
    "E",
    "G",
    "H",
    "J",
    "K",
    "L",
    "M",
    "N",
    "O",
    "P",
    "R",
    "S",
    "T",
    "U",
)


def anne_group(host: str) -> GenealogyGroup:
    prefix = "annehathaway"
    report = GenealogyLink(
        slug=f"{prefix}-a1",
        label="Family report",
        title="Anne Fisher Family Report",
    )
    return GenealogyGroup(
        host=host,
        hub_slug=f"{prefix}-index",
        hub_title="Anne Fisher Genealogy Index",
        summary="Browse the complete alphabetical name and surname indexes preserved from Anne Fisher’s Legacy Family Tree export.",
        people=1436,
        surnames=353,
        reports=(report,),
        name_pages=make_name_pages(prefix, ANNE_NAME_LABELS, "Anne Fisher"),
        surname_page=GenealogyLink(
            slug=f"{prefix}-surnames",
            label="Browse all surnames",
            title="Anne Fisher Surname Index",
        ),
        top_level_report_slugs=(report.slug,),
    )


def nye_group() -> GenealogyGroup:
    prefix = "files"
    reports = tuple(
        GenealogyLink(
            slug=f"{prefix}-a{generation}",
            label=f"Generation {generation}",
            title=f"Nye Family Report — Generation {generation}",
        )
        for generation in range(1, 11)
    )
    return GenealogyGroup(
        host="nojd.homestead.com",
        hub_slug=f"{prefix}-index",
        hub_title="Ellen Augusta Nye Genealogy Index",
        summary="Browse ten generations of the Nye family report, its alphabetical indexes, bibliography, and original GEDCOM data.",
        people=423,
        surnames=93,
        reports=reports,
        name_pages=make_name_pages(prefix, NYE_NAME_LABELS, "Ellen Augusta Nye"),
        surname_page=GenealogyLink(
            slug=f"{prefix}-surnames",
            label="Browse all surnames",
            title="Ellen Augusta Nye Surname Index",
        ),
        source_pages=(
            GenealogyLink(
                slug=f"{prefix}-sources",
                label="Sources and bibliography",
                title="Ellen Augusta Nye Sources",
            ),
        ),
        download_url="/media/nojd.homestead.com/files/annegedcom.ged",
        download_label="Download the original GEDCOM",
    )


GENEALOGY_GROUPS = (
    nye_group(),
    anne_group("karlaugust.homestead.com"),
    anne_group("mortensen.homestead.com"),
)

GROUPS_BY_HUB = {
    (group.host, group.hub_slug): group
    for group in GENEALOGY_GROUPS
}
GROUPS_BY_PAGE = {
    (group.host, slug): group
    for group in GENEALOGY_GROUPS
    for slug in {group.hub_slug, *group.child_slugs}
}


def group_for_hub(host: str, slug: str) -> GenealogyGroup | None:
    return GROUPS_BY_HUB.get((host, slug))


def title_for_page(host: str, slug: str, default: str) -> str:
    group = GROUPS_BY_PAGE.get((host, slug))
    return group.page_titles.get(slug, default) if group else default


def is_collection_visible(host: str, slug: str) -> bool:
    group = GROUPS_BY_PAGE.get((host, slug))
    if not group or slug == group.hub_slug:
        return True
    return slug in group.top_level_report_slugs
