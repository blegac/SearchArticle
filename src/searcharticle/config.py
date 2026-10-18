"""Configuration and session-state management.

This module replaces the former mutable globals
(``OUTPUT_FOLDER``, ``YOUR_EMAIL``, ``DIAG``) with:

- :class:`AppConfig`: persistent settings, serialized to ``config.json``.
- :class:`SessionState`: current application state (applied config,
  network diagnostics).

The ``config.json`` file is created automatically at the project root
(next to the ``SearchArticle.bat`` / ``SearchArticle.command`` launchers)
on first launch.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

#: Default output folder name (created at the project root).
DEFAULT_OUTPUT_DIRNAME = "downloaded_pdfs"

#: Default config.json content (no real identifiers).
DEFAULT_CONFIG: dict[str, str] = {
    "email": "",
    "output_folder": "",
    "institution_name": "",
    "institution_ip_prefix": "",
}


def project_root() -> Path:
    """
    Return the project root (folder containing ``src/``, the launchers
    and the README), derived from this file's location.
    """
    # config.py → searcharticle/ → src/ → project root
    return Path(__file__).resolve().parents[2]


def config_file() -> Path:
    """Path of the ``config.json`` file (project root)."""
    return project_root() / "config.json"


def default_output_dir() -> Path:
    """Default output folder (project root)."""
    return project_root() / DEFAULT_OUTPUT_DIRNAME


@dataclass
class AppConfig:
    """
    Persistent application settings (``config.json`` content).

    Attributes:
        email: Email address (required by the Unpaywall API, which rejects
            calls without a valid email).
        output_folder: Destination folder for downloaded PDFs.
        institution_name: Display name of the user's institution
            (e.g. "Sorbonne Université"). Used in the window title, the
            sidebar subtitle and warning messages. Empty means generic
            wording ("Institutional proxy", ...).
        institution_ip_prefix: Public IP prefix of the institution's
            network (e.g. "132.204."). Used to detect campus/VPN access
            for the proxy check. Empty means the proxy check is skipped.
    """

    email: str = DEFAULT_CONFIG["email"]
    output_folder: str = DEFAULT_CONFIG["output_folder"]
    institution_name: str = DEFAULT_CONFIG["institution_name"]
    institution_ip_prefix: str = DEFAULT_CONFIG["institution_ip_prefix"]

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        """Build a config from a dict, ignoring unknown keys."""
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in fields})

    def to_dict(self) -> dict:
        """Serialize the config to a JSON-compatible dict."""
        return asdict(self)


def load_config(path: Path | None = None) -> AppConfig:
    """
    Load the configuration from ``config.json``.

    If the file does not exist or is unreadable, return the default
    configuration. Missing keys are filled in with defaults and unknown
    keys (e.g. legacy proxy keys) are ignored.

    Args:
        path: Config file path (``config.json`` by default).

    Returns:
        The loaded configuration (or the default one).
    """
    file_path = path or config_file()
    if file_path.exists():
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            base = DEFAULT_CONFIG.copy()
            base.update(data)
            return AppConfig.from_dict(base)
        except Exception:
            pass
    return AppConfig.from_dict(DEFAULT_CONFIG)


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    """
    Save the configuration to ``config.json``.

    Args:
        cfg: Configuration to save.
        path: Config file path (``config.json`` by default).
    """
    file_path = path or config_file()
    file_path.write_text(
        json.dumps(cfg.to_dict(), indent=4, ensure_ascii=False),
        encoding="utf-8",
    )


class SessionState:
    """
    Current session state: applied config + network diagnostics.

    This object is created once at startup and passed explicitly to the
    functions that need it (no mutable globals).

    Attributes:
        config: Loaded persistent configuration.
        email: Email for the Unpaywall API (from the config).
        output_folder: PDF output folder (created if missing).
        diag: Network diagnostics state. Keys: ``internet``, ``proxy``,
            ``doi``, ``ncbi``, ``unpaywall``. Values: ``True`` (ok),
            ``False`` (offline), ``None`` (not tested).
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config: AppConfig = config or load_config()
        self.email: str = ""
        self.output_folder: str = ""
        self.diag: dict[str, bool | None] = {
            "internet": None,
            "proxy": None,
            "doi": None,
            "ncbi": None,
            "unpaywall": None,
        }
        self.apply(self.config)

    def apply(self, cfg: AppConfig) -> None:
        """
        Apply a configuration: update the email and the output folder
        (created if it does not exist).

        Args:
            cfg: New configuration to apply.
        """
        self.config = cfg
        self.email = cfg.email
        self.output_folder = cfg.output_folder or str(default_output_dir())
        Path(self.output_folder).mkdir(parents=True, exist_ok=True)

    def output_dir(self) -> Path:
        """Return the output folder as a :class:`Path`."""
        return Path(self.output_folder)
