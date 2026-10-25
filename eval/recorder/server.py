"""Local recording tool for the lip-reading evaluation set. Standalone: it does not touch
backend/server.py or frontend/, and runs on its own port (default 8001).

    python3 eval/recorder/server.py            # then open the printed URL (it contains a token)

Videos are written under eval/dataset/ (git-ignored) and never leave this machine: the page has
no external resources and the server makes no outgoing connections. See README.md for the
VS Code Remote SSH and phone instructions.

Layout, per speaker:
    eval/dataset/<speaker>/clips/<speaker>_<clip_id>_<mode>.webm|mp4
    eval/dataset/<speaker>/meta/<same name>.json     source of truth, one per saved clip
    eval/dataset/<speaker>/manifest.csv              rebuilt from meta/ after every save
    eval/dataset/<speaker>/superseded/               earlier takes replaced by a re-record
    eval/dataset/manifest_all.csv                    all speakers
Nothing is ever overwritten or deleted: re-recording a saved clip moves the old take to
superseded/ first.
"""

import argparse
import csv
import hmac
import json
import os
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import plan as P  # noqa: E402

DEFAULT_DATA = HERE.parent / "dataset"
OLD_DATA = Path.home() / "sihyeon" / "data"  # the earlier unlabelled experiments: never used
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MIMES = {"video/webm": ".webm", "video/mp4": ".mp4"}
MAX_BYTES = 300 * 1024 * 1024
MIN_BYTES = 1000
COOKIE = "ssrec"
MANIFEST_COLUMNS = ["video_path", "text", "category", "clip_id", "speaker_id", "speech_mode", "split", "set",
                    "pair_id", "take", "label_status", "mime", "bytes", "duration_s", "attempts", "recorded_at"]


class Conflict(Exception):
    pass


class BadRequest(Exception):
    pass


def base_mime(mime):
    return (mime or "").split(";")[0].strip().lower()


