# -*- coding: utf-8 -*-
"""Open the public site inside a local window. Download is added only here."""
from __future__ import annotations

import json
import shutil
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import ziliao

REPO_MARK = "/"
POLL_SECONDS = 30
INJECT = (ziliao.app_dir() / "client.js").read_text(encoding="utf-8")


def config_path() -> Path:
    return ziliao.home() / "client.json"


def load_config() -> dict:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(data: dict) -> None:
    config_path().write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def download_dir() -> Path:
    raw = str(load_config().get("download_dir") or "").strip()
    path = Path(raw) if raw else Path.home() / "Downloads" / "资料库"
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_download_dir(path: str) -> str:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    data = load_config()
    data["download_dir"] = str(target)
    save_config(data)
    return str(target)


def valid_repo(repo: str) -> bool:
    owner, _sep, name = repo.partition(REPO_MARK)
    if not owner or not name or REPO_MARK in name:
        return False
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.")
    return all(char in allowed for char in owner + name)


def within(root: Path, target: Path) -> bool:
    root = root.resolve()
    target = target.resolve()
    return target == root or root in target.parents


def extract_zip(archive_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            parts = Path(info.filename).parts
            if not info.filename or info.filename.startswith(("/", "\\")) or ".." in parts:
                raise RuntimeError("压缩包路径不安全")
            if not within(dest, dest / info.filename):
                raise RuntimeError("压缩包路径不安全")
        archive.extractall(dest)


def download_repo(repo: str, folder: Path | None = None) -> dict:
    repo = repo.strip().strip("/")
    if not valid_repo(repo):
        return {"ok": False, "message": "仓库名不正确"}
    owner, name = repo.split("/", 1)
    root = folder or download_dir()
    root.mkdir(parents=True, exist_ok=True)
    dest = root / f"{owner}__{name}"
    staging = root / f"{owner}__{name}.part"
    archive_path = root / f"{owner}__{name}.zip"
    if staging.exists():
        shutil.rmtree(staging)
    url = "https://api.github.com/repos/" + repo + "/zipball"
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("User-Agent", "ziliao")
    try:
        with urllib.request.urlopen(request, timeout=300) as response, archive_path.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except urllib.error.HTTPError as exc:
        archive_path.unlink(missing_ok=True)
        if exc.code == 404:
            return {"ok": False, "message": "这个仓库下载不到"}
        if exc.code in (403, 429):
            return {"ok": False, "message": "GitHub 暂时限制了下载，过一会再试"}
        return {"ok": False, "message": "下载失败"}
    except urllib.error.URLError:
        archive_path.unlink(missing_ok=True)
        return {"ok": False, "message": "连不上 GitHub"}
    try:
        extract_zip(archive_path, staging)
    except (OSError, zipfile.BadZipFile, RuntimeError):
        shutil.rmtree(staging, ignore_errors=True)
        return {"ok": False, "message": "下载到的压缩包打不开"}
    finally:
        archive_path.unlink(missing_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    staging.rename(dest)
    return {"ok": True, "path": str(dest), "message": "已下载到 " + str(dest)}


class ClientApi:
    def __init__(self) -> None:
        self.busy = False

    def current_dir(self) -> str:
        return str(download_dir())

    def choose_dir(self) -> str:
        import webview

        window = webview.windows[0]
        kind = webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG
        chosen = window.create_file_dialog(kind)
        if not chosen:
            return ""
        return set_download_dir(chosen[0])

    def download(self, repo: str) -> dict:
        self.busy = True
        try:
            return download_repo(repo)
        finally:
            self.busy = False


def page_url() -> str:
    return ziliao.source_base() + "/"


def disable_http_cache(window) -> None:
    from System import Func, Object

    form = window.native

    def run():
        core = form.webview.CoreWebView2
        core.CallDevToolsProtocolMethodAsync("Network.setCacheDisabled", '{"cacheDisabled":true}')
        return None

    form.Invoke(Func[Object](run))


def watch_public(window, api: ClientApi, stop: threading.Event) -> None:
    if not window.events.loaded.wait(30):
        return
    seen = ""
    try:
        seen = str(ziliao.remote_version().get("published_at") or "")
    except RuntimeError:
        seen = ""
    while not stop.wait(POLL_SECONDS):
        if api.busy:
            continue
        try:
            stamp = str(ziliao.remote_version().get("published_at") or "")
        except RuntimeError:
            continue
        if not stamp:
            continue
        if seen and stamp != seen:
            try:
                window.evaluate_js("location.reload()")
            except Exception:
                continue
        seen = stamp


def launch() -> None:
    try:
        import webview
    except ImportError as exc:
        raise SystemExit("缺少窗口组件。先运行 python -m pip install pywebview") from exc
    api = ClientApi()
    stop = threading.Event()
    fresh = {"done": False}
    window = webview.create_window("资料库", page_url(), js_api=api, width=1280, height=860)

    def refresh_once() -> None:
        try:
            disable_http_cache(window)
        except Exception:
            pass
        try:
            window.evaluate_js("location.reload()")
        except Exception:
            return

    def on_loaded() -> None:
        window.evaluate_js(INJECT)
        if fresh["done"]:
            return
        fresh["done"] = True
        threading.Thread(target=refresh_once, daemon=True).start()

    window.events.loaded += on_loaded
    threading.Thread(target=watch_public, args=(window, api, stop), daemon=True).start()
    try:
        webview.start()
    finally:
        stop.set()
