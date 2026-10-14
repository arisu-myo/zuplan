"""フローチャート仕様(.fc)のブラウザエディタと、Pythonコードからの取り込みツール。

使い方:
    python flowchart.py --serve                 # 図エディタのサーバを起動(図は data/flowchart.db に保存)
    python flowchart.py --serve my.fc           # .fc / .py を取り込んで、新しい図として開く
    python flowchart.py --serve --host 0.0.0.0 --db /srv/flowchart.db   # サーバとして公開
    python flowchart.py my.py --fc              # コード → .fc に変換(out/my.fc)
    python flowchart.py my.py --html            # Mermaid表示のHTML(out/my.html)
    python flowchart.py my.py                   # Mermaidを画面に出力
"""
import argparse
import ast
import html
import json
import os
import re
import sys
import threading
import webbrowser
import access
import fcspec
import landing_page
import mcp_server
import store
from editor_page import PAGE
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit


def label(text, limit=48):
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


class Builder:
    def __init__(self, title):
        self.title = title
        self.nodes = []  # (id, text, shape)
        self.edges = []  # (from, to, label)
        self.n = 0
        self.loops = []  # (head_id, break_exits)
        self.end = None

    def node(self, text, shape="rect"):
        self.n += 1
        nid = f"N{self.n}"
        self.nodes.append((nid, label(text), shape))
        return nid

    def link(self, preds, nid):
        for p, lbl in preds:
            self.edges.append((p, nid, lbl))

    def build(self, body, args_text=""):
        start = self.node(f"開始 {args_text}".strip(), "round")
        self.end = self.node("終了", "round")
        exits = self.block(body, [(start, "")])
        self.link(exits, self.end)
        return self

    def to_mermaid(self):
        lines = ["flowchart TD"]
        for nid, text, shape in self.nodes:
            t = text.replace('"', "#quot;")
            fmt = {"rect": f'["{t}"]', "round": f'(["{t}"])',
                   "diamond": f'{{"{t}"}}', "para": f'[/"{t}"/]'}[shape]
            lines.append(f"    {nid}{fmt}")
        for a, b, lbl in self.edges:
            lines.append(f"    {a} {f'-->|{lbl}|' if lbl else '-->'} {b}")
        return "\n".join(lines)

    def to_graph(self):
        """fcspec 形式の1ページ分(配置つき)。"""
        kind = {"rect": "proc", "diamond": "if", "para": "io"}
        nodes = []
        for i, (nid, text, shape) in enumerate(self.nodes):
            t = "start" if i == 0 else "end" if nid == self.end else kind[shape]
            if text == "try":
                t = "if"
            elif text.startswith("except"):
                t = "proc"
            nodes.append({"id": nid, "type": t, "text": text, "memo": ""})
        g = {"nodes": nodes,
             "edges": [{"from": a, "to": b, "label": lbl, "memo": ""} for a, b, lbl in self.edges]}
        fcspec.autolayout(g)
        return g

    def block(self, stmts, preds):
        for s in stmts:
            if not preds:  # 到達不能コード
                break
            preds = self.stmt(s, preds)
        return preds

    def stmt(self, s, preds):
        if isinstance(s, ast.If):
            c = self.node(ast.unparse(s.test) + " ?", "diamond")
            self.link(preds, c)
            yes = self.block(s.body, [(c, "Yes")])
            no = self.block(s.orelse, [(c, "No")]) if s.orelse else [(c, "No")]
            return yes + no

        if isinstance(s, (ast.While, ast.For, ast.AsyncFor)):
            if isinstance(s, ast.While):
                c = self.node(ast.unparse(s.test) + " ?", "diamond")
                cont, done = "Yes", "No"
            else:
                c = self.node(f"for {ast.unparse(s.target)} in {ast.unparse(s.iter)}", "diamond")
                cont, done = "次", "完了"
            self.link(preds, c)
            breaks = []
            self.loops.append((c, breaks))
            body_exits = self.block(s.body, [(c, cont)])
            self.loops.pop()
            self.link(body_exits, c)
            if s.orelse:
                return self.block(s.orelse, [(c, done)]) + breaks
            return [(c, done)] + breaks

        if isinstance(s, ast.Return):
            n = self.node("return " + (ast.unparse(s.value) if s.value else ""), "para")
            self.link(preds, n)
            self.link([(n, "")], self.end)
            return []

        if isinstance(s, ast.Raise):
            n = self.node("raise " + (ast.unparse(s.exc) if s.exc else ""), "para")
            self.link(preds, n)
            self.link([(n, "")], self.end)
            return []

        if isinstance(s, ast.Break) and self.loops:
            n = self.node("break")
            self.link(preds, n)
            self.loops[-1][1].append((n, ""))
            return []

        if isinstance(s, ast.Continue) and self.loops:
            n = self.node("continue")
            self.link(preds, n)
            self.link([(n, "")], self.loops[-1][0])
            return []

        if isinstance(s, ast.Try):
            t = self.node("try")
            self.link(preds, t)
            exits = self.block(s.body, [(t, "実行")])
            if s.orelse:
                exits = self.block(s.orelse, exits)
            for h in s.handlers:
                e = self.node("except " + (ast.unparse(h.type) if h.type else ""), "diamond")
                self.link([(t, "例外")], e)
                exits += self.block(h.body, [(e, "")])
            if s.finalbody:
                f = self.node("finally")
                self.link(exits, f)
                exits = self.block(s.finalbody, [(f, "")])
            return exits

        if isinstance(s, (ast.With, ast.AsyncWith)):
            n = self.node("with " + ", ".join(ast.unparse(i) for i in s.items))
            self.link(preds, n)
            return self.block(s.body, [(n, "")])

        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return preds  # 別チャートとして出力する

        is_io = isinstance(s, ast.Expr) and isinstance(s.value, ast.Call) and \
            ast.unparse(s.value.func) in ("print", "input")
        n = self.node(ast.unparse(s), "para" if is_io else "rect")
        self.link(preds, n)
        return [(n, "")]


