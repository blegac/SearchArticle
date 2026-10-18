"""
Pure utility functions (stateless, no network access).

Groups filename sanitizing, PDF detection, output-name formatting
and identifier-type detection.
"""

import json
import re
from datetime import datetime
from pathlib import Path

#: Characters forbidden in Windows filenames.
_FORBIDDEN_CHARS = r'[<>:"/\\|?*]'


def sanitize_filename(name: str) -> str:
    """
    Make a string usable as a filename.

    Replace characters forbidden on Windows (``< > : " / \\ | ? *``)
    with ``_``, convert spaces to ``_`` and cap at 150 characters.

    Args:
        name: Raw string (article title, DOI…).

    Returns:
        Sanitized string, usable as a filename.
    """
    name = re.sub(_FORBIDDEN_CHARS, "_", name)
    return re.sub(r"\s+", "_", name)[:150]


def is_pdf(data: bytes, min_size: int = 5000) -> bool:
    """
    Check that downloaded content really looks like a PDF.

    Args:
        data: Received binary content.
        min_size: Minimum size in bytes to consider the PDF valid.

    Returns:
        ``True`` if the content is large enough and starts with ``%PDF``.
    """
    return len(data) > min_size and data[:4] == b"%PDF"


def format_filename(author: str, year: str, fallback: str) -> str:
    """
    Format the filename as ``FirstAuthor_et_al_YEAR``.

    If the author or year is missing, use the provided ``fallback``
    (e.g. truncated title or identifier).

    Args:
        author: First author's family name (may be empty).
        year: Publication year (may be empty).
        fallback: Fallback text when author and year are both missing.

    Returns:
        Sanitized filename (without extension).
    """
    if author and year:
        return sanitize_filename(f"{author}_et_al_{year}")
    elif author:
        return sanitize_filename(f"{author}_et_al")
    elif year:
        return sanitize_filename(f"Unknown_et_al_{year}")
    else:
        return sanitize_filename(fallback)


def detect_type(s: str) -> tuple[str, str]:
    """
    Detect the type of a user-entered identifier.

    Recognized formats: ``doi:10.…``, ``pmid:12345``, bare DOI (``10.…``),
    bare PMID (5 to 8 digits).

    Args:
        s: Entered string (text-file line, input field…).

    Returns:
        Tuple ``(type, value)`` where type is ``"doi"``, ``"pmid"``
        or ``"unknown"``.
    """
    s = s.strip()
    if s.lower().startswith("doi:"):
        return "doi", s[4:].strip()
    if s.lower().startswith("pmid:"):
        return "pmid", s[5:].strip()
    if s.startswith("10."):
        return "doi", s
    if re.fullmatch(r"\d{5,8}", s):
        return "pmid", s
    return "unknown", s


def assign_unique_names(articles: list[dict]) -> int:
    """
    Make filenames unique within a batch of articles.

    PDFs are named ``Author_et_al_YEAR.pdf``: two articles by the same
    first author published the same year produce the same name, and the
    second would wrongly be skipped as "already downloaded". This function
    appends an ``a``/``b``/``c``… suffix (academic convention: 2021a, 2021b)
    to colliding articles.

    Assignment order is stable (sorted by DOI then full title),
    independent of article arrival order: re-running the same batch
    produces the same names, which preserves resuming ("already
    downloaded").

    Args:
        articles: List of article dicts; the ``"title"`` key is modified
            in place for colliding articles.

    Returns:
        Number of renamed articles.
    """
    groups: dict[str, list[dict]] = {}
    for article in articles:
        groups.setdefault(article["title"], []).append(article)

    renamed = 0
    for base, lst in groups.items():
        if len(lst) < 2:
            continue
        sorted_group = sorted(
            lst, key=lambda a: (a.get("doi") or "", a.get("full_title") or "")
        )
        for i, article in enumerate(sorted_group):
            suffix = chr(ord("a") + i) if i < 26 else f"_{i + 1}"
            article["title"] = f"{base}{suffix}"
            renamed += 1
    return renamed


def write_manifest(
    output_folder: str | Path, article: dict, title_base: str
) -> None:
    """
    Record a successful download in ``manifest.json``.

    The manifest (DOI → file) is then used to automatically link
    PDFs to Zotero entries with the separate ``link_zotero`` companion
    script (provided separately).

    Args:
        output_folder: Folder where PDFs are saved.
        article: Article dict (keys ``doi``, ``pmid``, ``full_title``).
        title_base: Filename base (no extension, a/b/c suffixes
            already applied where relevant).
    """
    doi = (article.get("doi") or "").strip().lower()
    if not doi:
        return
    path = Path(output_folder) / "manifest.json"
    try:
        data = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    data[doi] = {
        "file_path": sanitize_filename(f"{title_base}.pdf"),
        "title": article.get("full_title") or title_base,
        "pmid": article.get("pmid"),
        "date": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass
