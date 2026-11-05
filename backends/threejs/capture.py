"""capture.py — backend Three.js nhìn từ phía Python.

render_bundle(bundle_path, frames_dir): mở một HTTP server loopback phục vụ repo (để import map tới
node_modules/three chạy được qua ES module), rồi gọi capture.cjs render từng khung bằng Chromium headless.
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
NODE_MODULES = HERE / "node_modules" / "three"


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Phục vụ hai đường: /repo/... → gốc repo, /bundle.json → file bundle (có thể nằm ngoài repo)."""

    bundle_path: Path = Path()

    def translate_path(self, path: str) -> str:  # noqa: N802
        path = path.split("?", 1)[0].split("#", 1)[0]
        if path == "/bundle.json":
            return str(self.bundle_path)
        if path.startswith("/repo/"):
            rel = os.path.normpath(path[len("/repo/"):]).lstrip("/\\")
            if rel.startswith(".."):
                return str(REPO_ROOT / "__forbidden__")
            return str(REPO_ROOT / rel)
        return str(REPO_ROOT / "__not_found__")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):  # im lặng
        pass


def ensure_node_modules() -> None:
    if NODE_MODULES.exists():
        return
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("thiếu backends/threejs/node_modules/three và không có npm để cài: chạy `npm ci` trong backends/threejs")
    cmd = [npm, "ci"] if (HERE / "package-lock.json").exists() else [npm, "install"]
    subprocess.run(cmd, cwd=HERE, check=True)


def render_bundle(bundle_path: Path, frames_dir: Path, *, timeout_s: int = 600) -> dict:
    bundle_path = Path(bundle_path).resolve()
    frames_dir = Path(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    ensure_node_modules()
    if not shutil.which("node"):
        raise RuntimeError("không có node trên PATH; backend threejs cần Node.js ≥ 18 và playwright")

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    width, height = bundle["render"]["width"], bundle["render"]["height"]

    handler = partial(_Handler, directory=str(REPO_ROOT))
    _Handler.bundle_path = bundle_path
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/repo/backends/threejs/index.html?bundle=/bundle.json"
        cmd = ["node", str(HERE / "capture.cjs"), "--url", url, "--out", str(frames_dir),
               "--width", str(width), "--height", str(height)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        if proc.returncode != 0:
            raise RuntimeError(f"capture.cjs thoát mã {proc.returncode}:\n{proc.stderr.strip()}")
        return json.loads(proc.stdout.strip().splitlines()[-1])
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Render một scene_bundle.json bằng Three.js trong Chromium headless")
    ap.add_argument("bundle", type=Path)
    ap.add_argument("out", type=Path)
    a = ap.parse_args()
    print(json.dumps(render_bundle(a.bundle, a.out)))
    sys.exit(0)
