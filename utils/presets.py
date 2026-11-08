from __future__ import annotations

import json
import shutil
import sys
import urllib.request
import urllib.error
import ssl
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

def _bundled_presets_dir() -> Path:
    """Presets shipped with the app (inside the PyInstaller bundle when frozen)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "presets"


def _user_presets_dir() -> Path:
    """Writable presets folder.

    From source: the repo's presets/ folder (as before).
    Frozen build: ~/.dither_guy/presets, seeded once with the bundled presets
    (the bundle dir is temporary / read-only, and the old relative path
    depended on the current working directory).
    """
    if not getattr(sys, "frozen", False):
        return _bundled_presets_dir()
    user = Path.home() / ".dither_guy" / "presets"
    try:
        user.mkdir(parents=True, exist_ok=True)
        src = _bundled_presets_dir()
        if src.is_dir():
            for f in src.glob("*.json"):
                dst = user / f.name
                if not dst.exists():
                    shutil.copy2(f, dst)
    except OSError:
        pass
    return user


PRESETS_DIR = _user_presets_dir()


def save_preset(name: str, params: dict) -> Path:
    PRESETS_DIR.mkdir(exist_ok=True)
    safe = "".join(c for c in name if c.isalnum() or c in " _-").strip() or "preset"
    path = PRESETS_DIR / f"{safe}.json"
    p = dict(params)
    p.setdefault("category", DEFAULT_CATEGORY)
    if isinstance(p.get("color"), tuple):
        p["color"] = list(p["color"])
    with open(path, "w") as f:
        json.dump(p, f, indent=2)
    return path


def load_preset(name: str) -> Optional[dict]:
    n = name if name.endswith(".json") else f"{name}.json"
    path = PRESETS_DIR / n
    if not path.exists():
        return None
    try:
        with open(path) as f:
            p = json.load(f)
        if "color" in p and isinstance(p["color"], list):
            p["color"] = tuple(p["color"])
        return p
    except Exception:
        return None


def list_presets() -> list[str]:
    if not PRESETS_DIR.exists():
        return []
    return sorted(p.stem for p in PRESETS_DIR.glob("*.json"))


def delete_preset(name: str) -> bool:
    n = name if name.endswith(".json") else f"{name}.json"
    path = PRESETS_DIR / n
    if path.exists():
        path.unlink()
        return True
    return False


class DownloadPresetsWorker(QThread):
    progress = Signal(str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, repo: str = "shahil-sk/dither-guy", branch: str = "master"):
        super().__init__()
        self.repo = repo
        self.branch = branch

    def run(self):
        ctx = ssl.create_default_context()  # certificate verification stays ON

        api_url = f"https://api.github.com/repos/{self.repo}/contents/presets?ref={self.branch}"
        try:
            self.progress.emit("Fetching preset list from GitHub...")
            req = urllib.request.Request(api_url, headers={'User-Agent': 'DitherGuy-App'})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                data = json.loads(response.read().decode())
            
            if not isinstance(data, list):
                self.error.emit("Presets folder not found on GitHub.")
                return

            downloaded = []
            PRESETS_DIR.mkdir(exist_ok=True)
            
            files_to_download = [item for item in data if item.get("type") == "file" and item.get("name", "").endswith(".json")]
            
            if not files_to_download:
                self.error.emit("No preset files found in the repository.")
                return

            for i, item in enumerate(files_to_download):
                # Never trust the remote name as a path: keep the bare file name.
                name = Path(str(item["name"])).name
                if not name.endswith(".json") or name.startswith("."):
                    continue
                file_url = item.get("download_url")
                if not file_url:
                    continue
                    
                self.progress.emit(f"Downloading {name}... ({i+1}/{len(files_to_download)})")
                freq = urllib.request.Request(file_url, headers={'User-Agent': 'DitherGuy-App'})
                with urllib.request.urlopen(freq, timeout=10, context=ctx) as fres:
                    content = fres.read(1_000_000).decode()
                    try:
                        if not isinstance(json.loads(content), dict):
                            continue
                    except ValueError:
                        continue  # not a preset, skip it
                    save_path = PRESETS_DIR / name
                    with open(save_path, "w") as f:
                        f.write(content)
                    downloaded.append(name)
                    
            self.finished.emit(downloaded)
            
        except urllib.error.HTTPError as e:
            if e.code == 404:
                self.error.emit("Presets folder not found on GitHub repository.")
            else:
                self.error.emit(f"HTTP Error: {e.code} {e.reason}")
        except Exception as e:
            self.error.emit(f"Failed to download presets: {str(e)}")


# ---------------------------------------------------------------------------
# Categories, favourites, recents
# ---------------------------------------------------------------------------

DEFAULT_CATEGORY = "My Presets"


def preset_categories() -> dict[str, list[str]]:
    """{category: [preset names]} read from each file's "category" key."""
    cats: dict[str, list[str]] = {}
    for name in list_presets():
        p = load_preset(name) or {}
        cats.setdefault(str(p.get("category") or DEFAULT_CATEGORY), []).append(name)
    return dict(sorted(cats.items(), key=lambda kv: (kv[0] == DEFAULT_CATEGORY, kv[0])))


def _settings():
    from PySide6.QtCore import QSettings
    return QSettings("DitherGuy", "DitherGuy")


def _str_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v else []
    return [str(x) for x in v]


def favorite_presets() -> list[str]:
    existing = set(list_presets())
    return [n for n in _str_list(_settings().value("presets/favorites")) if n in existing]


def is_favorite(name: str) -> bool:
    return name in favorite_presets()


def toggle_favorite(name: str) -> bool:
    favs = favorite_presets()
    on = name not in favs
    favs = favs + [name] if on else [n for n in favs if n != name]
    _settings().setValue("presets/favorites", favs)
    return on


def recent_presets() -> list[str]:
    existing = set(list_presets())
    return [n for n in _str_list(_settings().value("presets/recent")) if n in existing]


def push_recent(name: str, keep: int = 10) -> None:
    rec = [name] + [n for n in recent_presets() if n != name]
    _settings().setValue("presets/recent", rec[:keep])
