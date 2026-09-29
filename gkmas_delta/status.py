"""Local and server status, shared by `--status` and the web console."""

from . import octo
from .state import State


def local_status(config) -> dict:
    state = State.load(config.paths.state_file)
    return {
        "has_baseline": state.has_baseline,
        "revision": state.last_revision,
        "updated_at": state.updated_at,
        "state_app_version": state.app_version,
        "app_version": config.app_version,
        "app_version_changed": not state.matches_app_version(config.app_version),
        "data_dir": str(config.paths.data_dir),
        "history": list(reversed(state.history[-10:])),
    }


def preview_from(config, start: int) -> dict:
    """What fetching vSTART (inclusive) up to the latest would download."""
    diff, _ = octo.fetch(max(start - 1, 0), config.app_version, config.unity_version)
    manifest, _ = octo.drop_deleted(octo.to_dict(diff))
    return {
        "start": start,
        "revision": manifest["revision"],
        "bundles": len(manifest["assetBundleList"]),
        "files": len(manifest["resourceList"]),
        "bytes": octo.total_bytes(manifest),
    }


def server_status(config) -> dict:
    """Ask the server where it is. Raises UmeError on network or version trouble."""
    state = State.load(config.paths.state_file)
    # A probe past the newest revision answers this in 54 bytes; pulling the
    # full catalogue just to read one number would cost ~5 MB.
    newest = octo.latest_revision(config.app_version, config.unity_version)
    result = {"server_revision": newest, "pending": None}

    if state.has_baseline and state.matches_app_version(config.app_version) and newest > state.last_revision:
        diff, _ = octo.fetch(state.last_revision, config.app_version, config.unity_version)
        manifest, _ = octo.drop_deleted(octo.to_dict(diff))
        result["pending"] = {
            "bundles": len(manifest["assetBundleList"]),
            "files": len(manifest["resourceList"]),
            "bytes": octo.total_bytes(manifest),
        }
    return result