def collect(body, prefix=""):
    """(名前, 本体, 引数文字列) のリストを返す。モジュール直下は '<main>'。"""
    out = []
    for s in body:
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = prefix + s.name
            out.append((name, s.body, f"({ast.unparse(s.args)})"))
            out += collect(s.body, name + ".")
        elif isinstance(s, ast.ClassDef):
            out += collect(s.body, prefix + s.name + ".")
    return out


def convert(source):
    tree = ast.parse(source)
    charts = []
    main = [s for s in tree.body if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    if main:
        charts.append(("<main>", Builder("main").build(main)))
    for name, body, args in collect(tree.body):
        charts.append((name + "()", Builder(name).build(body, args)))
    return charts


HTML = """<!doctype html>
<html lang="ja"><meta charset="utf-8"><title>Flowchart</title>
<style>body{{font-family:sans-serif;margin:2rem}}section{{margin-bottom:3rem}}</style>
<body>{sections}
<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
mermaid.initialize({{startOnLoad:true}});
</script></body></html>"""


def load_graphs(path):
    """.fc / .py / 無指定 から graphs を返す。"""
    if path and path.endswith(".fc"):
        with open(path, encoding="utf-8") as f:
            graphs = fcspec.parse(f.read())
        layout = {}
        if os.path.exists(path + ".layout.json"):
            with open(path + ".layout.json", encoding="utf-8") as f:
                layout = json.load(f)
        fcspec.apply_layout(graphs, layout)
        return graphs
    if path:
        with open(path, encoding="utf-8") as f:
            return [dict(c.to_graph(), name=n) for n, c in convert(f.read())]
    start = {"id": "N1", "type": "start", "text": "開始", "memo": "", "x": 0, "y": 0}
    return [{"name": "main", "nodes": [start], "edges": []}]


def write_fc(path, graphs):
    """.fc と座標ファイルを書き出す(--fc 用)。改行は常にLF(OSや編集ツールで変わると差分がずれるため)。"""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(fcspec.dump(graphs, rules=True))
    with open(path + ".layout.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(fcspec.layout_text(graphs))


SESSION_URL = re.compile(r"^/s/([A-Za-z0-9_-]{8,64})(/[a-z.]*)?$")
PAGE_URL = re.compile(r"^/s/([A-Za-z0-9_-]{8,64})/page/([A-Za-z0-9_-]{1,32})$")
API_SESSION_URL = re.compile(r"^/api/s/([A-Za-z0-9_-]{8,64})(/fc|/log)?$")
MAX_FC_BYTES = 16 * 1024 * 1024  # POST /api/new の上限(django 規模で約4MB)
MAX_SAVE_BYTES = 16 * 1024 * 1024
# 画面の見た目・動き・ロゴ(editor.css / editor.js / logo.svg)。/static/<名前> で配信する
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC_URL = re.compile(r"^/static/([A-Za-z0-9_-]+\.(css|js|svg))$")
STATIC_TYPES = {"css": "text/css", "js": "text/javascript", "svg": "image/svg+xml"}


def static_version():
    """static/ の最終更新時刻。URL に ?v= として付け、ファイルを直したらブラウザが必ず読み直すようにする。"""
    return str(max((int(os.path.getmtime(os.path.join(STATIC_DIR, f))) for f in os.listdir(STATIC_DIR)), default=0))


def serve(port, host, db_path, path=None, gate=None):
    """図エディタのサーバ。図1つ = 1セッション。URL /s/<id> で開き、内容はページ単位で SQLite に保存する。
    gate(access.Access)で、許可していない相手には白いページだけを返す。"""
    db = store.Store(db_path)
    gate = gate or access.Access()

    class Handler(BaseHTTPRequestHandler):
        def _gate(self):
            """許可していない相手(このパソコンでも --allow の範囲でもない)なら、白いページを返して False。"""
            if gate.allowed(self.client_address[0], self.headers):
                return True
            self._send(access.BLANK, "text/html", 404)
            return False

        def _send(self, body, ctype, status=200, headers=(), cache="no-store"):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache)
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _static(self, name, ext, versioned):
            path = os.path.join(STATIC_DIR, name)
            if not os.path.isfile(path):
                return self._not_found()
            with open(path, encoding="utf-8") as f:
                body = f.read()
            # ?v= 付きは中身が変わるとURLも変わるので、長くキャッシュしてよい
            self._send(body, STATIC_TYPES[ext], cache="public, max-age=31536000, immutable" if versioned else "no-cache")

        def _json(self, obj, status=200):
            self._send(json.dumps(obj, ensure_ascii=False), "application/json", status)

        def _not_found(self):
            self._send(NOT_FOUND, "text/html", 404)

        def _body(self, limit):
            length = int(self.headers.get("Content-Length", 0))
            if length > limit:
                raise ValueError(f"送られた内容が大きすぎます(上限 {limit // 1024 // 1024}MB)")
            return self.rfile.read(length).decode("utf-8")

        def _base(self):
            """外から見たこのサーバのURL(リバースプロキシの後ろでも正しくなるよう、転送ヘッダを優先)。"""
            proto = self.headers.get("X-Forwarded-Proto", "http")
            host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or f"127.0.0.1:{port}"
            return f"{proto}://{host}"

        def _links(self, sid):
            base = self._base()
            return {"url": f"{base}/s/{sid}", "api": f"{base}/api/s/{sid}", "fc": f"{base}/api/s/{sid}/fc",
                    "log": f"{base}/api/s/{sid}/log"}

        def _mcp(self):
            """MCP の Streamable HTTP。JSON-RPC を受け取り、応答を JSON 1つで返す(SSE は使わない)。"""
            # ブラウザ経由の悪用(DNS rebinding)を防ぐため、別サイトのページからの呼び出しは断る(MCP仕様の要求)
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc != (self.headers.get("X-Forwarded-Host") or self.headers.get("Host")):
                return self._json({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Origin not allowed"}}, 403)
            try:
                msg = json.loads(self._body(MAX_FC_BYTES))
            except (ValueError, UnicodeDecodeError):
                return self._json({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, 400)
            links = self._links
            if isinstance(msg, list):  # 古いクライアントのまとめ送り
                out = [r for r in (mcp_server.handle(m, db, links) for m in msg) if r is not None]
            else:
                out = mcp_server.handle(msg, db, links)
            if not out:  # 通知だけなら本文なし
                return self._send("", "text/plain", 202)
            self._json(out)

        def _created(self, sid):
            return {"id": sid, **self._links(sid), "download": f"{self._base()}/s/{sid}/download.fc"}

        def _read_api(self, sid, sub, query):
            """AI用の読み取り。?page=名前 で1ページだけに絞れる(読む量を減らすため)。"""
            if sub == "/log":
                text = db.history_text(sid)
                return self._send(text, "text/plain") if text else self._json({"error": "この図はサーバにありません"}, 404)
            info = db.info(sid)
            if not info:
                return self._json({"error": "この図はサーバにありません"}, 404)
            page = (parse_qs(query).get("page") or [None])[0]
            if page is not None and not any(p["name"] == page for p in info["pages"]):
                return self._json({"error": f"ページがありません: {page}", "pages": [p["name"] for p in info["pages"]]}, 404)
            if sub == "/fc":
                return self._send(db.fc_text(sid, page), "text/plain")
            head = {"id": sid, "name": info["name"], **self._links(sid)}
            if page is None:  # 一覧だけ(ページが多くても軽い)。中身は ?page= か /fc で読む
                return self._json({**head, "pages": [{"name": p["name"], "node_count": p["nodes"], "rev": p["rev"]}
                                                     for p in info["pages"]], "rules": fcspec.RULES})
            graphs = db.graphs(sid, page)
            rev = next(p["rev"] for p in info["pages"] if p["name"] == page)
            self._json({**head, "pages": [{"name": g["name"], "rev": rev,
                                           "nodes": [{k: n[k] for k in ("id", "type", "text", "memo")} for n in g["nodes"]],
                                           "edges": [{k: e[k] for k in ("from", "to", "label", "memo")} for e in g["edges"]]}
                                          for g in graphs],
                        "issues": fcspec.validate(graphs), "rules": fcspec.RULES})

        def do_GET(self):
            url = urlsplit(self.path)
            if not self._gate():
                return
            if url.path == "/":  # 説明ページ(人には作成ボタン、AIには作成・読み取りの手順とAPI一覧)
                return self._send(render_landing(self._base()), "text/html")
            m = STATIC_URL.match(url.path)
            if m:
                return self._static(m.group(1), m.group(2), "v=" in url.query)
            if url.path == "/mcp":  # MCP は POST だけ(サーバからの通知の流れ=SSE は使わない)
                return self._send("MCP: POST で JSON-RPC を送ってください", "text/plain", 405, [("Allow", "POST")])
            if url.path in ("/api", "/api/"):  # API一覧(JSON)
                return self._json({"apis": [{"method": m, "path": p, "description": d}
                                            for m, p, d, _ in landing_page.APIS]})
            m = API_SESSION_URL.match(url.path)
            if m:
                return self._read_api(m.group(1), m.group(2) or "", url.query)
            m = PAGE_URL.match(url.path)
            if m:  # エディタが開いたページの中身を読む
                p = db.page(m.group(1), m.group(2))
                return self._json(p) if p else self._json({"error": "このページはサーバにありません"}, 404)
            m = SESSION_URL.match(url.path)
            if not m:
                return self._not_found()
            sid, sub = m.group(1), m.group(2) or ""
            if sub in ("", "/"):
                # 開くたびにDBから読む。最初はページの一覧と先頭ページの中身だけ(ほかのページは開いたときに読む)
                info = db.info(sid)
                if not info:
                    return self._not_found()
                info["first"] = db.page(sid, info["pages"][0]["pid"]) if info["pages"] else None
                init = json.dumps(info, ensure_ascii=False).replace("</", "<\\/")
                links = self._links(sid)  # AIがエディタのURLを開いたときの案内(読み取り用APIの場所)
                page = (PAGE.replace("__FC_URL__", html.escape(links["fc"])).replace("__API_URL__", html.escape(links["api"]))
                        .replace("__V__", static_version()))
                return self._send(page.replace("__INIT__", init), "text/html")
            if sub == "/download.fc":
                info = db.info(sid)
                if not info:
                    return self._not_found()
                disp = "attachment; filename*=UTF-8''" + quote(info["name"])
                return self._send(db.fc_text(sid), "text/plain", headers=[("Content-Disposition", disp)])
            if sub == "/log":
                text = db.history_text(sid)
                return self._send(text, "text/plain") if text else self._not_found()
            self._not_found()

        def do_POST(self):
            url = urlsplit(self.path)
            if not self._gate():
                return
            if url.path == "/new":  # 「新しい図を作る」ボタン。空の図を作ってエディタへ移動する
                sid = db.create(load_graphs(None))
                return self._send("", "text/plain", 303, [("Location", f"/s/{sid}")])
            if url.path == "/api/new":  # AI用: 本文の .fc から図を作り、URLと検査結果を返す
                try:
                    sid, graphs = db.create_from_fc(self._body(MAX_FC_BYTES), (parse_qs(url.query).get("name") or ["無題"])[0])
                except (ValueError, UnicodeDecodeError) as e:
                    return self._json({"error": f"{e}"}, 400)
                return self._json({**self._created(sid), "issues": fcspec.validate(graphs)}, 201)
            if url.path == "/mcp":  # MCP(Streamable HTTP)。AIクライアントが図を読み書きする
                return self._mcp()
            m = SESSION_URL.match(url.path)
            if not m:
                return self._not_found()
            sid, sub = m.group(1), m.group(2)
            try:
                body = json.loads(self._body(MAX_SAVE_BYTES))
                if sub == "/settings":
                    return self._json({"settings": db.set_settings(sid, body)})
                if sub != "/save":
                    return self._not_found()
                # 変わったページだけが届く。手動保存(check_all)のときは全ページを検査する
                revs, changes, saved = db.save(sid, body["ops"])
                checked = db.graphs(sid) if body.get("check_all") else saved
                res = {"revs": revs, "changes": changes, "issues": fcspec.validate(checked)}
            except store.Conflict as e:
                names = e.args[0]
                res = {"error": "別の画面で先に保存されています: " + "、".join(names[:5]) + (" ほか" if len(names) > 5 else ""),
                       "conflict": True}
            except KeyError:
                res = {"error": "この図はサーバにありません"}
            except Exception as e:  # 書き込み失敗など。画面にエラーを返す
                res = {"error": f"{type(e).__name__}: {e}"}
            self._json(res)

        def log_message(self, *args):
            pass

    first = "/"
    if path:  # 指定したファイルを取り込んで、新しいセッションとして開く
        first = f"/s/{db.create(load_graphs(path), os.path.splitext(os.path.basename(path))[0] + '.fc')}"
    ThreadingHTTPServer.request_queue_size = 128  # 標準は5件。同時に多く来ると接続を断ってしまうため広げる
    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}{first}"
    print(f"起動しました: {url}  DB: {os.path.abspath(db_path)}  (Ctrl+Cで終了)")
    print(f"アクセス: {gate.describe()}")
    if host in ("127.0.0.1", "localhost"):  # 手元で使うときだけブラウザを開く
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def render_landing(base):
    rows = "".join(f"<tr><td><code>{m}</code></td><td><code>{html.escape(p)}</code></td><td>{html.escape(d)}</td>"
                   f"<td>{html.escape(r)}</td></tr>" for m, p, d, r in landing_page.APIS)
    out = landing_page.PAGE.replace("__API_ROWS__", rows)
    rep = {"__BASE__": base, "__MAX__": str(MAX_FC_BYTES // 1024 // 1024), "__RULES__": fcspec.RULES,
           "__EXAMPLE__": landing_page.EXAMPLE.rstrip()}
    for k, v in rep.items():
        out = out.replace(k, html.escape(v, quote=True))
    return out


NOT_FOUND = """<!doctype html><html lang="ja"><meta charset="utf-8"><title>見つかりません - Zuplan</title>
<body style="font-family:sans-serif;margin:3rem;color:#1f2937">
<h2>この図は見つかりません</h2><p>URLが間違っているか、図が削除されています。</p>
<p><a href="/">トップページへ(新しい図を作る)</a></p></body></html>"""


OUT_DIR = "out"  # --fc / --html の出力先(ファイル名だけ指定したとき)
DEFAULT_DB = os.path.join("data", "flowchart.db")
LEGACY_DB = "flowchart.db"  # 以前の置き場所(プロジェクト直下)


def out_path(path):
    """ファイル名だけなら out/ に入れる(生成物をソースと混ぜないため)。フォルダ付きならそのまま。"""
    if not os.path.dirname(path):
        path = os.path.join(OUT_DIR, path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def prepare_db(path):
    """DBの置き場所を用意する。既定の場所が空で、以前の場所に flowchart.db があれば移す。"""
    if path == DEFAULT_DB and not os.path.exists(path) and os.path.exists(LEGACY_DB):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(LEGACY_DB + ext):
                os.replace(LEGACY_DB + ext, path + ext)
        print(f"DBを移しました: {LEGACY_DB} → {path}")
    if os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", nargs="?", help=".fc(図の仕様)または .py(取り込み)")
    ap.add_argument("--html", nargs="?", const="", metavar="出力.html",
                    help="Mermaid表示のHTMLとして出力(省略時は out/<入力名>.html)")
    ap.add_argument("--fc", nargs="?", const="", metavar="出力.fc",
                    help="Pythonコードを .fc に変換して出力(省略時は out/<入力名>.fc)")
    ap.add_argument("--serve", action="store_true", help="図エディタのサーバを起動(file を指定すると取り込んで開く)")
    ap.add_argument("--diff", metavar="新.fc", help="file(旧)と新.fc の意味的な差分を表示")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1", help="ほかのパソコンから使うときは 0.0.0.0(--allow も必要)")
    ap.add_argument("--db", default=DEFAULT_DB, help=f"セッションを保存する SQLite ファイル(既定 {DEFAULT_DB})")
    ap.add_argument("--allow", action="append", metavar="IPの範囲",
                    help="このパソコン以外で使ってよいIP(例: 192.168.1.0/24。カンマ区切り・複数回可)。"
                         "家庭・社内のネットワークの範囲だけ指定できる。それ以外には白いページを返す")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if a.diff and a.file:
        with open(a.file, encoding="utf-8") as f1, open(a.diff, encoding="utf-8") as f2:
            print("\n".join(fcspec.diff(fcspec.parse(f1.read()), fcspec.parse(f2.read()))) or "差分なし")
        return
    if a.serve:
        try:
            gate = access.Access(access.parse_allow(a.allow))
        except ValueError as e:
            ap.error(str(e))
        return serve(a.port, a.host, prepare_db(a.db), a.file, gate)
    if not a.file:
        ap.error("ファイルを指定するか --serve を使ってください")
    stem = os.path.splitext(os.path.basename(a.file))[0]
    if a.fc is not None:
        path = out_path(a.fc or stem + ".fc")
        write_fc(path, load_graphs(a.file))
        print(f"出力しました: {path}")
        return
    with open(a.file, encoding="utf-8") as f:
        charts = convert(f.read())
    if a.html is not None:
        secs = "".join(
            f'<section><h2>{html.escape(n)}</h2><pre class="mermaid">{html.escape(c.to_mermaid())}</pre></section>'
            for n, c in charts
        )
        path = out_path(a.html or stem + ".html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(HTML.format(sections=secs))
        print(f"出力しました: {path}")
    else:
        for n, c in charts:
            print(f"%% {n}\n{c.to_mermaid()}\n")


if __name__ == "__main__":
    sys.exit(main())
