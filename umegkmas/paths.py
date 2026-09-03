"""Path anchoring.

Every path in the app derives from here. Nothing is resolved against the current
working directory, so the launcher can be double-clicked from anywhere and a
frozen/embedded build behaves the same as a source checkout.
"""

import sys
from pathlib import Path


def _app_dir() -> Path:
    # PyInstaller / embedded builds put the executable next to the data folder;
    # a source checkout uses the package's parent.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_DIR = _app_dir()
CONFIG_PATH = APP_DIR / "config.toml"


class DataPaths:
    """Resolved data locations. Built once from config, passed around explicitly."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.state_file = data_dir / "state.json"
        self.manifests = data_dir / "manifests"
        self.assets = data_dir / "gkmas" / "Assets"
        self.resources = data_dir / "gkmas" / "Resource"
        self.unobfuscated = data_dir / "gkmas" / "UnobfuscateAssets"
        self.images = data_dir / "IMAGE"
        self.converted = data_dir / "IMAGE" / "Converted"

    def ensure(self) -> None:
        for path in (self.data_dir, self.manifests):
            path.mkdir(parents=True, exist_ok=True)

    def revision_images(self, revision: int) -> Path:
        return self.images / f"v{revision}"

    def revision_converted(self, revision: int) -> Path:
        return self.converted / f"v{revision}"

    def revision_unobfuscated(self, revision: int) -> Path:
        return self.unobfuscated / str(revision)
