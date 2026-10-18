"""
PDF download sources.

For each article, sources are tried in this priority order:
  1. Publisher (direct PDF declared in CrossRef, otherwise via doi.org —
     needs institutional VPN or proxy for subscriptions)
  2. Unpaywall (all OA versions, not just the "best" one)
  3. PubMed Central (PMCID via the Europe PMC API)
  4. PubMed Central (PMID → PMCID conversion)

Each function returns ``(size_KB, detail)`` on success,
``(None, message)`` on failure, or ``(None, None)`` when the article is
simply absent from that source (move on to the next one silently).
"""

import re
import time
from pathlib import Path
from urllib.parse import urlparse

from .config import SessionState
from .network import make_request, request_with_retry
from .utils import write_manifest, is_pdf, sanitize_filename

#: Minimum size of a downloaded PDF (bytes).
_PDF_MIN_PUBLISHER = 10000

#: HTML patterns indicating an anti-bot verification page (Cloudflare…).
_ANTIBOT_MARKERS = ("just a moment", "cf-chl", "challenge-platform", "captcha")

#: Patterns to find a PDF link in a publisher page.
_PUBLISHER_PDF_PATTERNS = [
    r'href\s*=\s*"([^"]*\.pdf[^"]*)"',
    r"href\s*=\s*'([^']*\.pdf[^']*)'",
    r'data-article-pdf="([^"]*)"',
    r'"pdfUrl":"([^"]*)"',
    r'citation_pdf_url"\s+content="([^"]*)"',
]


def _is_antibot_page(html: str) -> bool:
    """Detect an anti-bot verification page (Cloudflare, captcha…)."""
    t = html.lower()
    return any(k in t for k in _ANTIBOT_MARKERS)


def save_pdf(state: SessionState, data: bytes, title: str) -> int:
    """
    Save PDF bytes to the output folder.

    Args:
        state: Session state (provides the output folder).
        data: Binary content of the PDF.
        title: Desired filename (without extension).

    Returns:
        File size in KB.
    """
    p = state.output_dir() / sanitize_filename(f"{title}.pdf")
    p.write_bytes(data)
    return len(data) // 1024


def _absolute_url(url_pdf: str, page_url: str) -> str:
    """Convert a relative PDF URL to an absolute URL."""
    if url_pdf.startswith("//"):
        return "https:" + url_pdf
    if url_pdf.startswith("/"):
        p = urlparse(page_url)
        return f"{p.scheme}://{p.netloc}{url_pdf}"
    return url_pdf


def _download_pdf(
    url_pdf: str,
    title: str,
    state: SessionState,
    log_cb=None,
    min_size: int = _PDF_MIN_PUBLISHER,
    label: str = "Publisher",
) -> tuple[int | None, str | None]:
    """
    Download a PDF from a direct URL and save it.

    Args:
        url_pdf: Direct URL of the PDF.
        title: Desired filename (without extension).
        state: Session state (output folder).
        log_cb: Optional logging function.
        min_size: Minimum size in bytes to consider the content
            a valid PDF.
        label: Source label for the log.

    Returns:
        ``(size_KB, label)`` on success, ``(None, reason)`` otherwise.
    """
    if log_cb:
        log_cb("    → Downloading PDF...", "muted")

    def req_pdf():
        return make_request(url_pdf, timeout=40)

    pr, err_pdf = request_with_retry(req_pdf)

    if pr is None:
        if log_cb:
            log_cb(f"    ✘ PDF download failed: {err_pdf}", "warning")
        return None, err_pdf

    if pr.status_code != 200:
        if log_cb:
            log_cb(f"    ✘ HTTP status {pr.status_code} for PDF", "warning")
        return None, f"HTTP {pr.status_code}"

    if not is_pdf(pr.content, min_size):
        if log_cb:
            log_cb(
                f"    ✘ Received content is not a valid PDF "
                f"({len(pr.content)} bytes)",
                "warning",
            )
        return None, "Not a valid PDF"

    if log_cb:
        log_cb("    ✔ Valid PDF retrieved", "success")
    return save_pdf(state, pr.content, title), label


