"""Local update state.

The whole point of the incremental mode: the server does the diffing, so all we
have to remember is which revision we last completed. Kept in one small JSON so
a user can inspect or reset it by hand.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

STATE_VERSION = 1


@dataclass
class State:
    path: Path
    app_version: str = ""
    last_revision: int = 0
    updated_at: str = ""
    history: list = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "State":
        if not path.exists():
            return cls(path=path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt state file must not brick the tool; fall back to "unknown"
            # and let the caller re-establish a baseline.
            return cls(path=path)
        return cls(
            path=path,
            app_version=str(raw.get("app_version", "")),
            last_revision=int(raw.get("last_revision", 0)),
            updated_at=str(raw.get("updated_at", "")),
            history=list(raw.get("history", [])),
        )

    @property
    def has_baseline(self) -> bool:
        return self.last_revision > 0

    def matches_app_version(self, app_version: str) -> bool:
        # Revision numbering is scoped to the app version in the octo URL, so a
        # remembered revision is meaningless once that changes.
        return not self.app_version or self.app_version == app_version

    def record(self, app_version: str, revision: int, note: str) -> None:
        self.app_version = app_version
        self.last_revision = revision
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.history.append({"revision": revision, "at": self.updated_at, "note": note})
        self.history = self.history[-50:]
        self.save()

    def save(self) -> None:
        payload = {
            "state_version": STATE_VERSION,
            "app_version": self.app_version,
            "last_revision": self.last_revision,
            "updated_at": self.updated_at,
            "history": self.history,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