class Store:
    def __init__(self, data_dir):
        self.root = Path(data_dir).resolve()
        if self.root == OLD_DATA.resolve() or OLD_DATA.resolve() in self.root.parents:
            raise SystemExit(f"refusing to use {self.root}: that is the old unlabelled recordings directory")
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.items = self._load_plan()
        self.by_id = {it["clip_id"]: it for it in self.items}

    def _load_plan(self):
        """The plan is snapshotted on first use so clip IDs and labels stay stable for the whole dataset."""
        phrases = P.load_phrases()
        fresh = P.build_plan(phrases)
        snap = self.root / "plan.json"
        if snap.exists():
            saved = json.loads(snap.read_text())
            if saved["phrases_sha"] != P.phrases_sha(phrases) or saved["items"] != fresh:
                print("WARNING: plan.py or demo_phrases.txt changed since this dataset started; "
                      f"using the saved plan in {snap}", file=sys.stderr)
            return saved["items"]
        snap.write_text(json.dumps({"phrases_sha": P.phrases_sha(phrases), "created": time.strftime("%F %T"),
                                    "items": fresh}, indent=2))
        return fresh

    # -- paths ----------------------------------------------------------------
    @staticmethod
    def check_id(value, what):
        if not ID_RE.match(value or ""):
            raise BadRequest(f"bad {what}: use 1-32 letters, digits, - or _")
        return value

    def speaker_dir(self, speaker):
        return self.root / self.check_id(speaker, "speaker_id")

    def stem(self, speaker, item):
        return f"{speaker}_{item['clip_id']}_{item['speech_mode']}"

    def item(self, clip_id):
        if clip_id not in self.by_id:
            raise BadRequest(f"unknown clip_id {clip_id!r}")
        return self.by_id[clip_id]

    # -- reading ----------------------------------------------------------------
    def saved(self, speaker):
        meta_dir = self.speaker_dir(speaker) / "meta"
        out = {}
        if meta_dir.exists():
            for f in meta_dir.glob("*.json"):
                m = json.loads(f.read_text())
                out[m["clip_id"]] = m
        return out

    def clip_path(self, speaker, clip_id):
        m = self.saved(speaker).get(clip_id)
        if not m:
            return None, None
        return self.speaker_dir(speaker) / "clips" / Path(m["video_path"]).name, m["mime"]

    # -- writing ----------------------------------------------------------------
    def save(self, speaker, clip_id, data, mime, attempts=1, duration_s=None, replace=False):
        item = self.item(clip_id)
        mime = base_mime(mime)
        if mime not in MIMES:
            raise BadRequest(f"unsupported video type {mime!r}; expected one of {sorted(MIMES)}")
        if len(data) < MIN_BYTES:
            raise BadRequest(f"video is only {len(data)} bytes: nothing was recorded")
        if len(data) > MAX_BYTES:
            raise BadRequest("video too large")
        sdir = self.speaker_dir(speaker)
        stem = self.stem(speaker, item)
        with self.lock:
            for sub in ("clips", "meta", "superseded"):
                (sdir / sub).mkdir(parents=True, exist_ok=True)
            existing = self.saved(speaker).get(clip_id)
            if existing and not replace:
                raise Conflict(f"{clip_id} is already saved for {speaker}; re-record it to replace (the old take is kept)")
            if existing:
                stamp = time.strftime("%Y%m%d-%H%M%S")
                old_video = sdir / "clips" / Path(existing["video_path"]).name
                for src in (old_video, sdir / "meta" / f"{old_video.stem}.json"):
                    if src.exists():
                        shutil.move(str(src), str(sdir / "superseded" / f"{stamp}_{src.name}"))
            video = sdir / "clips" / f"{stem}{MIMES[mime]}"
            if video.exists():  # unmanaged leftover with the same name: never overwrite it
                video = sdir / "clips" / f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}{MIMES[mime]}"
            tmp = video.with_suffix(video.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, video)
            meta = {
                "video_path": f"clips/{video.name}", "text": item["text"], "category": P.manifest_category(item),
                "clip_id": clip_id, "speaker_id": speaker, "speech_mode": item["speech_mode"],
                "split": item["split"], "set": item["set"], "pair_id": item["pair_id"], "take": item["take"],
                "label_status": item["label_status"], "mime": mime, "bytes": len(data),
                "duration_s": "" if duration_s is None else round(float(duration_s), 2),
                "attempts": attempts, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            (sdir / "meta" / f"{video.stem}.json").write_text(json.dumps(meta, indent=2))
            self.write_manifests()
        return meta

    def write_manifests(self):
        """Rebuild every manifest from the per-clip meta files (caller holds the lock)."""
        order = {it["clip_id"]: i for i, it in enumerate(self.items)}
        combined = []
        for sdir in sorted(d for d in self.root.iterdir() if d.is_dir() and (d / "meta").exists()):
            rows = sorted(self.saved(sdir.name).values(), key=lambda m: order.get(m["clip_id"], 1e9))
            self._write_csv(sdir / "manifest.csv", rows)
            combined += [dict(m, video_path=f"{sdir.name}/{m['video_path']}") for m in rows]
        self._write_csv(self.root / "manifest_all.csv", combined)

    @staticmethod
    def _write_csv(path, rows):
        tmp = path.with_suffix(".csv.part")
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, path)


