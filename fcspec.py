"""図の仕様ファイル(.fc)の読み書き・検査・自動配置。

形式(トークン節約のため1行1要素):
    fc1
    ## 名前          ← ページ(関数・処理の単位)
    a start 開始     ← ノード: id 種別 テキスト
    ; メモ           ← 直前のノード/矢印へのメモ(複数行可)
    a>b ラベル       ← 矢印: 元>先 [ラベル]
座標は .fc には書かず、横の .layout.json に保存する(AIが読む量を増やさないため)。
"""
import json
import re
import sys

TYPES = ("start", "end", "proc", "if", "io", "loop", "call", "screen", "data", "db", "note")
SIDE = {"data", "db", "note"}  # フローの順序には入らない補助図形
DEFAULT_TEXT = {"start": "開始", "end": "終了", "proc": "処理", "if": "条件?", "io": "入出力",
                "loop": "繰り返し", "call": "呼出", "screen": "画面", "data": "データ", "db": "DB", "note": "メモ"}

RULES = """[fc形式の読み方] 図=プログラムのフロー仕様。これに従って実装する。
`## 名前`=関数/処理単位(別ページ)。`id 種別 テキスト`=図形。`a>b ラベル`=遷移。`;`行=直前の行のメモ。
種別: start end proc(処理) if(判断。出る矢印のラベル=分岐条件) io(入出力) loop(出る矢印 次/完了) call(別##の呼出。テキストにページ名を含める) screen(画面) data(データ) db(DB) note(補足。実装対象外)
data/db/note に繋がる矢印は読み書きなどの関係で、実行順ではない。図に無い仕様は足さず、曖昧なら質問する。"""

_EDGE = re.compile(r"^(\S+)>(\S+)(?:\s+(.*))?$")


def header(rules=False):
    """rules=True なら先頭に読み方ルールを `;` 行で入れる(単体で配るファイル用)。"""
    return ["fc1"] + ([f"; {r}" for r in RULES.splitlines()] if rules else [])


def page_lines(g):
    """1ページ分の本文(`## 名前` 行を除く)。DBにはページごとにこの形で保存する。"""
    out = []
    for n in g["nodes"]:
        out.append(f"{n['id']} {n['type']} {n['text']}".rstrip())
        out += [f"; {m}" for m in n.get("memo", "").splitlines() if m.strip()]
    for e in g["edges"]:
        out.append(f"{e['from']}>{e['to']}" + (f" {e['label']}" if e.get("label") else ""))
        out += [f"; {m}" for m in e.get("memo", "").splitlines() if m.strip()]
    return out


def dump(graphs, rules=False):
    out = header(rules)
    for g in graphs:
        out.append(f"## {g['name']}")
        out += page_lines(g)
    return "\n".join(out) + "\n"


def parse_page(name, body):
    """page_lines で保存した本文を1ページに戻す。"""
    g = parse("## _\n" + body)[0]
    g["name"] = name
    return g


def parse(text):
    graphs, last = [], None
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("fc1") or (line.startswith(";") and not graphs):  # 先頭の説明コメントは読み飛ばす
            continue
        if line.startswith("##"):
            graphs.append({"name": line[2:].strip() or "main", "nodes": [], "edges": []})
            last = None
        elif not graphs:
            raise ValueError(f"{no}行目: 最初に '## 名前' が必要です")
        elif line.startswith(";"):
            if last is None:
                raise ValueError(f"{no}行目: メモの対象がありません")
            last["memo"] = (last["memo"] + "\n" if last["memo"] else "") + line[1:].strip()
        elif _EDGE.match(line):
            a, b, lbl = _EDGE.match(line).groups()
            last = {"from": a, "to": b, "label": lbl or "", "memo": ""}
            graphs[-1]["edges"].append(last)
        else:
            parts = line.split(None, 2)
            if len(parts) < 2 or parts[1] not in TYPES:
                raise ValueError(f"{no}行目: 図形の種別が不明です: {line}")
            last = {"id": parts[0], "type": parts[1], "text": parts[2] if len(parts) > 2 else "", "memo": ""}
            graphs[-1]["nodes"].append(last)
    return graphs


