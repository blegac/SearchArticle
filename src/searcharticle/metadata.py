"""
Article metadata resolution: PMID (PubMed), DOI (CrossRef),
downloadable-article construction and title search.
"""

import re

from .network import make_request, request_with_retry
from .utils import format_filename, sanitize_filename

#: Generic email sent to APIs (CrossRef, Unpaywall) as a courtesy.
#: No personal data is stored or requested from the user.
_EMAIL_API = "anonymous@example.com"


def resolve_pmid(pmid: str) -> dict | None:
    """
    Resolve a PMID via the PubMed API (esummary) to get the DOI,
    title, first author and year.

    Args:
        pmid: PubMed identifier (digits only).

    Returns:
        Article dict ``{title, full_title, doi, pmid, author, year}``
        or ``None`` on failure.
    """

    def req():
        return make_request(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
            f"?db=pubmed&id={pmid}&retmode=json",
            timeout=15,
        )

    r, _err = request_with_retry(req)
    if r is None:
        return None
    try:
        result = r.json().get("result", {}).get(str(pmid), {})
        if not result:
            return None
        title = result.get("title", f"PMID_{pmid}")
        short_title = re.sub(r'[<>:"/\\|?*{}]', "", title)[:80]
        authors = result.get("authors", [])
        author = authors[0].get("name", "").split()[0] if authors else ""
        am = re.search(r"\d{4}", result.get("pubdate", ""))
        year = am.group(0) if am else ""
        doi = next(
            (x["value"] for x in result.get("articleids", []) if x.get("idtype") == "doi"),
            None,
        )
        name = format_filename(author, year, short_title[:50])
        return {
            "title": name,
            "full_title": title,
            "doi": doi,
            "pmid": pmid,
            "author": author,
            "year": year,
        }
    except Exception:
        return None


def resolve_doi_crossref(doi: str) -> dict:
    """
    Query the CrossRef API to fetch the metadata of a given DOI.

    Args:
        doi: DOI identifier (e.g. ``10.7554/eLife.102424.3``).

    Returns:
        Dict ``{author, year, full_title}``. On failure, returns
        a dict with empty values (the DOI as fallback title).
    """
    try:

        def req():
            return make_request(
                f"https://api.crossref.org/works/{doi}",
                timeout=15,
                headers={
                    "User-Agent": (
                        "SearchArticle/1.0 "
                        f"(mailto:{_EMAIL_API})"
                    )
                },
            )

        r, _err = request_with_retry(req)
        if not r or r.status_code != 200:
            return {"author": "", "year": "", "full_title": doi}

        msg = r.json().get("message", {})

        # First author (family name)
        raw_authors = msg.get("author", [])
        author = raw_authors[0].get("family", "") if raw_authors else ""

        # Publication year
        pub = msg.get("published", {}) or msg.get("published-print", {}) or {}
        parts = pub.get("date-parts", [[]])
        year = str(parts[0][0]) if parts and parts[0] else ""

        # Full title
        titres = msg.get("title", [])
        full_title = titres[0] if titres else doi

        return {"author": author, "year": year, "full_title": full_title}

    except Exception:
        return {"author": "", "year": "", "full_title": doi}


def _is_declared_pdf_url(url: str, content_type: str) -> bool:
    """
    Decide whether a CrossRef link likely points to a PDF.

    Some publishers declare the right content-type (``application/pdf``),
    but others use ``unspecified`` (e.g. Science): we also accept URLs
    containing ``.pdf`` or ``/pdf/``.
    """
    ct = (content_type or "").lower()
    u = (url or "").lower()
    return "pdf" in ct or ".pdf" in u or "/pdf/" in u


def pdf_urls_crossref(doi: str) -> list[str]:
    """
    Return the direct PDF URLs declared in CrossRef metadata.

    Many publishers (eLife, PLOS, MDPI, Science…) declare their PDF in
    CrossRef: this is the most reliable way to get the published version,
    without going through doi.org or scraping the publisher page (often
    protected against bots or rendered in JavaScript).

    Args:
        doi: DOI identifier.

    Returns:
        List of PDF URLs (often a single one), empty if none declared.
    """
    try:

        def req():
            return make_request(
                f"https://api.crossref.org/works/{doi}",
                timeout=15,
                headers={"User-Agent": f"SearchArticle/1.0 (mailto:{_EMAIL_API})"},
            )

        r, _err = request_with_retry(req)
        if r is None or r.status_code != 200:
            return []
        urls: list[str] = []
        for link in r.json().get("message", {}).get("link", []):
            u = (link.get("URL") or "").strip()
            if u and _is_declared_pdf_url(u, link.get("content-type") or ""):
                if u not in urls:
                    urls.append(u)
        return urls
    except Exception:
        return []