class Handler(BaseHTTPRequestHandler):
    server_version = "Recorder"
    store: Store = None
    token = ""
    secure = False

    def log_message(self, fmt, *args):  # quiet: only saves are printed
        pass

    # -- helpers ----------------------------------------------------------------
    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", headers=()):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj), "application/json")

    def _authed(self):
        cookies = dict(c.strip().split("=", 1) for c in self.headers.get("Cookie", "").split(";") if "=" in c)
        given = cookies.get(COOKIE) or self.headers.get("X-Recorder-Token") or ""
        return hmac.compare_digest(given.encode(), self.token.encode())

    def _query(self):
        q = parse_qs(urlparse(self.path).query)
        return {k: v[0] for k, v in q.items()}

    # -- routes ----------------------------------------------------------------
    def do_GET(self):
        route, q = urlparse(self.path).path, self._query()
        if route == "/":
            if "token" in q:
                if not hmac.compare_digest(q["token"].encode(), self.token.encode()):
                    return self._send(403, "wrong token")
                flags = "; Secure" if self.secure else ""
                return self._send(302, headers=[("Location", "/"), (
                    "Set-Cookie", f"{COOKIE}={self.token}; Path=/; HttpOnly; SameSite=Strict{flags}")])
            if not self._authed():
                return self._send(401, "Open the full URL printed by the recorder (it ends in ?token=...).")
            return self._send(200, (HERE / "static" / "index.html").read_bytes(), "text/html; charset=utf-8")
        if not self._authed():
            return self._send(401, "unauthorised")
        try:
            if route == "/api/plan":
                speaker = self.store.check_id(q.get("speaker", ""), "speaker_id")
                return self._json(200, {"items": self.store.items, "saved": self.store.saved(speaker)})
            if route == "/api/clip":
                speaker = self.store.check_id(q.get("speaker", ""), "speaker_id")
                path, mime = self.store.clip_path(speaker, q.get("clip_id", ""))
                if not path or not path.exists():
                    return self._send(404, "not saved yet")
                return self._send(200, path.read_bytes(), mime)
        except BadRequest as e:
            return self._json(400, {"error": str(e)})
        self._send(404, "not found")

    def do_POST(self):
        route, q = urlparse(self.path).path, self._query()
        if not self._authed():
            return self._send(401, "unauthorised")
        if route != "/api/save":
            return self._send(404, "not found")
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BYTES:
                raise BadRequest("video too large")
            data = self.rfile.read(length)
            speaker = self.store.check_id(q.get("speaker", ""), "speaker_id")
            meta = self.store.save(
                speaker, q.get("clip_id", ""), data, self.headers.get("Content-Type", ""),
                attempts=int(q.get("attempts", 1)),
                duration_s=float(q["duration"]) if q.get("duration") else None,
                replace=q.get("replace") == "1",
            )
        except Conflict as e:
            return self._json(409, {"error": str(e)})
        except (BadRequest, ValueError) as e:
            return self._json(400, {"error": str(e)})
        print(f"saved {meta['video_path']}  ({meta['bytes'] // 1024} KiB, {meta['split']}, {meta['category']})", flush=True)
        self._json(200, meta)


def make_server(data_dir, token, host="127.0.0.1", port=8001, tls=None):
    """Returns (httpd, store). tls: (certfile, keyfile) or None."""
    store = Store(data_dir)
    handler = type("BoundHandler", (Handler,), {"store": store, "token": token, "secure": bool(tls)})
    httpd = ThreadingHTTPServer((host, port), handler)
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(*tls)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    return httpd, store


def lan_ips():
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()
        return [ip for ip in out if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip)]
    except Exception:
        return []


def ensure_cert(cert_dir):
    """Self-signed certificate for the phone (camera access needs HTTPS). Local files only."""
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert, key = cert_dir / "cert.pem", cert_dir / "key.pem"
    stale = cert.exists() and time.time() - cert.stat().st_mtime > 25 * 86400  # certificate lasts 30 days
    if stale or not (cert.exists() and key.exists()):
        san = ",".join(["DNS:localhost", "IP:127.0.0.1"] + [f"IP:{ip}" for ip in lan_ips()])
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30", "-keyout", str(key),
                        "-out", str(cert), "-subj", "/CN=silent-speech-recorder", "-addext", f"subjectAltName={san}"],
                       check=True, capture_output=True)
        os.chmod(key, 0o600)
    return str(cert), str(key)


def main():
    ap = argparse.ArgumentParser(description="Local recorder for the lip-reading evaluation set.")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA), help="where clips and manifests go (default eval/dataset)")
    ap.add_argument("--lan", action="store_true", help="listen on all interfaces (for a phone); implies --https")
    ap.add_argument("--https", action="store_true", help="serve HTTPS with a local self-signed certificate")
    args = ap.parse_args()
    https = args.https or args.lan
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    token = secrets.token_urlsafe(16)
    tls = ensure_cert(HERE / ".certs") if https else None
    try:
        httpd, store = make_server(args.data_dir, token, host, args.port, tls)
    except OSError as e:
        sys.exit(f"cannot listen on {host}:{args.port}: {e}")
    scheme = "https" if https else "http"
    print(f"data dir: {store.root}   ({len(store.items)} clips in the plan)")
    if args.lan:
        for ip in lan_ips():
            print(f"phone / other device: {scheme}://{ip}:{args.port}/?token={token}")
        print("  (the browser will warn about the self-signed certificate: accept it for this address)")
    print(f"this machine / VS Code forwarded port: {scheme}://localhost:{args.port}/?token={token}")
    print("Ctrl+C to stop. Recordings stay on this machine.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