def _extract_pdf_links(html: str) -> list[str]:
    """Extract candidate PDF URLs from a page's HTML."""
    links: list[str] = []
    for pat in _PUBLISHER_PDF_PATTERNS:
        for m in re.finditer(pat, html):
            u = m.group(1)
            if u not in links:
                links.append(u)
    return links


def dl_publisher(
    doi: str, title: str, state: SessionState, log_cb=None
) -> tuple[int | None, str | None]:
    """
    Download the PDF via the publisher page.

    The page is reached via doi.org, falling back to the CrossRef URL when
    doi.org is unreachable (frequent anti-bot protection).

    Requires institutional access (VPN or proxy) for subscription
    articles.

    Args:
        doi: Article DOI.
        title: Desired filename (without extension).
        state: Session state (network diagnostics, output folder).
        log_cb: Optional ``log_cb(message, style)`` logging function.
    """
    # Local import to avoid a circular import (metadata imports network).
    from .metadata import pdf_urls_crossref, publisher_url_crossref

    if state.diag["doi"] is False:
        return None, "DOI resolver offline — check your VPN connection"

    if state.diag.get("proxy") is False and log_cb:
        inst_name = state.config.institution_name.strip()
        proxy_label = f"{inst_name} proxy" if inst_name else "Institutional proxy"
        log_cb(
            f"    ⚠  {proxy_label} not detected — subscription articles "
            "may be unreachable (enable the VPN).",
            "warning",
        )

    # ── 0. Direct PDFs declared in CrossRef (most reliable) ──
    # Skips doi.org and publisher-page scraping: for publishers that
    # declare their PDF (eLife, PLOS, MDPI…), this is the published version.
    for pdf_url in pdf_urls_crossref(doi):
        if log_cb:
            log_cb(f"    → Declared PDF (CrossRef): {pdf_url[:60]}...", "muted")
        kb, detail = _download_pdf(pdf_url, title, state, log_cb)
        if kb is not None:
            return kb, detail

    # ── 1. Reach the article page ────────────────────────────
    page_url: str | None = None
    page_html: str | None = None

    if log_cb:
        log_cb(f"    → Resolving DOI via https://doi.org/{doi}", "muted")
    r, err = request_with_retry(
        lambda: make_request(
            f"https://doi.org/{doi}", timeout=20, allow_redirects=True
        )
    )
    if r is not None and r.status_code == 200:
        page_url, page_html = r.url, r.text
        if log_cb:
            log_cb(f"    → Redirected to {page_url[:60]}...", "muted")
    else:
        status = f"HTTP {r.status_code}" if r is not None else (err or "network failure")
        if log_cb:
            log_cb(f"    ✘ doi.org unreachable ({status}) — trying via CrossRef…", "warning")
        landing = publisher_url_crossref(doi)
        if not landing:
            return None, f"DOI resolution failed: {status}"
        if log_cb:
            log_cb(f"    → Publisher page (CrossRef): {landing[:60]}…", "muted")
        r2, err2 = request_with_retry(
            lambda: make_request(landing, timeout=20, allow_redirects=True)
        )
        if r2 is None or r2.status_code != 200:
            status2 = (
                f"HTTP {r2.status_code}" if r2 is not None else (err2 or "network failure")
            )
            if log_cb:
                log_cb(f"    ✘ Publisher page unreachable ({status2})", "warning")
            return None, f"Publisher page unreachable: {status2}"
        page_url, page_html = r2.url, r2.text

    if _is_antibot_page(page_html):
        if log_cb:
            log_cb("    ✘ Anti-bot verification page (publisher)", "warning")
        return None, "Publisher page protected (anti-bot)"

    # ── 2. Look for a PDF link in the page ────────────────────
    for link in _extract_pdf_links(page_html):
        pu = _absolute_url(link, page_url)
        if log_cb:
            log_cb(f"    → PDF found: {pu[:60]}...", "muted")
        kb, detail = _download_pdf(pu, title, state, log_cb)
        if kb is not None:
            return kb, detail

    if log_cb:
        log_cb("    ✘ No PDF link found on the publisher page", "warning")
    return None, "No PDF link on the publisher page"