def autolayout(g):
    """ループの戻り辺を無視した最長パスで段を決める簡易配置。"""
    nodes = g["nodes"]
    if not nodes:
        return
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))
    ids = {n["id"] for n in nodes}
    succ = {}
    for e in g["edges"]:
        if e["from"] in ids and e["to"] in ids:
            succ.setdefault(e["from"], []).append(e["to"])
    start = next((n["id"] for n in nodes if n["type"] == "start"), nodes[0]["id"])
    order, state, back = [], {}, set()

    def dfs(u):
        state[u] = 1
        for v in succ.get(u, []):
            if state.get(v) == 1:
                back.add((u, v))
            elif v not in state:
                dfs(v)
        state[u] = 2
        order.append(u)

    dfs(start)
    rank = {i: 0 for i in ids}
    for u in reversed(order):
        for v in succ.get(u, []):
            if (u, v) not in back:
                rank[v] = max(rank[v], rank[u] + 1)
    ends = {n["id"] for n in nodes if n["type"] == "end"}
    body = [rank[i] for i in state if i not in ends] or [0]
    last = max(body)
    for i in ids:
        if i in ends:
            rank[i] = last + 1
        elif i not in state:  # 開始から辿れない図形は下にまとめる
            rank[i] = last + 2
    cols, pos = {}, {}
    for n in nodes:
        r = rank[n["id"]]
        pos[n["id"]] = (cols.get(r, 0), r)
        cols[r] = cols.get(r, 0) + 1
    for n in nodes:
        c, r = pos[n["id"]]
        n["x"], n["y"] = round((c - (cols[r] - 1) / 2) * 290), r * 120


def apply_layout(graphs, layout):
    for g in graphs:
        saved = layout.get(g["name"], {})
        if g["nodes"] and all(n["id"] in saved for n in g["nodes"]):
            for n in g["nodes"]:
                n["x"], n["y"] = saved[n["id"]]
        else:
            autolayout(g)


def layout_of(graphs):
    return {g["name"]: {n["id"]: [n["x"], n["y"]] for n in g["nodes"]} for g in graphs}


def validate(graphs):
    """AIが読む前の機械チェック。[{level, page, node, msg}] を返す。"""
    issues = []

    def add(level, g, node, msg):
        issues.append({"level": level, "page": g["name"], "node": node, "msg": msg})

    names = set()
    for g in graphs:
        if g["name"] in names:
            add("error", g, None, f"ページ名が重複しています: {g['name']}")
        names.add(g["name"])
        by = {}
        for n in g["nodes"]:
            if n["id"] in by:
                add("error", g, n["id"], f"idが重複しています: {n['id']}")
            by[n["id"]] = n
        flow = []
        for e in g["edges"]:
            if e["from"] not in by or e["to"] not in by:
                add("error", g, None, f"存在しない図形への矢印: {e['from']}>{e['to']}")
            elif by[e["from"]]["type"] not in SIDE and by[e["to"]]["type"] not in SIDE:
                flow.append(e)
        out, inc = {}, {}
        for e in flow:
            out.setdefault(e["from"], []).append(e)
            inc.setdefault(e["to"], []).append(e)
        starts = [n for n in g["nodes"] if n["type"] == "start"]
        if len(starts) != 1:
            add("error", g, None, f"開始(start)が{len(starts)}個あります。1個にしてください")
        if not any(n["type"] == "end" for n in g["nodes"]):
            add("warn", g, None, "終了(end)がありません")
        for n in g["nodes"]:
            t, i = n["type"], n["id"]
            if t == "note":
                continue
            if t not in SIDE and not n["text"].strip():
                add("warn", g, i, "テキストが空です")
            if t in SIDE:
                continue
            o = out.get(i, [])
            if t == "end" and o:
                add("error", g, i, "終了から出る矢印があります")
            if t != "end" and not o:
                add("error", g, i, "行き止まりです(出る矢印がありません)")
            if t in ("if", "loop"):
                if len(o) < 2:
                    add("error", g, i, "分岐が2本未満です")
                if any(not e["label"] for e in o):
                    add("error", g, i, "出る矢印にラベル(条件)が必要です")
            elif len(o) > 1:
                add("warn", g, i, "矢印が複数あります。分岐は判断(if)で表してください")
            if t == "start" and inc.get(i):
                add("warn", g, i, "開始に入る矢印があります")
        if len(starts) == 1:
            seen, stack = set(), [starts[0]["id"]]
            while stack:
                u = stack.pop()
                if u not in seen:
                    seen.add(u)
                    stack += [e["to"] for e in out.get(u, [])]
            for n in g["nodes"]:
                if n["type"] not in SIDE and n["id"] not in seen:
                    add("warn", g, n["id"], "開始から到達できません")
    return issues


