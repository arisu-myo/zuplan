"""セッション(図1つ)を SQLite に保存する。図はページ単位で1行ずつ持つ(大きなプロジェクトでも、保存は変わったページだけで済むように)。

ページは名前を変えても変わらない pid で区別し、ページごとの rev(版番号)で、古い画面からの上書きを防ぐ。
別のページを編集している人どうしは衝突しない。
"""
import contextlib
import json
import re
import secrets
import sqlite3
import threading
import time
import fcspec

DEFAULT_SETTINGS = {"autosave": True}
SCHEMA_VERSION = 2
PID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS sessions (
  id       TEXT PRIMARY KEY,        -- URL に付く推測できないID
  name     TEXT NOT NULL,           -- 表示名・ダウンロード時のファイル名
  settings TEXT NOT NULL,           -- 自動保存のオン/オフなど(JSON)
  created  TEXT NOT NULL,
  updated  TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS pages (
  session_id TEXT NOT NULL REFERENCES sessions(id),
  pid        TEXT NOT NULL,         -- ページID(名前を変えても変わらない)
  pos        INTEGER NOT NULL,      -- 並び順
  name       TEXT NOT NULL,
  body       TEXT NOT NULL,         -- .fc のページ本文(`## 名前` 行を除く)
  layout     TEXT NOT NULL,         -- 座標 {図形id: [x, y]}
  nodes      INTEGER NOT NULL,      -- 図形数(ページ一覧用)
  rev        INTEGER NOT NULL,      -- 保存のたびに+1
  updated    TEXT NOT NULL,
  PRIMARY KEY (session_id, pid),
  UNIQUE (session_id, name))""",
    "CREATE INDEX IF NOT EXISTS pages_order ON pages(session_id, pos)",
    """CREATE TABLE IF NOT EXISTS history (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  at         TEXT NOT NULL,
  changes    TEXT NOT NULL)          -- 意味的な差分(1行1件)""",
    "CREATE INDEX IF NOT EXISTS history_session ON history(session_id, id)",
]


class Conflict(Exception):
    """別の画面が先に、同じページを保存(または削除)していた。args[0] はページ名の一覧。"""


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def new_pid():
    return secrets.token_urlsafe(8)


def _one_line(s):
    return " ".join(str(s or "").split())


def clean_page(p):
    """画面から届いたページを、.fc に書ける形に整える(改行が入ると1行1要素の形式が壊れるため)。"""
    name = _one_line(p.get("name"))
    if not name:
        raise ValueError("ページ名が空です")
    nodes = []
    for n in p.get("nodes", []):
        nid = str(n["id"]).strip()
        if not nid or any(c.isspace() for c in nid) or ">" in nid:
            raise ValueError(f"[{name}] 図形のidが不正です: {nid!r}")
        if n["type"] not in fcspec.TYPES:
            raise ValueError(f"[{name}] 図形の種別が不明です: {n['type']}")
        nodes.append({"id": nid, "type": n["type"], "text": _one_line(n.get("text")), "memo": str(n.get("memo") or ""),
                      "x": round(float(n.get("x", 0))), "y": round(float(n.get("y", 0)))})
    edges = [{"from": str(e["from"]), "to": str(e["to"]), "label": _one_line(e.get("label")), "memo": str(e.get("memo") or "")}
             for e in p.get("edges", [])]
    return {"name": name, "nodes": nodes, "edges": edges}


def _row_values(g):
    return ("\n".join(fcspec.page_lines(g)), json.dumps({n["id"]: [n["x"], n["y"]] for n in g["nodes"]}), len(g["nodes"]))


def _graph(row, with_layout=True):
    g = fcspec.parse_page(row["name"], row["body"])
    if with_layout:
        pos = json.loads(row["layout"])
        if g["nodes"] and all(n["id"] in pos for n in g["nodes"]):
            for n in g["nodes"]:
                n["x"], n["y"] = pos[n["id"]]
        else:
            fcspec.autolayout(g)
    return g


class Store:
    def __init__(self, path):
        self.path = path
        # 書き込みはこのプロセスの中で1つずつ順番に行う。SQLite は同時に1件しか書けず、
        # DB側で待たせると(Windows では)約1秒単位で待つため、10人同時の保存が1件1秒になっていた
        self._write = threading.Lock()
        with self._db() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
                return
            old = "fc" in [r[1] for r in db.execute("PRAGMA table_info(sessions)")]
        if old:  # 形を変える前に、元のDBを残しておく(<db>.v1.bak)
            with contextlib.closing(sqlite3.connect(path)) as src, contextlib.closing(sqlite3.connect(path + ".v1.bak")) as dst:
                src.backup(dst)
        with self._db() as db:
            self._migrate(db)

    @contextlib.contextmanager
    def _db(self, write=False):
        # リクエストごとに接続する(サーバはスレッドで並行に動くため)。正常終了ならコミット、例外ならロールバック
        with self._write if write else contextlib.nullcontext():
            db = sqlite3.connect(self.path, timeout=10)
            try:
                db.execute("PRAGMA journal_mode=WAL")
                db.row_factory = sqlite3.Row
                with db:
                    yield db
            finally:
                db.close()

    def _migrate(self, db):
        """版1(図全体を sessions.fc に1つで保存)から、ページごとの保存へ移す。"""
        cols = [r[1] for r in db.execute("PRAGMA table_info(sessions)")]
        if "fc" in cols:
            # 新しい形の表を別名で作って移し、古い表と入れ替える(history からの参照名 sessions を保つため)
            old = db.execute("SELECT * FROM sessions").fetchall()
            db.execute(SCHEMA[0].replace("IF NOT EXISTS sessions", "sessions_new"))
            db.executemany("INSERT INTO sessions_new VALUES (?,?,?,?,?)",
                           [(r["id"], r["name"], r["settings"], r["created"], r["updated"]) for r in old])
            db.execute("DROP TABLE sessions")
            db.execute("ALTER TABLE sessions_new RENAME TO sessions")
        else:
            old = []
        for sql in SCHEMA:
            db.execute(sql)
        for r in old:
            graphs = fcspec.parse(r["fc"])
            fcspec.apply_layout(graphs, json.loads(r["layout"]))
            self._insert_pages(db, r["id"], graphs, r["updated"])
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _insert_pages(self, db, sid, graphs, now):
        seen = set()
        for g in graphs:  # 重複したページ名には番号を付けて一意にする(版1のDBやコード取り込みでは重複しうる)
            base, k = g["name"], 2
            while g["name"] in seen:
                g["name"], k = f"{base} {k}", k + 1
            seen.add(g["name"])
        db.executemany("INSERT INTO pages VALUES (?,?,?,?,?,?,?,1,?)",
                       [(sid, new_pid(), i, g["name"], *_row_values(g), now) for i, g in enumerate(graphs)])

    def create(self, graphs, name="無題.fc"):
        """graphs は座標付き。"""
        sid = secrets.token_urlsafe(12)
        now = _now()
        with self._db(write=True) as db:
            db.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", (sid, name, json.dumps(DEFAULT_SETTINGS), now, now))
            self._insert_pages(db, sid, graphs, now)
            db.execute("INSERT INTO history (session_id, at, changes) VALUES (?,?,?)",
                       (sid, now, f"+ 新規作成 (ページ{len(graphs)})"))
        return sid

    def create_from_fc(self, text, name="無題"):
        """.fc テキストから新しい図を作る(POST /api/new と MCP の create_diagram で使う)。(sid, graphs) を返す。"""
        graphs = fcspec.parse(text)
        if not graphs:
            raise ValueError("ページ(## 名前)が1つもありません")
        names = [g["name"] for g in graphs]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise ValueError("ページ名が重複しています: " + ", ".join(dup[:10]))
        fcspec.apply_layout(graphs, {})  # 座標は自動配置
        name = _one_line(name)[:80] or "無題"
        return self.create(graphs, name if name.endswith(".fc") else name + ".fc"), graphs

    def write_pages(self, sid, text, delete=()):
        """.fc テキストに書かれたページを、名前で上書き(無ければ末尾に追加)する。delete のページは消す。
        図形の id がすべて前と同じページは座標を引き継ぎ、そうでなければ自動配置し直す。(変更点, 書いたページ) を返す。"""
        graphs = fcspec.parse(text) if text and text.strip() else []
        names = [g["name"] for g in graphs]
        if len(set(names)) < len(names):
            raise ValueError("ページ名が重複しています")
        info = self.info(sid)
        if not info:
            raise KeyError(sid)
        by_name = {p["name"]: p for p in info["pages"]}
        missing = [n for n in delete if n not in by_name]
        if missing:
            raise ValueError("ページがありません: " + ", ".join(missing))
        if len(set(delete)) >= len(by_name) and not any(g["name"] not in by_name for g in graphs):
            raise ValueError("すべてのページは削除できません(図には1ページ以上必要です)")
        ops, last = [], info["pages"][-1]["pid"] if info["pages"] else None
        for n in delete:
            ops.append({"op": "del", "pid": by_name[n]["pid"], "rev": by_name[n]["rev"]})
        for g in graphs:
            old = by_name.get(g["name"])
            pos = {}
            if old:
                cur = self.page(sid, old["pid"])
                pos = {n["id"]: (n["x"], n["y"]) for n in cur["nodes"]} if cur else {}
            if g["nodes"] and all(n["id"] in pos for n in g["nodes"]):
                for n in g["nodes"]:
                    n["x"], n["y"] = pos[n["id"]]
            else:
                fcspec.autolayout(g)
            if old:
                ops.append({"op": "put", "pid": old["pid"], "rev": old["rev"], **g})
            else:
                pid = new_pid()
                ops.append({"op": "put", "pid": pid, "rev": None, "after": last, **g})
                last = pid
        _, changes, saved = self.save(sid, ops)
        return changes, saved

    def info(self, sid):
        """{id, name, settings, pages: [{pid, name, rev, nodes}]}(ページは中身なしの一覧)。無ければ None。"""
        with self._db() as db:
            s = db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
            if not s:
                return None
            rows = db.execute("SELECT pid, name, rev, nodes FROM pages WHERE session_id=? ORDER BY pos", (sid,)).fetchall()
        return {"id": sid, "name": s["name"], "settings": {**DEFAULT_SETTINGS, **json.loads(s["settings"])},
                "pages": [dict(r) for r in rows]}

    def page(self, sid, pid):
        """1ページ分(座標付き)。{pid, name, rev, nodes, edges}。無ければ None。"""
        with self._db() as db:
            r = db.execute("SELECT * FROM pages WHERE session_id=? AND pid=?", (sid, pid)).fetchone()
        return r and {"pid": pid, "rev": r["rev"], **_graph(r)}

    def graphs(self, sid, page=None, layout=False):
        """全ページ(または名前が page の1ページ)を parse 結果で返す。"""
        sql, args = "SELECT * FROM pages WHERE session_id=?", [sid]
        if page is not None:
            sql, args = sql + " AND name=?", args + [page]
        with self._db() as db:
            rows = db.execute(sql + " ORDER BY pos", args).fetchall()
        return [_graph(r, layout) for r in rows]

    def fc_text(self, sid, page=None):
        """.fc テキスト(読み方ルール付き)。ページ本文をそのままつなぐので、ページが多くても速い。"""
        sql, args = "SELECT name, body FROM pages WHERE session_id=?", [sid]
        if page is not None:
            sql, args = sql + " AND name=?", args + [page]
        with self._db() as db:
            rows = db.execute(sql + " ORDER BY pos", args).fetchall()
        out = fcspec.header(rules=True)
        for r in rows:
            out.append(f"## {r['name']}")
            if r["body"]:
                out.append(r["body"])
        return "\n".join(out) + "\n"

    def save(self, sid, ops):
        """画面からの変更(変わったページだけ)をまとめて保存する。すべて成功するか、何も変えないかのどちらか。

        ops は先頭から順に適用する:
          {"op": "put", "pid", "rev"(新規は null), "after"(新規のみ。直前のページのpid。null なら先頭), "name", "nodes", "edges"}
          {"op": "del", "pid", "rev"}
          {"op": "move", "pid", "after"}
        戻り値: ({pid: 新しいrev}, 変更点, 保存したページ)。同じページが別の画面で先に変わっていたら Conflict。
        """
        now = _now()
        with self._db(write=True) as db:
            if not db.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone():
                raise KeyError(sid)
            # 本文は保存・削除するページの分だけ読む(ページが多くても速いように)
            touched = list({str(op.get("pid", "")) for op in ops if op.get("op") in ("put", "del")})
            rows = {}
            for k in range(0, len(touched), 500):
                part = touched[k:k + 500]
                rows.update((r["pid"], r) for r in db.execute(
                    f"SELECT * FROM pages WHERE session_id=? AND pid IN ({','.join('?' * len(part))})", (sid, *part)))
            # 並び順(全ページのIDと位置)は、追加・削除・移動があるときだけ読む。
            # 中身を直しただけの保存(自動保存のほとんど)では読まない(1万ページで保存1回の6割を占めていたため)
            reorder = any(op.get("op") in ("del", "move") or (op.get("op") == "put" and str(op.get("pid")) not in rows)
                          for op in ops)
            pos = dict(db.execute("SELECT pid, pos FROM pages WHERE session_id=?", (sid,)).fetchall()) if reorder else {}
            order = sorted(pos, key=pos.get)
            changes, revs, saved, conflicts, puts = [], {}, [], [], []

            def place(pid, after):
                if pid in order:
                    order.remove(pid)
                order.insert(order.index(after) + 1 if after in order else (0 if after is None else len(order)), pid)

            for op in ops:
                pid = str(op.get("pid", ""))
                if not PID.match(pid):
                    raise ValueError(f"ページIDが不正です: {pid!r}")
                old = rows.get(pid)
                kind = op.get("op")
                if kind == "put":
                    g = clean_page(op)
                    if old is None and op.get("rev") is not None:  # 編集中に、別の画面で削除された
                        conflicts.append(g["name"])
                    elif old is not None and old["rev"] != op.get("rev"):
                        conflicts.append(old["name"])
                    else:
                        puts.append((pid, old, g))
                        if old is None:
                            place(pid, op.get("after"))
                elif kind == "del":
                    if old is None:
                        continue  # すでに削除されている
                    if old["rev"] != op.get("rev"):
                        conflicts.append(old["name"])
                        continue
                    db.execute("DELETE FROM pages WHERE session_id=? AND pid=?", (sid, pid))
                    changes.append(f"- ページ {old['name']}")
                    order.remove(pid)
                    del rows[pid]
                elif kind == "move":
                    if pid in order:
                        place(pid, op.get("after"))
                else:
                    raise ValueError(f"不明な操作です: {kind!r}")
            if conflicts:
                raise Conflict(conflicts)

            # 名前の入れ替え(A→B, B→A)でも一意制約に当たらないよう、名前の変わるページは先に仮の名前にする
            for pid, old, g in puts:
                if old is not None and old["name"] != g["name"]:
                    db.execute("UPDATE pages SET name=? WHERE session_id=? AND pid=?", ("\x00" + pid, sid, pid))
            for pid, old, g in puts:
                body, layout, count = _row_values(g)
                try:
                    if old is None:
                        db.execute("INSERT INTO pages VALUES (?,?,?,?,?,?,?,1,?)", (sid, pid, -1, g["name"], body, layout, count, now))
                        changes += fcspec.diff([], [g])
                        revs[pid] = 1
                    else:
                        db.execute("UPDATE pages SET name=?, body=?, layout=?, nodes=?, rev=rev+1, updated=? WHERE session_id=? AND pid=?",
                                   (g["name"], body, layout, count, now, sid, pid))
                        before = _graph(old, with_layout=False)
                        if before["name"] != g["name"]:
                            changes.append(f"~ ページ名: {before['name']} → {g['name']}")
                            before["name"] = g["name"]
                        changes += fcspec.diff([before], [g])
                        revs[pid] = old["rev"] + 1
                except sqlite3.IntegrityError:
                    raise ValueError(f"ページ名が重複しています: {g['name']}")
                saved.append(g)
            # 並び順が変わったページだけ pos を書き直す
            db.executemany("UPDATE pages SET pos=? WHERE session_id=? AND pid=?",
                           [(i, sid, p) for i, p in enumerate(order) if pos.get(p) != i])
            db.execute("UPDATE sessions SET updated=? WHERE id=?", (now, sid))
            if changes:
                db.execute("INSERT INTO history (session_id, at, changes) VALUES (?,?,?)", (sid, now, "\n".join(changes)))
        return revs, changes, saved

    def set_settings(self, sid, changes):
        with self._db(write=True) as db:
            row = db.execute("SELECT settings FROM sessions WHERE id=?", (sid,)).fetchone()
            if not row:
                raise KeyError(sid)
            settings = {**DEFAULT_SETTINGS, **json.loads(row["settings"])}
            settings.update({k: v for k, v in changes.items() if k in DEFAULT_SETTINGS})
            db.execute("UPDATE sessions SET settings=? WHERE id=?", (json.dumps(settings), sid))
        return settings

    def history_text(self, sid):
        """旧 .fc.log と同じ形式の変更履歴。"""
        with self._db() as db:
            rows = db.execute("SELECT at, changes FROM history WHERE session_id=? ORDER BY id", (sid,)).fetchall()
        return "".join(f"## {r['at']}\n{r['changes']}\n" for r in rows)
