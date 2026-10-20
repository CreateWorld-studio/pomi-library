# -*- coding: utf-8 -*-
"""Query the local text snapshot. Images are not downloaded."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import threading
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TZ = timezone(timedelta(hours=8))
FILES = ("manifest.json", "index.jsonl", "cards.jsonl", "news.json", "ranks.json")
LOCAL_PORT = 8791
UPDATE_LOCK = threading.Lock()
UPDATING = False


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def home() -> Path:
    override = os.environ.get("ZILIAO_HOME")
    path = Path(override) if override else Path.home() / ".ziliao"
    path.mkdir(parents=True, exist_ok=True)
    return path


def auth_path() -> Path:
    return home() / "auth.json"


def snap_dir() -> Path:
    return home() / "snapshot"


def emit(payload: dict, code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    raise SystemExit(code)


def load_auth() -> dict:
    path = auth_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_auth(data: dict) -> None:
    auth_path().write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def request(url: str, method: str = "GET", payload: dict | None = None, token: str = "", timeout: int = 60):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json, application/zip")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        message = f"HTTP {exc.code}"
        try:
            body = json.loads(raw.decode("utf-8"))
            if isinstance(body, dict) and body.get("error"):
                message = str(body["error"])
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        raise RuntimeError(message) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("连不上资料库后台") from exc


def load_manifest() -> dict | None:
    path = snap_dir() / "manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def install_path() -> Path:
    return home() / "install.json"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def source_base() -> str:
    env = os.environ.get("ZILIAO_PUBLIC", "").strip()
    if env:
        return env.rstrip("/")
    path = app_dir() / "source.txt"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line.rstrip("/")
    return "https://www.pomi.me"


def ensure_id() -> str:
    path = install_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict) and len(str(data.get("id") or "")) == 32:
            return str(data["id"])
    install_id = uuid.uuid4().hex
    path.write_text(json.dumps({"id": install_id}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return install_id


def require_snapshot() -> dict:
    manifest = load_manifest()
    if manifest is None:
        emit({"error": "本机还没有资料。可以先用着，更新会在后台继续。"}, 2)
    return manifest


def read_jsonl(name: str):
    path = snap_dir() / name
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def cmd_login(args: argparse.Namespace) -> None:
    server = args.server.rstrip("/")
    if args.token:
        _status, _ctype, raw = request(server + "/api/plugin/manifest", token=args.token, timeout=20)
        manifest = json.loads(raw.decode("utf-8"))
        save_auth({"server": server, "username": manifest.get("username") or args.username or "", "token": args.token})
        emit({"ok": True, "server": server, "published_at": manifest.get("published_at") or ""})
    if not args.username or not args.password:
        emit({"error": "登录需要 --username 和 --password，或一把已有的 --token。"}, 2)
    _status, _ctype, raw = request(
        server + "/api/plugin/login",
        method="POST",
        payload={"username": args.username, "password": args.password},
        timeout=30,
    )
    body = json.loads(raw.decode("utf-8"))
    save_auth({"server": server, "username": body.get("username") or args.username, "token": body["token"]})
    emit({"ok": True, "username": body.get("username") or args.username, "server": server})


PUBLIC_FILES = ("catalog.js", "index.html")
INDEX_KEYS = (
    "id", "group", "category", "subcategory", "tags", "name_zh", "name_en",
    "summary", "github_url", "stars", "language",
)
CARD_KEYS = INDEX_KEYS + ("description", "forks", "pushed_at", "created_at", "collected_at")
NEWS_KEYS = ("id", "date", "kind", "title", "summary", "source_name", "url", "project_id", "stars")


def fetch_public(name: str, method: str = "GET", timeout: int = 180) -> tuple[dict, bytes]:
    req = urllib.request.Request(source_base() + "/" + name, method=method)
    req.add_header("Accept", "*/*")
    req.add_header("User-Agent", "ziliao")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            body = b"" if method == "HEAD" else response.read()
            return headers, body
    except urllib.error.HTTPError as exc:
        raise RuntimeError("公网页面没有返回 " + name) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("连不上 https://www.pomi.me") from exc


def file_stamp(headers: dict) -> str:
    return str(headers.get("etag") or headers.get("last-modified") or "")


def remote_version() -> dict:
    stamps = []
    for name in PUBLIC_FILES:
        headers, _body = fetch_public(name, method="HEAD", timeout=20)
        stamp = file_stamp(headers)
        if not stamp:
            raise RuntimeError("公网没有给出资料版本")
        stamps.append(stamp)
    return {"published_at": "|".join(stamps)}


def parse_assignment(text: str, marker: str):
    at = text.find(marker)
    if at < 0:
        raise RuntimeError("公网页面里没有资料")
    try:
        data, _end = json.JSONDecoder().raw_decode(text, at + len(marker))
    except json.JSONDecodeError as exc:
        raise RuntimeError("公网资料无法读取") from exc
    return data


def pick(item: dict, keys: tuple[str, ...]) -> dict:
    chosen = {}
    for key in keys:
        value = item.get(key)
        if value in (None, ""):
            continue
        chosen[key] = value
    return chosen


def clean_ranks(raw: dict) -> dict:
    out = {"updated_at": str(raw.get("updated_at") or "")}
    for board in ("github", "ai"):
        block = raw.get(board) if isinstance(raw.get(board), dict) else {}
        out[board] = {}
        for period in ("daily", "weekly", "monthly"):
            ids = block.get(period) or []
            if isinstance(ids, list):
                out[board][period] = [str(item) for item in ids if item]
    return out


def build_snapshot(catalog_text: str, page_text: str) -> dict:
    catalog = parse_assignment(catalog_text, "window.CATALOG = ")
    site = parse_assignment(page_text, "window.SITE = ")
    if not isinstance(catalog, list) or not isinstance(site, dict):
        raise RuntimeError("公网资料无法读取")
    cards = []
    index_rows = []
    for item in catalog:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        card = pick(item, CARD_KEYS)
        card["id"] = str(item["id"])
        cards.append(card)
        index_rows.append(pick(card, INDEX_KEYS))
    news_raw = site.get("news") if isinstance(site.get("news"), list) else []
    news = [pick(item, NEWS_KEYS) for item in news_raw if isinstance(item, dict) and item.get("id")]
    ranks = clean_ranks(site.get("ranks") if isinstance(site.get("ranks"), dict) else {})
    return {"cards": cards, "index": index_rows, "news": news, "ranks": ranks}


def write_snapshot(staging: Path, payload: dict, published_at: str) -> None:
    lines = [json.dumps(row, ensure_ascii=False) for row in payload["index"]]
    (staging / "index.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    lines = [json.dumps(row, ensure_ascii=False) for row in payload["cards"]]
    (staging / "cards.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    (staging / "news.json").write_text(json.dumps(payload["news"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (staging / "ranks.json").write_text(json.dumps(payload["ranks"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "version": 1,
        "published_at": published_at,
        "source": source_base(),
        "counts": {"cards": len(payload["cards"]), "news": len(payload["news"])},
        "files": list(FILES),
    }
    (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def swap_snapshot(staging: Path) -> None:
    dest = snap_dir()
    backup = home() / "snapshot-backup"
    if backup.exists():
        shutil.rmtree(backup)
    if dest.exists():
        dest.rename(backup)
    try:
        staging.rename(dest)
    except OSError:
        if backup.exists() and not dest.exists():
            backup.rename(dest)
        raise
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)


def perform_update() -> dict:
    install_id = ensure_id()
    remote = remote_version()
    local = load_manifest()
    published_at = str(remote.get("published_at") or "")
    counts = (local or {}).get("counts") or {}
    if local and local.get("published_at") == published_at:
        return {
            "ok": True,
            "updated": False,
            "published_at": published_at,
            "cards": counts.get("cards") or 0,
            "news": counts.get("news") or 0,
            "id": install_id,
            "source": source_base(),
        }
    staging = home() / "snapshot-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        catalog_headers, catalog_raw = fetch_public("catalog.js")
        page_headers, page_raw = fetch_public("index.html")
        published_at = "|".join(
            stamp for stamp in (file_stamp(catalog_headers), file_stamp(page_headers)) if stamp
        ) or published_at
        payload = build_snapshot(catalog_raw.decode("utf-8"), page_raw.decode("utf-8"))
        if not payload["cards"]:
            raise RuntimeError("公网资料是空的")
        write_snapshot(staging, payload, published_at)
        swap_snapshot(staging)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "ok": True,
        "updated": True,
        "published_at": published_at,
        "cards": len(payload["cards"]),
        "news": len(payload["news"]),
        "id": install_id,
        "source": source_base(),
    }


def cmd_status(_args: argparse.Namespace) -> None:
    manifest = load_manifest()
    result = {
        "ready": manifest is not None,
        "published_at": (manifest or {}).get("published_at") or "",
        "cards": ((manifest or {}).get("counts") or {}).get("cards") or 0,
        "news": ((manifest or {}).get("counts") or {}).get("news") or 0,
        "source": source_base(),
        "server_reachable": False,
        "needs_update": manifest is None,
        "updating": UPDATING,
    }
    try:
        remote = remote_version()
        result["server_reachable"] = True
        result["remote_published_at"] = remote.get("published_at") or ""
        result["needs_update"] = result["remote_published_at"] != result["published_at"]
    except RuntimeError as exc:
        result["server_message"] = str(exc)
    emit(result)


def cmd_update(_args: argparse.Namespace) -> None:
    global UPDATING
    with UPDATE_LOCK:
        UPDATING = True
        try:
            emit(perform_update())
        finally:
            UPDATING = False


def search_items(query: str, group: str, limit: int) -> dict:
    terms = [part.casefold() for part in query.split() if part.strip()]
    if not terms:
        raise ValueError("请提供要查的词")
    matched = []
    for item in read_jsonl("index.jsonl"):
        if group and group not in (item.get("group"), item.get("category"), item.get("subcategory")):
            continue
        hay_name = " ".join(str(item.get(key) or "") for key in ("name_zh", "name_en", "id")).casefold()
        hay_rest = " ".join([str(item.get("summary") or ""), " ".join(item.get("tags") or [])]).casefold()
        if not all(term in hay_name or term in hay_rest for term in terms):
            continue
        rank = 2 if all(term in hay_name for term in terms) else 1
        matched.append((rank, int(item.get("stars") or 0), item))
    matched.sort(key=lambda row: (-row[0], -row[1], str(row[2].get("name_zh") or "")))
    return {"total": len(matched), "items": [row[2] for row in matched[:limit]]}


def cmd_search(args: argparse.Namespace) -> None:
    require_snapshot()
    try:
        emit(search_items(args.query, args.group.strip(), args.limit))
    except ValueError as exc:
        emit({"error": str(exc)}, 2)


def cmd_card(args: argparse.Namespace) -> None:
    require_snapshot()
    wanted = args.repo.strip().casefold()
    for card in read_jsonl("cards.jsonl"):
        if str(card.get("id") or "").casefold() == wanted:
            emit({"item": card})
    emit({"error": "快照里没有 " + args.repo}, 1)


def cmd_news(args: argparse.Namespace) -> None:
    require_snapshot()
    path = snap_dir() / "news.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        items = []
    today = datetime.now(TZ).date()
    earliest = (today - timedelta(days=max(args.days, 1) - 1)).isoformat()
    chosen = [item for item in items if str(item.get("date") or "") >= earliest]
    if args.kind:
        chosen = [item for item in chosen if item.get("kind") == args.kind]
    emit({"items": chosen[: args.limit]})


def cmd_ranks(args: argparse.Namespace) -> None:
    require_snapshot()
    ranks = json.loads((snap_dir() / "ranks.json").read_text(encoding="utf-8"))
    board = args.board if args.board in ("github", "ai") else "github"
    period = args.period if args.period in ("daily", "weekly", "monthly") else "daily"
    ids = ((ranks.get(board) or {}).get(period) or [])[: args.limit]
    names = {}
    wanted = {item.casefold() for item in ids}
    if wanted:
        for row in read_jsonl("index.jsonl"):
            if str(row.get("id") or "").casefold() in wanted:
                names[str(row["id"]).casefold()] = row
    items = []
    for repo_id in ids:
        row = names.get(repo_id.casefold(), {})
        items.append({
            "id": repo_id,
            "name_zh": row.get("name_zh") or "",
            "summary": row.get("summary") or "",
            "stars": row.get("stars") or 0,
            "group": row.get("group") or "",
            "category": row.get("category") or "",
        })
    emit({"updated_at": ranks.get("updated_at") or "", "board": board, "period": period, "items": items})


def cmd_password(args: argparse.Namespace) -> None:
    auth = load_auth()
    server = (args.server or auth.get("server") or "").rstrip("/")
    username = args.username or auth.get("username") or ""
    if not server or not username or not args.old or not args.new:
        emit({"error": "修改密码需要原密码、新密码，以及后台地址和用户名。已经登录过就可以不重复填地址和用户名。"}, 2)
    request(
        server + "/api/account/password",
        method="POST",
        payload={"username": username, "old": args.old, "new": args.new},
        timeout=30,
    )
    if auth.get("server"):
        auth.pop("token", None)
        save_auth(auth)
    emit({"ok": True, "username": username, "relogin": True})


def local_state() -> dict:
    manifest = load_manifest() or {}
    counts = manifest.get("counts") or {}
    return {
        "ready": bool(manifest),
        "published_at": manifest.get("published_at") or "",
        "cards": counts.get("cards") or 0,
        "news": counts.get("news") or 0,
        "updating": UPDATING,
    }


def start_silent_update() -> None:
    def run() -> None:
        global UPDATING
        if not UPDATE_LOCK.acquire(blocking=False):
            return
        UPDATING = True
        try:
            perform_update()
        except RuntimeError:
            return
        finally:
            UPDATING = False
            UPDATE_LOCK.release()

    threading.Thread(target=run, daemon=True).start()


class LibraryHandler(BaseHTTPRequestHandler):
    server_version = "ZiliaoLibrary"

    def log_message(self, fmt: str, *args) -> None:
        return

    def send_json(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/":
            page = (app_dir() / "library.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(page)
            return
        if path == "/local/state":
            self.send_json(local_state())
            return
        if not load_manifest():
            self.send_json({"ready": False, "items": [], "total": 0}, 200)
            return
        if path == "/local/search":
            text = (query.get("q") or [""])[0]
            group = (query.get("group") or [""])[0]
            limit = int((query.get("limit") or ["8"])[0] or 8)
            try:
                self.send_json(search_items(text, group, min(max(limit, 1), 20)))
            except ValueError as exc:
                self.send_json({"error": str(exc), "items": [], "total": 0}, 400)
            return
        if path == "/local/card":
            wanted = (query.get("id") or [""])[0].strip().casefold()
            for card in read_jsonl("cards.jsonl"):
                if str(card.get("id") or "").casefold() == wanted:
                    self.send_json({"item": card})
                    return
            self.send_json({"error": "这条已经不在资料库里"}, 404)
            return
        if path == "/local/news":
            items = json.loads((snap_dir() / "news.json").read_text(encoding="utf-8"))
            today = datetime.now(TZ).date()
            earliest = (today - timedelta(days=6)).isoformat()
            chosen = [item for item in items if str(item.get("date") or "") >= earliest]
            self.send_json({"items": chosen[:30]})
            return
        if path == "/local/ranks":
            ranks = json.loads((snap_dir() / "ranks.json").read_text(encoding="utf-8"))
            board = (query.get("board") or ["github"])[0]
            period = (query.get("period") or ["daily"])[0]
            if board not in ("github", "ai"):
                board = "github"
            if period not in ("daily", "weekly", "monthly"):
                period = "daily"
            ids = ((ranks.get(board) or {}).get(period) or [])[:10]
            names = {}
            wanted = {item.casefold() for item in ids}
            for row in read_jsonl("index.jsonl"):
                if str(row.get("id") or "").casefold() in wanted:
                    names[str(row["id"]).casefold()] = row
            items = []
            for repo_id in ids:
                row = names.get(repo_id.casefold(), {})
                items.append({
                    "id": repo_id,
                    "name_zh": row.get("name_zh") or "",
                    "summary": row.get("summary") or "",
                    "stars": row.get("stars") or 0,
                })
            self.send_json({"updated_at": ranks.get("updated_at") or "", "board": board, "period": period, "items": items})
            return
        self.send_json({"error": "没有这个地址"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/local/touch":
            self.send_json({"error": "没有这个地址"}, 404)
            return
        ensure_id()
        start_silent_update()
        self.send_json(local_state())


def cmd_open(_args: argparse.Namespace) -> None:
    from shell import launch
    launch()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ziliao")
    sub = parser.add_subparsers(dest="cmd", required=True)
    login = sub.add_parser("login")
    login.add_argument("--server", required=True)
    login.add_argument("--username", default="")
    login.add_argument("--password", default="")
    login.add_argument("--token", default="")
    login.set_defaults(func=cmd_login)
    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)
    update = sub.add_parser("update")
    update.set_defaults(func=cmd_update)
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--group", default="")
    search.add_argument("--limit", type=int, default=8)
    search.set_defaults(func=cmd_search)
    card = sub.add_parser("card")
    card.add_argument("repo")
    card.set_defaults(func=cmd_card)
    news = sub.add_parser("news")
    news.add_argument("--days", type=int, default=7)
    news.add_argument("--kind", default="")
    news.add_argument("--limit", type=int, default=20)
    news.set_defaults(func=cmd_news)
    ranks = sub.add_parser("ranks")
    ranks.add_argument("--board", default="github", choices=("github", "ai"))
    ranks.add_argument("--period", default="daily", choices=("daily", "weekly", "monthly"))
    ranks.add_argument("--limit", type=int, default=10)
    ranks.set_defaults(func=cmd_ranks)
    opened = sub.add_parser("open")
    opened.set_defaults(func=cmd_open)
    password = sub.add_parser("password")
    password.add_argument("--old", required=True)
    password.add_argument("--new", required=True)
    password.add_argument("--server", default="")
    password.add_argument("--username", default="")
    password.set_defaults(func=cmd_password)
    return parser


def main() -> None:
    configure_stdio()
    if getattr(sys, "frozen", False) and len(sys.argv) == 1:
        sys.argv.append("open")
    args = build_parser().parse_args()
    if args.cmd == "search":
        args.limit = min(max(args.limit, 1), 20)
    if args.cmd in ("news", "ranks"):
        args.limit = min(max(args.limit, 1), 30)
    try:
        args.func(args)
    except RuntimeError as exc:
        emit({"error": str(exc)}, 1)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