def publisher_url_crossref(doi: str) -> str | None:
    """
    Return the publisher page URL of a DOI via the CrossRef API,
    without going through doi.org (useful when doi.org blocks requests).

    Args:
        doi: DOI identifier.

    Returns:
        The publisher page URL, or ``None`` if not found.
    """
    try:

        def req():
            return make_request(
                f"https://api.crossref.org/works/{doi}",
                timeout=15,
                headers={"User-Agent": f"SearchArticle/1.0 (mailto:{_EMAIL_API})"},
            )

        r, _err = request_with_retry(req)
        if r is None or r.status_code != 200:
            return None
        msg = r.json().get("message", {})
        resource = msg.get("resource", {}) or {}
        url = (resource.get("primary", {}) or {}).get("URL")
        if url:
            return url
        for link in msg.get("link", []):
            if link.get("URL"):
                return link["URL"]
        return msg.get("URL")
    except Exception:
        return None


def article_from_doi(doi: str) -> dict:
    """
    Build a downloadable article dict from a DOI alone.

    Metadata (author, year, title) are fetched via CrossRef;
    on failure, the filename is based on the DOI.

    Args:
        doi: DOI identifier.

    Returns:
        Article dict ``{title, full_title, doi, pmid, author, year}``.
    """
    doi = doi.strip()
    meta = resolve_doi_crossref(doi)
    name = format_filename(
        meta["author"], meta["year"], fallback=sanitize_filename(doi.replace("/", "_"))
    )
    return {
        "title": name,
        "full_title": meta["full_title"],
        "doi": doi,
        "pmid": None,
        "author": meta["author"],
        "year": meta["year"],
    }


def find_doi_by_title(
    title_query: str, max_results: int = 5, author: str = ""
) -> list[dict]:
    """
    Search articles by title via CrossRef, with PubMed as fallback.

    Args:
        title_query: Title or title keywords.
        max_results: Maximum number of results to return.
        author: An author's family name to refine the search
            (CrossRef ``query.author`` parameter).

    Returns:
        List of ``{doi, title, authors, year, journal, score,
        source}`` dicts sorted by decreasing relevance score. PubMed
        results additionally include the ``pmid`` key.
    """
    results: list[dict] = []

    # ── 1. CrossRef ────────────────────────────────────────────
    try:
        params = {
            "query.title": title_query,
            "rows": max_results,
            "select": "DOI,title,author,published,container-title,score",
            "mailto": _EMAIL_API,
        }
        if author:
            params["query.author"] = author

        def req_cr():
            return make_request(
                "https://api.crossref.org/works",
                params=params,
                timeout=15,
                headers={"User-Agent": f"SearchArticle/1.0 (mailto:{_EMAIL_API})"},
            )

        r, _err = request_with_retry(req_cr)
        if r and r.status_code == 200:
            items = r.json().get("message", {}).get("items", [])
            for item in items:
                doi = item.get("DOI", "")
                titres = item.get("title", [])
                title = titres[0] if titres else "(no title)"
                raw_authors = item.get("author", [])
                authors = ", ".join(
                    f"{a.get('family', '')} {a.get('given', '')[:1]}."
                    for a in raw_authors[:3]
                ) + ("…" if len(raw_authors) > 3 else "")
                pub = item.get("published", {})
                parts = pub.get("date-parts", [[]])
                year = str(parts[0][0]) if parts and parts[0] else "?"
                journal_list = item.get("container-title", [])
                journal = journal_list[0] if journal_list else ""
                score = round(item.get("score", 0), 1)
                if doi:
                    results.append(
                        {
                            "doi": doi,
                            "title": title,
                            "authors": authors,
                            "year": year,
                            "journal": journal,
                            "score": score,
                            "source": "CrossRef",
                        }
                    )
    except Exception:
        pass

    # ── 2. PubMed fallback (if CrossRef is empty) ──────────────
    if not results:
        try:
            # Title search
            def req_search():
                return make_request(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                    params={
                        "db": "pubmed",
                        "term": f"{title_query}[Title]",
                        "retmax": max_results,
                        "retmode": "json",
                    },
                    timeout=15,
                )

            rs, _ = request_with_retry(req_search)
            if rs and rs.status_code == 200:
                ids = rs.json().get("esearchresult", {}).get("idlist", [])
                if ids:

                    def req_summary():
                        return make_request(
                            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                            params={
                                "db": "pubmed",
                                "id": ",".join(ids),
                                "retmode": "json",
                            },
                            timeout=15,
                        )

                    rsum, _ = request_with_retry(req_summary)
                    if rsum and rsum.status_code == 200:
                        result_map = rsum.json().get("result", {})
                        for pmid in ids:
                            item = result_map.get(pmid, {})
                            title = item.get("title", "")
                            raw_authors = item.get("authors", [])
                            authors = ", ".join(
                                a.get("name", "") for a in raw_authors[:3]
                            ) + ("…" if len(raw_authors) > 3 else "")
                            am = re.search(r"\d{4}", item.get("pubdate", ""))
                            year = am.group(0) if am else "?"
                            journal = item.get("source", "")
                            doi = next(
                                (
                                    x["value"]
                                    for x in item.get("articleids", [])
                                    if x.get("idtype") == "doi"
                                ),
                                None,
                            )
                            results.append(
                                {
                                    "doi": doi,
                                    "title": title,
                                    "authors": authors,
                                    "year": year,
                                    "journal": journal,
                                    "score": 0,
                                    "pmid": pmid,
                                    "source": "PubMed",
                                }
                            )
        except Exception:
            pass

    return results