def _pdf_urls_unpaywall(data: dict) -> list[str]:
    """
    Collect candidate PDF URLs from an Unpaywall response.

    Walk ``best_oa_location`` first, then all ``oa_locations``,
    preferring direct ``url_for_pdf`` entries (plain ``url`` entries
    may point to HTML pages).

    Args:
        data: Decoded JSON response from the Unpaywall API.

    Returns:
        List of unique URLs, deduplicated.
    """
    locs: list[dict] = []
    best = data.get("best_oa_location") or {}
    if best:
        locs.append(best)
    for loc in data.get("oa_locations") or []:
        if loc not in locs:
            locs.append(loc)
    urls: list[str] = []
    for key in ("url_for_pdf", "url"):
        for loc in locs:
            u = (loc.get(key) or "").strip()
            if u and u not in urls:
                urls.append(u)
    return urls


def dl_unpaywall(
    doi: str, title: str, state: SessionState, log_cb=None
) -> tuple[int | None, str | None]:
    """
    Download the open-access version via the Unpaywall API.

    Requires a valid email in the configuration: the Unpaywall API
    rejects (HTTP 422) calls without an email.

    Args:
        doi: Article DOI.
        title: Desired filename (without extension).
        state: Session state (email, diagnostics, output folder).
        log_cb: Optional logging function.
    """
    if state.diag["unpaywall"] is False:
        return None, "Unpaywall offline"

    if not state.email:
        return None, "Email required for Unpaywall — set it in the settings"

    if log_cb:
        log_cb("    → Querying Unpaywall API", "muted")

    def req():
        return make_request(
            f"https://api.unpaywall.org/v2/{doi}?email={state.email}", timeout=15
        )

    r, err = request_with_retry(req)

    if r is None:
        if log_cb:
            log_cb(f"    ✘ Unpaywall failed: {err}", "warning")
        return None, err

    if r.status_code == 422:
        if log_cb:
            log_cb("    ✘ Email rejected by Unpaywall (check that it is valid)", "warning")
        return None, "Email rejected by Unpaywall (HTTP 422)"

    if r.status_code != 200:
        if log_cb:
            log_cb(f"    ✘ HTTP status {r.status_code} from Unpaywall", "warning")
        return None, f"HTTP {r.status_code}"

    try:
        data = r.json()
    except Exception:
        if log_cb:
            log_cb("    ✘ Unreadable Unpaywall response", "warning")
        return None, "Unreadable Unpaywall response"

    urls = _pdf_urls_unpaywall(data)
    if not urls:
        if log_cb:
            log_cb("    ✘ No OA version available", "muted")
        return None, None

    for pu in urls:
        if log_cb:
            log_cb(f"    → OA PDF found: {pu[:60]}...", "muted")
        kb, _detail = _download_pdf(
            pu, title, state, log_cb, min_size=5000, label="Unpaywall"
        )
        if kb is not None:
            return kb, "Unpaywall"

    if log_cb:
        log_cb("    ✘ No downloadable OA PDF", "warning")
    return None, "No downloadable OA PDF"


def _pmcid_from_doi(doi: str) -> str | None:
    """
    Find an article's PMCID from its DOI via the Europe PMC API
    (full-text search on the DOI).

    Args:
        doi: DOI identifier.

    Returns:
        The PMCID (e.g. ``"PMC6516827"``) or ``None`` if not found.
    """

    def req():
        return make_request(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": f'DOI:"{doi}"', "format": "json", "resultType": "core"},
            timeout=20,
        )

    r, _err = request_with_retry(req)
    if r is None or r.status_code != 200:
        return None
    try:
        results = r.json().get("resultList", {}).get("result", [])
        if results:
            return results[0].get("pmcid")
    except Exception:
        pass
    return None


