"""MCP(Model Context Protocol)サーバ。Claude Code などのAIクライアントが、Zuplan の図を読み書きするための道具を提供する。

サーバの POST /mcp(Streamable HTTP。応答は JSON 1つ)で動く。外部ライブラリは使わず、JSON-RPC 2.0 を直接扱う。
Claude Code への登録例:  claude mcp add --transport http zuplan http://127.0.0.1:8000/mcp
"""
import json
import re
import fcspec
import store

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")  # 新しい順
SERVER_INFO = {"name": "zuplan", "title": "Zuplan", "version": "0.1.0"}
INSTRUCTIONS = (
    "Zuplan は、プログラムの仕様をフローチャート(.fc 形式)で描き、AIがそれを読んで実装するためのツール。"
    "図はページ(関数・処理の単位)の集まり。実装するときは read_fc で読み、図に無い仕様は足さず、曖昧ならユーザーに質問する。"
    "ページが多い図は list_pages で一覧を見てから、read_fc の page で必要なページだけ読む。"
    "図を直すときは write_pages を使う(ユーザーがそのページを編集中だと、ユーザーの画面は再読み込みが必要になる)。\n\n" + fcspec.RULES)

_DIAGRAM = {"type": "string", "description": "図のID、または図のURL(…/s/<ID>)"}
_PAGE = {"type": "string", "description": "ページ名(省略すると全ページ)"}
TOOLS = [
    {"name": "list_pages", "title": "ページ一覧",
     "description": "図のページ一覧(名前・図形数・版番号)と、図のURLを返す。ページが多い図はまずこれで全体を見る。",
     "inputSchema": {"type": "object", "properties": {"diagram": _DIAGRAM}, "required": ["diagram"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "read_fc", "title": "図を読む",
     "description": "図を .fc テキスト(先頭に読み方ルール)で返す。実装するときはこれを読む。page で1ページだけに絞れる。",
     "inputSchema": {"type": "object", "properties": {"diagram": _DIAGRAM, "page": _PAGE}, "required": ["diagram"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "validate", "title": "図を検査する",
     "description": "開始が1つか、分岐にラベルがあるか、行き止まりが無いか などを検査し、問題の一覧を返す。",
     "inputSchema": {"type": "object", "properties": {"diagram": _DIAGRAM, "page": _PAGE}, "required": ["diagram"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "read_log", "title": "変更履歴",
     "description": "図の変更履歴(保存ごとの意味的な差分)を返す。前回読んだあとにユーザーが何を直したかが分かる。",
     "inputSchema": {"type": "object", "properties": {"diagram": _DIAGRAM}, "required": ["diagram"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "create_diagram", "title": "新しい図を作る",
     "description": ".fc テキストから新しい図を作り、URL(ユーザーに伝える)と検査結果を返す。座標は自動配置。",
     "inputSchema": {"type": "object", "properties": {
         "fc": {"type": "string", "description": ".fc 形式の本文(`## ページ名` で始まるページを1つ以上)"},
         "name": {"type": "string", "description": "図の名前(省略可)"}}, "required": ["fc"]},
     "annotations": {"readOnlyHint": False, "destructiveHint": False}},
    {"name": "write_pages", "title": "ページを書き込む",
     "description": "fc に書いたページを、同じ名前のページに上書きする(無ければ末尾に追加)。delete に書いたページは削除する。"
                    "図形の id が前と同じなら座標を引き継ぐ。書いたページの検査結果と変更点を返す。",
     "inputSchema": {"type": "object", "properties": {
         "diagram": _DIAGRAM,
         "fc": {"type": "string", "description": "上書き・追加するページ(.fc 形式。`## ページ名` から)。削除だけなら省略可"},
         "delete": {"type": "array", "items": {"type": "string"}, "description": "削除するページ名"}},
         "required": ["diagram"]},
     "annotations": {"readOnlyHint": False, "destructiveHint": True}},
]


class ToolError(Exception):
    """AIに伝える失敗(isError: true の結果になる)。"""


def _sid(diagram):
    m = re.search(r"/s/([A-Za-z0-9_-]{8,64})", str(diagram or "")) or re.fullmatch(r"([A-Za-z0-9_-]{8,64})", str(diagram or "").strip())
    if not m:
        raise ToolError("diagram には図のID、または図のURL(…/s/<ID>)を指定してください")
    return m.group(1)


def _text(obj):
    return obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1)


def call_tool(name, args, db, links):
    """links(sid) は図のURL類を返す関数(サーバが外から見たURLで作る)。"""
    if name == "create_diagram":
        try:
            sid, graphs = db.create_from_fc(args.get("fc", ""), args.get("name") or "無題")
        except ValueError as e:
            raise ToolError(f".fc を読めませんでした: {e}")
        return {"id": sid, **links(sid), "issues": fcspec.validate(graphs),
                "note": "url をユーザーに伝えてください。ユーザーはそのURLで図を見ながら直せます。"}
    sid = _sid(args.get("diagram"))
    info = db.info(sid)
    if not info:
        raise ToolError("この図はサーバにありません")
    page = args.get("page") or None
    if page is not None and not any(p["name"] == page for p in info["pages"]):
        raise ToolError(f"ページがありません: {page}。ある名前: " + ", ".join(p["name"] for p in info["pages"][:50]))
    if name == "list_pages":
        return {"id": sid, "name": info["name"], **links(sid),
                "pages": [{"name": p["name"], "node_count": p["nodes"], "rev": p["rev"]} for p in info["pages"]]}
    if name == "read_fc":
        return db.fc_text(sid, page)
    if name == "validate":
        issues = fcspec.validate(db.graphs(sid, page))
        return {"issues": issues} if issues else "問題は見つかりませんでした"
    if name == "read_log":
        return db.history_text(sid)
    if name == "write_pages":
        delete = [str(d) for d in args.get("delete") or []]
        if not (args.get("fc") or "").strip() and not delete:
            raise ToolError("fc か delete のどちらかを指定してください")
        try:
            changes, saved = db.write_pages(sid, args.get("fc") or "", delete)
        except store.Conflict as e:
            raise ToolError("ちょうど同じページが別の画面で保存されました。read_fc で読み直してから、もう一度書いてください: "
                            + ", ".join(e.args[0]))
        except ValueError as e:
            raise ToolError(str(e))
        return {"changes": changes or ["(変更なし)"], "issues": fcspec.validate(saved), **links(sid)}
    raise ToolError(f"不明な道具です: {name}")


def _error(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def handle(msg, db, links):
    """JSON-RPC のメッセージ1つを処理して応答を返す。通知(id なし)には None を返す。"""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
    if "id" not in msg:
        return None  # notifications/initialized など
    mid, method, params = msg["id"], msg["method"], msg.get("params") or {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        result = {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                  "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if not any(t["name"] == name for t in TOOLS):
            return _error(mid, -32602, f"Unknown tool: {name}")
        try:
            out, is_error = call_tool(name, args, db, links), False
        except ToolError as e:
            out, is_error = str(e), True
        result = {"content": [{"type": "text", "text": _text(out)}], "isError": is_error}
        if isinstance(out, dict) and not is_error:
            result["structuredContent"] = out
    else:
        return _error(mid, -32601, f"Method not found: {method}")
    return {"jsonrpc": "2.0", "id": mid, "result": result}