def layout_text(graphs):
    """座標ファイル。1図形1行で出し、座標を動かしたときの差分を読みやすくする。"""
    lines = ["{"]
    pages = list(layout_of(graphs).items())
    for pi, (name, pos) in enumerate(pages):
        lines.append(f"{json.dumps(name, ensure_ascii=False)}: {{")
        items = list(pos.items())
        for i, (k, (x, y)) in enumerate(items):
            lines.append(f" {json.dumps(k)}: [{x}, {y}]" + ("," if i < len(items) - 1 else ""))
        lines.append("}" + ("," if pi < len(pages) - 1 else ""))
    lines.append("}")
    return "\n".join(lines) + "\n"


def _cut(t, n=40):
    t = " ".join(str(t).split())
    return t if len(t) <= n else t[: n - 1] + "…"


def diff(old, new):
    """2つの図(parse結果)の意味的な差分を、1変更1行で返す。座標の移動は含めない。"""
    out = []
    o = {g["name"]: g for g in old}
    n = {g["name"]: g for g in new}
    for name, g in n.items():
        if name not in o:
            out.append(f"+ ページ {name} (図形{len(g['nodes'])}・矢印{len(g['edges'])})")
    for name in o:
        if name not in n:
            out.append(f"- ページ {name}")
    for name, g in n.items():
        if name not in o:
            continue
        p = f"[{name}]"
        on = {x["id"]: x for x in o[name]["nodes"]}
        nn = {x["id"]: x for x in g["nodes"]}
        for i, x in nn.items():
            if i not in on:
                out.append(f"+ {p} 図形 {i} {x['type']} {_cut(x['text'])}" + (f" ; {_cut(x['memo'])}" if x["memo"] else ""))
        for i, x in on.items():
            if i not in nn:
                out.append(f"- {p} 図形 {i} {x['type']} {_cut(x['text'])}")
        for i, x in nn.items():
            if i not in on:
                continue
            for key, label in (("type", "種別"), ("text", "テキスト"), ("memo", "メモ")):
                if x[key] != on[i][key]:
                    out.append(f"~ {p} 図形 {i} {label}: {_cut(on[i][key]) or '(なし)'} → {_cut(x[key]) or '(なし)'}")

        def keyed(edges):
            seen, res = {}, {}
            for e in edges:
                k = (e["from"], e["to"])
                seen[k] = seen.get(k, 0) + 1
                res[k + (seen[k],)] = e
            return res

        oe, ne = keyed(o[name]["edges"]), keyed(g["edges"])
        for k, e in ne.items():
            if k not in oe:
                out.append(f"+ {p} 矢印 {k[0]}>{k[1]}" + (f" {_cut(e['label'])}" if e["label"] else "")
                           + (f" ; {_cut(e['memo'])}" if e["memo"] else ""))
        for k, e in oe.items():
            if k not in ne:
                out.append(f"- {p} 矢印 {k[0]}>{k[1]}" + (f" {_cut(e['label'])}" if e["label"] else ""))
        for k, e in ne.items():
            if k in oe:
                for key, label in (("label", "ラベル"), ("memo", "メモ")):
                    if e[key] != oe[k][key]:
                        out.append(f"~ {p} 矢印 {k[0]}>{k[1]} {label}: {_cut(oe[k][key]) or '(なし)'} → {_cut(e[key]) or '(なし)'}")
    return out