def _dl_pdf_pmc(
    pmcid: str, title: str, state: SessionState, log_cb=None, label: str = "PMC"
) -> tuple[int | None, str | None]:
    """
    Download a PMC article's PDF from its PMCID.

    Args:
        pmcid: PMCID identifier (e.g. ``"PMC6516827"``).
        title: Desired filename (without extension).
        state: Session state (output folder).
        log_cb: Optional logging function.
        label: Source label for the log.

    Returns:
        ``(size_KB, label)`` on success, ``(None, reason)`` otherwise.
    """

    def req_pdf():
        return make_request(
            f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/", timeout=45
        )

    r, err = request_with_retry(req_pdf)

    if r is None:
        if log_cb:
            log_cb(f"    ✘ PDF download failed: {err}", "warning")
        return None, err

    if r.status_code != 200:
        if log_cb:
            log_cb(f"    ✘ HTTP status {r.status_code}", "warning")
        return None, f"HTTP {r.status_code}"

    if not is_pdf(r.content, _PDF_MIN_PUBLISHER):
        if log_cb:
            log_cb("    ✘ Received content is not a valid PDF", "warning")
        return None, "Not a PDF"

    if log_cb:
        log_cb("    ✔ PMC PDF retrieved", "success")
    return save_pdf(state, r.content, title), label


def dl_pmc_doi(
    doi: str, title: str, state: SessionState, log_cb=None
) -> tuple[int | None, str | None]:
    """
    Download the PDF from PubMed Central (PMCID found via
    the Europe PMC API from the DOI).

    Args:
        doi: Article DOI.
        title: Desired filename (without extension).
        state: Session state (NCBI diagnostics, output folder).
        log_cb: Optional logging function.
    """
    if state.diag["ncbi"] is False:
        return None, "NCBI offline"

    if log_cb:
        log_cb("    → Looking up PMCID (Europe PMC) with DOI", "muted")

    pmcid = _pmcid_from_doi(doi)
    if not pmcid:
        if log_cb:
            log_cb("    ✘ Article not in PMC", "muted")
        return None, None

    if log_cb:
        log_cb(f"    → Article found: {pmcid}", "muted")
    return _dl_pdf_pmc(pmcid, title, state, log_cb, label="PMC")


def dl_pmc_pmid(
    pmid: str, title: str, state: SessionState, log_cb=None
) -> tuple[int | None, str | None]:
    """
    Download the PDF from PubMed Central via PMID → PMCID conversion.

    Args:
        pmid: PubMed identifier.
        title: Desired filename (without extension).
        state: Session state (NCBI diagnostics, output folder).
        log_cb: Optional logging function.
    """
    if state.diag["ncbi"] is False:
        return None, "NCBI offline"

    if log_cb:
        log_cb("    → Converting PMID → PMCID", "muted")

    def req_conv():
        return make_request(
            f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
            f"?ids={pmid}&format=json",
            timeout=20,
        )

    rc, err = request_with_retry(req_conv)

    if rc is None:
        if log_cb:
            log_cb(f"    ✘ Conversion failed: {err}", "warning")
        return None, f"PMC idconv: {err}"

    recs = rc.json().get("records", [])
    pmcid = recs[0].get("pmcid") if recs else None

    if not pmcid:
        if log_cb:
            log_cb("    ✘ No PMCID found", "muted")
        return None, None

    if log_cb:
        log_cb(f"    → PMCID found: {pmcid}", "muted")
    return _dl_pdf_pmc(pmcid, title, state, log_cb, label="PMC (PMID)")


def _title_similarity(a: str, b: str) -> float:
    """
    Normalized similarity between two titles (0..1), insensitive to
    case, accents and punctuation.
    """
    import difflib
    import unicodedata

    def normalize(s: str) -> str:
        s = unicodedata.normalize("NFKD", s.lower())
        s = "".join(c for c in s if c.isalnum() or c.isspace())
        return re.sub(r"\s+", " ", s).strip()

    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _compatible_journals(j1: str, j2: str) -> bool:
    """
    Check whether two journal names likely denote the same journal
    (normalized comparison, substring in both directions).
    """
    import unicodedata

    def normalize(s: str) -> str:
        s = unicodedata.normalize("NFKD", s.lower())
        s = "".join(c for c in s if c.isalnum() or c.isspace())
        return re.sub(r"\s+", " ", s).strip()

    n1, n2 = normalize(j1), normalize(j2)
    if not n1 or not n2:
        return False
    return n1 in n2 or n2 in n1


