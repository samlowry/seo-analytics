"""Локальный сервер панели доказательств.

Отдаёт index.html и data.json, ролики с перемоткой (Range), сохранённые главные:
просмотр — без скриптов и без meta refresh, в песочнице; скачивание — как есть.

Запуск: python3 server.py <срез> [<срез> …] [--port 8765] [--data data/data.json]
Адреса файлов: /ev/<имя среза>/<путь>, /page/<имя среза>/<домен>/<вариант>.
"""

import argparse
import gzip
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

HERE = Path(__file__).resolve().parent
PAGE_KINDS = {"browser", "http", "http-mobile", "http-google-mobile", "http-googlebot"}
DOMAIN_RE = re.compile(r"^[a-z0-9.\-]+$")

# Сохранённая страница — HTML чужого сайта. Скрипты и обновление по meta уводили бы
# просмотр на трекеры с IP смотрящего, поэтому вырезаем их и ставим песочницу.
SCRIPT_RE = re.compile(r"<script\b.*?</script\s*>", re.I | re.S)
REFRESH_RE = re.compile(r"<meta[^>]+http-equiv\s*=\s*['\"]?refresh[^>]*>", re.I)
PAGE_CSP = (
    "sandbox; default-src 'none'; img-src * data:; style-src * 'unsafe-inline'; "
    "font-src * data:; media-src *"
)


class Handler(BaseHTTPRequestHandler):
    roots: dict[str, Path]
    data: Path

    def log_message(self, fmt, *args):  # тише: только ошибки
        if args and str(args[1])[:1] in "45":
            super().log_message(fmt, *args)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlsplit(self.path)
        path = unquote(url.path)
        qs = parse_qs(url.query)
        dl = "dl" in qs
        if path in ("/", "/index.html"):
            return self.send_file(HERE / "index.html", "text/html; charset=utf-8")
        if path == "/data.json":
            return self.send_file(self.data, "application/json; charset=utf-8")
        if path.startswith("/ev/"):
            src, _, rel = path[4:].partition("/")
            root = self.roots.get(src)
            f = self.safe(root / "evidence", rel) if root else None
            if not f:
                return self.send_error(HTTPStatus.NOT_FOUND)
            return self.send_file(f, mimetypes.guess_type(f.name)[0] or "application/octet-stream", dl)
        if path.startswith("/page/"):
            return self.send_page(path[6:], dl)
        self.send_error(HTTPStatus.NOT_FOUND)

    def safe(self, base: Path, rel: str) -> Path | None:
        f = (base / rel).resolve()
        if base.resolve() not in f.parents or not f.is_file():
            return None
        return f

    def send_page(self, rest: str, dl: bool):
        src, _, rest = rest.partition("/")
        dom, _, kind = rest.partition("/")
        root = self.roots.get(src)
        if not root or not DOMAIN_RE.match(dom) or kind not in PAGE_KINDS:
            return self.send_error(HTTPStatus.NOT_FOUND)
        f = root / "brand-scan" / "html" / f"{dom}.{kind}.html.gz"
        if not f.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        raw = gzip.open(f).read()
        if dl:
            body = raw
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{dom}.{kind}.html"')
        else:
            text = raw.decode("utf-8", errors="replace")
            text = REFRESH_RE.sub("", SCRIPT_RE.sub("", text))
            base = f'<base href="https://{dom}/"><meta name="referrer" content="no-referrer">'
            text = re.sub(r"(<head[^>]*>)", r"\1" + base.replace("\\", "\\\\"), text, count=1, flags=re.I) \
                if re.search(r"<head[^>]*>", text, re.I) else base + text
            body = text.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", PAGE_CSP)
            self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_file(self, f: Path, ctype: str, dl: bool = False):
        size = f.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(size - int(m.group(2)), 0)
            if start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                return self.end_headers()
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if dl:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(f.name)}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(f, "rb") as fh:
            fh.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = fh.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roots", nargs="+", help="срезы brand-protection/<дата>; имя папки — имя среза в адресах")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--data", default=str(HERE / "data" / "data.json"))
    a = ap.parse_args()
    Handler.roots = {Path(r).resolve().name: Path(r).resolve() for r in a.roots}
    Handler.data = Path(a.data).resolve()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"http://{a.host}:{a.port}/")
    srv.serve_forever()


if __name__ == "__main__":
    main()
