# SearchArticle

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-lightgrey)]()

Automated scientific-article PDF downloader with institutional access support. Modern graphical interface (dark mode), compatible with Windows and macOS.

SearchArticle is a desktop app (CustomTkinter GUI) that downloads scientific article PDFs from a DOI, PMID, title, text file, or BibTeX file. It tries publisher access (via your institution's network or VPN), Unpaywall, and PubMed Central in order, with network diagnostics.

---

## Features

- **5 input modes**: DOI, PMID, title (CrossRef + PubMed), text file, BibTeX file
- **Multiple sources** tried in priority order: publisher (institutional access), Unpaywall, PMC
- **Live network diagnostics**: Internet, institutional proxy, DOI resolver, NCBI, Unpaywall
- **Smart retry** with exponential backoff on network errors
- **Automatic** file naming: `Author_et_al_Year.pdf`
- **Resume**: already-downloaded PDFs are skipped automatically

---

## Requirements

- **Python 3.10+** ([download](https://www.python.org/downloads/))
- **Git** (to clone the repository)
- Two external libraries: `customtkinter` and `requests` (everything else is in the standard library)

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/blegac/SearchArticle.git
cd SearchArticle
```

### 2. Create a virtual environment (recommended)

**Windows:**
```bash
python -m venv .venv
.venv\Scripts\activate
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install the project

```bash
pip install -e .
```

This installs the dependencies (`customtkinter`, `requests`) **and** makes the `searcharticle` package importable. This is the step that makes `python -m searcharticle` work.

> If you prefer not to install the package, just use `pip install -r requirements.txt`, but then launch the app via the launcher (`SearchArticle.bat` / `SearchArticle.command`), which sets up the `PYTHONPATH` automatically.

### 4. Configure

Copy the example file (no real identifiers):

```bash
# Windows
copy config.example.json config.json

# macOS / Linux
cp config.example.json config.json
```

Then fill in your email in `config.json` (required by the Unpaywall API, which rejects calls without a valid email - any valid email works, e.g. your university address; it is only used as a contact identifier and is not tied to any institution), or directly from the app's **⚙ Settings** panel.

> ⚠️ `config.json` contains your personal email: it is already in `.gitignore`, **never commit it**.

### 5. Launch the application

```bash
python -m searcharticle
```

Or, if you ran `pip install -e .`:

```bash
searcharticle
```

---

## Launchers (double-click)

To avoid opening a terminal every time, use your OS launcher, placed at the **project root** (next to the `src/` folder).

### Windows — `SearchArticle.bat`

Just double-click it. The script:
- detects the local `.venv` if present (otherwise the system Python)
- installs / updates `customtkinter` and `requests` if needed
- launches `python -m searcharticle`

> **If Windows blocks the file** (SmartScreen): right-click → Properties → check "Unblock" → OK.

### macOS — `SearchArticle.command`

Make it executable **once**:
```bash
chmod +x SearchArticle.command
```

Then double-click. The script:
- detects Python 3 (local venv, Homebrew, pyenv, system)
- installs / updates dependencies if needed
- launches `python -m searcharticle`

> **If macOS blocks the file** (Gatekeeper): right-click → Open → Open anyway.

---

## Usage: the 5 tabs

### DOI
Enter a DOI directly. The field comes pre-filled with an example.
```
10.7554/eLife.102424.3
doi:10.1038/s41586-021-03819-2
```

### PMID
Enter a PubMed identifier. The app queries the PubMed API to get the DOI, title, author and year, then attempts the download.
```
32589966
pmid:32589966
```

### Title
Enter a title (or keywords). The app queries **CrossRef** (then **PubMed** as a fallback) and shows up to 5 clickable results with title, authors, year, journal and DOI. Click **⬇ Download** on the right result.

### Text file
Point to a `.txt` file with identifiers, **one per line**. DOIs and PMIDs can be mixed:
```
10.7554/eLife.102424.3        ← bare DOI
doi:10.1038/s41586-021-03819-2 ← DOI with prefix
32589966                      ← bare PMID
pmid:32589966                 ← PMID with prefix
# comment                     ← ignored line
```

### BibTeX
Point to a `.bib` file. The title, author, year and DOI are extracted automatically from each entry.

---

## Download sources

For each article, sources are tried in this priority order:

| Priority | Source | Condition |
|---|---|---|
| 1 | **Publisher** | Institutional network/VPN active |
| 2 | **Unpaywall** | Legal open-access version available |
| 3 | **PubMed Central (PMC)** | Article deposited on PMC (DOI lookup) |
| 4 | **PMC via PMID** | If PMID available without DOI |

As soon as one source succeeds, the rest are skipped. If the PDF already exists in the output folder, the article is skipped automatically.

---

## Network diagnostics

At the top of the download panel, 5 colored indicators show live connectivity:

| Indicator | Tested service | If red → |
|---|---|---|
| **Internet** | google.com | Check your WiFi / Ethernet connection |
| **Institutional proxy** | Public IP in the configured institutional range | Not on the institutional network/VPN, or no IP prefix configured → set it in Settings |
| **DOI resolver** | doi.org | Check your connection (or your institution's VPN) |
| **NCBI / PMC** | eutils.ncbi.nlm.nih.gov | PMC downloads will be skipped |
| **Unpaywall** | api.unpaywall.org | This source will be skipped |

Set these in the ⚙ Settings panel (**Institutional access** section), or directly in `config.json`: `institution_name` (display name, e.g. `Sorbonne Université` - shown in the window title and warning messages; empty = generic wording) and `institution_ip_prefix` (public IP prefix of your institution's network, e.g. `132.204.` - used for the proxy check; empty = check skipped).

When a service is offline, a clear warning appears in the log and the corresponding source is **skipped immediately** - no waiting on 3 doomed attempts.

Otherwise the app uses automatic retry with exponential backoff (2s, 4s, 6s…) and an extended delay on NCBI rate-limits (HTTP 429).

---

## Configuration

Settings are stored in `config.json` (project root) and editable from the **⚙ Settings** panel.

| Key | Description |
|---|---|
| `email` | Your email (required by the Unpaywall API) |
| `output_folder` | PDF destination folder (default: `downloaded_pdfs/`) |
| `institution_name` | Institution display name (window title, warnings) |
| `institution_ip_prefix` | Public IP prefix used for proxy detection (empty = check skipped) |

---

## File naming

PDFs are named `Author_et_al_Year.pdf`, e.g. `Smith_et_al_2021.pdf`. Characters forbidden on Windows (`< > : " / \ | ? *`) are replaced with `_`, and names are capped at 150 characters.

When the same first author publishes several articles in the same year, an `a`/`b`/`c` suffix is added automatically (academic convention): `Smith_et_al_2021a.pdf`, `Smith_et_al_2021b.pdf`… This prevents an article from being wrongly skipped as "already downloaded".

## Zotero workflow: linking downloaded PDFs

Every successful download is recorded in `manifest.json` (placed in the output folder): it maps each DOI to its PDF file. PDFs already present in the folder (resuming a previous batch) are recorded too. A separate companion script, **link_zotero** (provided separately, not part of this repository), reads this manifest and automatically creates **linked attachments** under the matching Zotero entries (DOI matching, case- and prefix-insensitive).

Setup (once):
1. In Zotero: Preferences → Advanced → Files and Folders → **Linked Attachment Base Directory** → point it to the PDF folder (or its network mount point). Links are stored as relative paths, portable across machines.
2. Close Zotero.

Usage (with the companion script):
```bash
# Dry run (recommended first)
python link_zotero.py --pdf-dir "D:\Papers" --dry-run

# For real (auto-backup of zotero.sqlite, confirmation asked)
python link_zotero.py --pdf-dir "D:\Papers" --base-dir "D:\Papers"
```

Useful options: `--zotero-data-dir` (if your Zotero folder is not `~/Zotero`), `--yes` (no confirmation), `--force` (re-create an existing link), `--no-backup` (not recommended). The script ignores the trash, never attaches under another attachment, and never duplicates a file that is already linked.

---

## Troubleshooting (FAQ)

**"DOI resolver offline" in the log**
→ You are not on your institution's network/VPN. Subscription articles (Elsevier, Springer…) won't be reachable via the publisher. Enable the VPN.

**"NCBI offline" in the log**
→ PMC is temporarily unreachable from your network. Try again later.

**Unpaywall finds no open-access version**
→ The article has no legal free version. Check [Unpaywall](https://unpaywall.org) or [Open Access Button](https://openaccessbutton.org).

**BibTeX file parsed incorrectly**
→ Make sure the file is UTF-8 encoded. Some tools (Mendeley, Zotero) sometimes export in Latin-1.

**`ModuleNotFoundError: No module named 'searcharticle'`**
→ You ran `pip install -r requirements.txt` without installing the package. Run `pip install -e .` at the project root (with the venv activated), then retry `python -m searcharticle`.

**`ModuleNotFoundError: No module named 'customtkinter'`**
→ Install the dependencies: `pip install -e .` (with the venv activated).

---

## Project structure

```
SearchArticle/
├── README.md                  ← this file
├── LICENSE                    ← MIT license
├── pyproject.toml             ← project metadata (pip install -e .)
├── requirements.txt           ← dependencies
├── config.example.json        ← config template (no identifiers)
├── config.json                ← your config (created on 1st launch, git-ignored)
├── SearchArticle.bat          ← Windows launcher
├── SearchArticle.command      ← macOS launcher
├── src/
│   └── searcharticle/
│       ├── __init__.py        ← package version (1.0.0)
│       ├── __main__.py        ← entry point (python -m searcharticle)
│       ├── config.py          ← config + session state (AppConfig, SessionState)
│       ├── utils.py           ← name sanitizing, PDF detection, formatting, detect_type
│       ├── network.py         ← requests, retry/backoff, network diagnostics
│       ├── metadata.py        ← PMID / DOI resolution (PubMed, CrossRef)
│       ├── downloaders.py     ← download sources (publisher, Unpaywall, PMC)
│       └── gui.py             ← CustomTkinter interface (App class)
└── tests/
    ├── test_utils.py          ← unit tests (python -m unittest discover -s tests)
    └── test_downloaders.py    ← downloader unit tests
```

---

## Development

Run the tests:
```bash
python -m unittest discover -s tests
```

Check that all modules compile:
```bash
python -m py_compile src/searcharticle/*.py
```

---

## Legal notes

Access via an institutional VPN or proxy is reserved for members of that institution, for academic purposes, in accordance with the licensing agreements signed by its library.

---

## License

Distributed under the [MIT](LICENSE) license. © 2026 Benjamin Le Gac.