def _doi_by_title(article: dict, log_cb=None) -> str | None:
    """
    Try to recover the DOI of an identifier-less article via a
    title search (CrossRef).

    The search is refined with the first author's name when known. The
    best result is only accepted if its title is close enough to the
    searched title (guard against false positives); when identical titles
    appear in several journals (e.g. republication), the BibTeX journal
    breaks the tie when possible.

    Args:
        article: Article dict (uses ``full_title``, ``author`` and
            ``journal`` when available).
        log_cb: Optional logging function.

    Returns:
        The resolved DOI, or ``None``.
    """
    from .metadata import find_doi_by_title

    full_title = (article.get("full_title") or "").strip()
    if len(full_title) < 15:
        return None
    try:
        results = find_doi_by_title(
            full_title,
            max_results=5,
            author=(article.get("author") or "").split()[0],
        )
    except Exception:
        return None

    # Keep only close-title results that have a DOI
    candidates = [
        r
        for r in results
        if r.get("doi") and _title_similarity(full_title, r.get("title", "")) >= 0.6
    ]
    if not candidates:
        if log_cb:
            log_cb("  ✘  No title result close enough", "warning")
        return None

    # Tie-break with the BibTeX journal when several candidates
    bib_journal = article.get("journal") or ""
    if len(candidates) > 1 and bib_journal:
        for c in candidates:
            if _compatible_journals(bib_journal, c.get("journal", "")):
                if log_cb:
                    log_cb(f"  → Matching journal: {c.get('journal')}", "muted")
                return c["doi"]
        if log_cb:
            log_cb(
                "  ⚠  Several possible journals, taking the best score",
                "warning",
            )

    return candidates[0]["doi"]


def download_article(
    article: dict, state: SessionState, log_cb, prog_cb=None
) -> bool:
    """
    Download an article, trying sources in priority order.

    If the PDF already exists in the output folder, the article is not
    re-downloaded, but it is still recorded in ``manifest.json``
    (for Zotero linking).

    Args:
        article: Dict ``{title, full_title, doi, pmid, …}``.
        state: Session state.
        log_cb: ``log_cb(message, style)`` logging function.
        prog_cb: Optional progress callback (unused by the GUI,
            kept for compatibility).

    Returns:
        ``True`` if the download succeeded, ``False`` otherwise.
    """
    doi = article.get("doi")
    pmid = article.get("pmid")
    t = article["title"]

    # Fallback: no identifier (BibTeX without DOI) → title search
    if not doi and not pmid:
        if log_cb:
            log_cb("  🔎 No DOI/PMID — searching by title…", "muted")
        doi = _doi_by_title(article, log_cb)
        if doi:
            article["doi"] = doi
            if log_cb:
                log_cb(f"  ✔  DOI resolved: {doi}", "success")
        else:
            if log_cb:
                log_cb("  ✘  Could not resolve a DOI for this article", "error")
            return False

    path = Path(state.output_folder) / sanitize_filename(f"{t}.pdf")
    if path.exists():
        log_cb(f"⏭  Already downloaded: {t}", "muted")
        # The file already exists (previous batch): still record it
        # in the manifest so the link_zotero companion script can link it.
        write_manifest(state.output_folder, article, t)
        return True

    sources = []
    if doi:
        sources += [
            ("Publisher", lambda: dl_publisher(doi, t, state, log_cb)),
            ("Unpaywall", lambda: dl_unpaywall(doi, t, state, log_cb)),
            ("PMC", lambda: dl_pmc_doi(doi, t, state, log_cb)),
        ]
    if pmid:
        sources.append(("PMC (PMID)", lambda p=pmid: dl_pmc_pmid(p, t, state, log_cb)))

    for source_name, fn in sources:
        try:
            log_cb(f"  › {source_name}…", "muted")
            kb, detail = fn()
            if kb is not None:
                log_cb(f"  ✔  {detail}  ({kb} KB)", "success")
                # Remember DOI → file for Zotero linking
                write_manifest(state.output_folder, article, t)
                return True
            # detail may be an error message or None (= absent from the source)
            if detail:
                log_cb(f"  ✘  {source_name}: {detail}", "warning")
            time.sleep(0.8)
        except Exception as e:
            log_cb(f"  ✘  {source_name}: {str(e)[:80]}", "error")
            time.sleep(0.8)

    log_cb("  ✘  No source worked", "error")
    return False
