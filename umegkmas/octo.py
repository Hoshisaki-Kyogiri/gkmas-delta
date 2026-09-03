"""Octo manifest client.

Two ways to get a manifest:

  fetch(0)   -> the full catalogue (~5 MB, ~46k entries)
  fetch(N)   -> only what changed between revision N and latest (~13 KB for one
                revision's worth). The server does the diffing, entries carry
                full download info, and a `state` of DELETE marks removals.

Incremental mode is therefore just "remember your revision number" - no local
manifest history is needed to compute a diff.
"""

import hashlib
import json
import re
from pathlib import Path

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from google.protobuf.json_format import MessageToJson

from . import octodb_pb2
from .errors import ManifestError, NetworkError

OCTO_ENDPOINT = "https://api.asset.game-gakuen-idolmaster.jp/v2/pub/a/400/v/{app_version}/list/{revision}"
OCTO_API_KEY = "eSquJySjayO5OLLVgdTd"
OCTO_KEY_HEADER = "0jv0wsohnnsigttbfigushbtl3a8m7l5"

# Local octocacheevai (the file the game itself keeps on device) uses a
# different, older key/iv pair than the HTTPS response.
LOCAL_CACHE_KEY = "1nuv9td1bw1udefk"
LOCAL_CACHE_IV = "LvAUtf+tnz"

STATE_ADD = 1
STATE_UPDATE = 2
STATE_LATEST = 3
STATE_DELETE = 4


def _headers(unity_version: str) -> dict:
    return {
        "User-Agent": f"UnityPlayer/{unity_version} (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        "Accept": "application/x-protobuf,x-octo-app/400",
        "X-OCTO-KEY": OCTO_KEY_HEADER,
        "X-Unity-Version": unity_version,
    }


def _decrypt_response(encrypted: bytes) -> bytes:
    if len(encrypted) < 32:
        raise ManifestError(
            "服务器返回的清单太短，无法解密。",
            "多半是游戏更新了。请打开 config.toml 修改 [advanced] 里的 app_version。",
        )
    iv, ciphertext = encrypted[:16], encrypted[16:]
    key = hashlib.sha256(OCTO_API_KEY.encode("utf-8")).digest()
    try:
        return unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(ciphertext), 16, style="pkcs7")
    except ValueError as exc:
        raise ManifestError(
            "清单解密失败。",
            "多半是游戏更新了密钥。请打开 config.toml 修改 [advanced] 里的 app_version。",
        ) from exc


def fetch(revision: int, app_version: str, unity_version: str) -> tuple[octodb_pb2.Database, bytes]:
    """Fetch a manifest. revision=0 means the full catalogue."""
    url = OCTO_ENDPOINT.format(app_version=app_version, revision=revision)
    try:
        response = requests.get(url, headers=_headers(unity_version), timeout=60)
    except requests.exceptions.RequestException as exc:
        raise NetworkError(
            "连不上资源服务器。",
            "检查网络连接或代理设置后重试。",
        ) from exc

    # Both codes come back for a version path the CDN doesn't serve.
    if response.status_code in (400, 404):
        raise ManifestError(
            f"服务器不认识游戏版本 {app_version}。",
            "游戏多半更新了。请打开 config.toml，修改 [advanced] 里的 app_version。",
        )
    if response.status_code != 200:
        raise NetworkError(
            f"服务器返回 HTTP {response.status_code}。",
            "稍后重试；持续失败说明游戏可能更新了。",
        )

    proto_bytes = _decrypt_response(response.content)
    database = octodb_pb2.Database()
    try:
        database.ParseFromString(proto_bytes)
    except Exception as exc:
        raise ManifestError("清单格式无法解析。", "请稍后重试或反馈这个问题。") from exc
    return database, proto_bytes


# Any revision past the newest one comes back as an empty manifest stamped with
# the current revision - 54 bytes, so it is the cheap way to ask "what's latest?"
# without pulling the ~5 MB full catalogue.
PROBE_REVISION = 9999999


def latest_revision(app_version: str, unity_version: str) -> int:
    database, _ = fetch(PROBE_REVISION, app_version, unity_version)
    return database.revision


def decrypt_local_cache(cache_path: Path) -> tuple[octodb_pb2.Database, bytes]:
    """Decrypt an octocacheevai copied off a device. Always a full manifest."""
    if not cache_path.exists():
        raise ManifestError(
            f"找不到本地缓存文件 {cache_path}。",
            "把游戏里的 octocacheevai 放到这个位置，或者去掉 --local-cache 走在线获取。",
        )
    key = hashlib.md5(LOCAL_CACHE_KEY.encode("utf-8")).digest()
    iv = hashlib.md5(LOCAL_CACHE_IV.encode("utf-8")).digest()
    try:
        # The on-device file carries one extra 0x01 byte, then a 16-byte md5 of
        # the payload that follows it.
        decrypted = unpad(
            AES.new(key, AES.MODE_CBC, iv).decrypt(cache_path.read_bytes()[1:]), 16, style="pkcs7"
        )[16:]
    except ValueError as exc:
        raise ManifestError("本地缓存解密失败。", "文件可能损坏或来自不兼容的游戏版本。") from exc

    database = octodb_pb2.Database()
    database.ParseFromString(decrypted)
    return database, decrypted


def _type_of(name: str) -> str:
    match = re.match(r"(.+?)_.*$", name)
    return match.group(1) if match else "others"


def to_dict(database: octodb_pb2.Database) -> dict:
    """Protobuf -> plain dict, with the `type` prefix each stage downstream uses."""
    manifest = json.loads(MessageToJson(database))
    manifest.setdefault("assetBundleList", [])
    manifest.setdefault("resourceList", [])
    for entry in manifest["assetBundleList"] + manifest["resourceList"]:
        entry["type"] = _type_of(entry["name"])
    return manifest


def drop_deleted(manifest: dict) -> tuple[dict, int]:
    """Strip DELETE entries; they name files to remove, not to fetch."""
    removed = 0
    for key in ("assetBundleList", "resourceList"):
        kept = []
        for entry in manifest.get(key, []):
            if entry.get("state") == "DELETE":
                removed += 1
                continue
            kept.append(entry)
        manifest[key] = kept
    return manifest, removed


def save_manifest(manifest: dict, proto_bytes: bytes, out_dir: Path, revision: int, label: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    if proto_bytes is not None:
        (out_dir / f"manifest_{label}").write_bytes(proto_bytes)
    json_path = out_dir / f"manifest_{label}.json"
    json_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return json_path


def total_bytes(manifest: dict) -> int:
    total = 0
    for key in ("assetBundleList", "resourceList"):
        for entry in manifest.get(key, []):
            try:
                total += int(entry.get("size") or 0)
            except (TypeError, ValueError):
                pass
    return total
