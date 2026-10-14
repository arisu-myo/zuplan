"""ルートページ(/)。人には「新しい図を作る」ボタン、AIには図(プロジェクト)の作り方を説明する。"""

# AIが最初に書く .fc の見本(検査を通る形にしておく)
EXAMPLE = """fc1
## 全体像
N1 start 起動
N2 io ID・パスワード入力
N3 call ログイン処理 [login]
N4 if 認証OK?
N5 screen メイン画面
N6 end 終了
N7 db ユーザーDB
N1>N2
N2>N3
N3>N4
N4>N5 Yes
N4>N2 No
; 3回失敗したら1分ロック
N5>N6
N3>N7 照会
## login
L1 start 開始(id, password)
L2 proc パスワードをハッシュ化
L3 io 結果を返す
L4 end 終了
L1>L2
L2>L3
L3>L4
"""

# API一覧(トップページの表と GET /api の両方に使う): (メソッド, パス, 内容, 返すもの)
APIS = [
    ("GET", "/", "トップページ(作り方・読み方の説明とAPI一覧)", "HTML"),
    ("GET", "/api", "API一覧", "JSON"),
    ("POST", "/api/new?name={名前}", "本文の .fc(text/plain, UTF-8)から新しい図を作る。座標は自動配置", "JSON(201): id, url, fc, api, log, download, issues"),
    ("GET", "/api/s/{ID}/fc?page={ページ名}", "図の .fc テキスト(先頭に読み方ルール)。page は省略可", "text/plain"),
    ("GET", "/api/s/{ID}", "ページの一覧(名前・図形数・版番号)。ページが多くても軽い", "JSON: id, name, pages[{name, node_count, rev}], rules"),
    ("GET", "/api/s/{ID}?page={ページ名}", "1ページの内容(座標なし)と検査結果", "JSON: id, name, pages[{name, rev, nodes, edges}], issues, rules"),
    ("GET", "/api/s/{ID}/log", "変更履歴(保存ごとの意味的な差分)", "text/plain"),
    ("POST", "/mcp", "MCPサーバ(Streamable HTTP)。道具: list_pages, read_fc, validate, read_log, create_diagram, write_pages", "JSON-RPC 2.0"),
    ("GET", "/s/{ID}", "図エディタ(人向け)", "HTML"),
    ("GET", "/s/{ID}/download.fc", ".fc のダウンロード(人向け。中身は /api/s/{ID}/fc と同じ)", "ファイル"),
    ("POST", "/new", "空の図を作ってエディタへ移動(トップページのボタン用)", "303 → /s/{ID}"),
    ("POST", "/s/{ID}/save, /s/{ID}/settings", "エディタ内部用(保存・設定)。AIは使わない", "JSON"),
]

PAGE = r"""<!doctype html>
<html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Zuplan - 図で描く仕様書</title>
<link rel="icon" type="image/svg+xml" href="/static/logo.svg">
<meta name="description" content="Zuplan: 図(フローチャート)でプログラムの仕様を描き、AIが読んで実装するためのツール。AIは POST __BASE__/api/new に .fc を送ると新しい図を作れ、GET __BASE__/api/s/{ID}/fc で図を読めます。API一覧は GET __BASE__/api。">
<style>
:root{color-scheme:light;--bg:#f4f6fb;--panel:#fff;--line:#e1e5ee;--ink:#1f2937;--sub:#6b7280;--accent:#2f6bd8;--accent2:#e8f0ff}
*{box-sizing:border-box}
body{font-family:"Segoe UI","Yu Gothic UI","Hiragino Sans",sans-serif;margin:0;background:var(--bg);color:var(--ink);font-size:15px;line-height:1.75}
main{max-width:860px;margin:0 auto;padding:2.5rem 16px 4rem}
.hero{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:2rem;text-align:center}
.brand{display:inline-flex;align-items:center;gap:.6rem;font-weight:700;font-size:28px;letter-spacing:-.01em}
.brand img{width:42px;height:42px;display:block}
.tagline{font-size:17px;font-weight:600;color:var(--ink);margin:.5rem 0 0}
.hero p{color:var(--sub);margin:.6rem 0 1.4rem}
button{font:inherit;font-weight:600;font-size:16px;cursor:pointer;border:1px solid var(--accent);background:var(--accent);color:#fff;
  padding:.7rem 1.6rem;border-radius:10px}
button:hover{background:#2459b3}
section{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:1.4rem 1.8rem;margin-top:1.4rem}
h2{font-size:18px;margin:0 0 .6rem}
h3{font-size:15px;margin:1.2rem 0 .3rem}
code,pre{font-family:Consolas,"Cascadia Mono",Menlo,monospace}
code{background:var(--bg);padding:.1rem .35rem;border-radius:5px;font-size:13.5px}
pre{background:#1f2937;color:#e5e7eb;padding:1rem;border-radius:10px;overflow-x:auto;font-size:13px;line-height:1.6;margin:.5rem 0}
pre code{background:none;padding:0;font-size:inherit}
ol,ul{padding-left:1.3rem;margin:.4rem 0}
table{border-collapse:collapse;width:100%;font-size:14px;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:.35rem .6rem;text-align:left;vertical-align:top}
th{background:var(--bg);white-space:nowrap}
.note{color:var(--sub);font-size:13.5px}
</style>
<body><main>

<div class="hero">
  <div class="brand"><img src="/static/logo.svg" alt="">Zuplan</div>
  <div class="tagline">図で描く仕様書。AIがそのまま実装する。</div>
  <p>図(フローチャート)でプログラムの仕様を描き、AIがそれを読んで実装するためのツールです。<br>図1つごとに専用のURLができ、そのURLを共有すると同じ図を開いて編集できます。</p>
  <form method="post" action="/new"><button>新しい図を作る</button></form>
  <p class="note" style="margin:1rem 0 0">AI向け: <a href="#for-ai">図の作り方</a> ・ <a href="#read">図の読み方</a> ・ <a href="#mcp">MCPで使う</a> ・ <a href="#apis">API一覧</a> ・ <a href="#format">.fc 形式</a></p>
</div>

<section id="for-ai">
<h2>AIの方へ: 新しいプロジェクト(図)の作り方</h2>
<p>ユーザーから「このツールで新しいプロジェクトを作って」と頼まれたら、次の手順で図を作り、URLをユーザーに伝えてください。</p>
<ol>
  <li>ユーザーの要望を、下の <b>.fc 形式</b>でフローとして書く(座標は不要。サーバが自動で配置します)。</li>
  <li><code>POST __BASE__/api/new?name=プロジェクト名</code> に、.fc の本文をそのまま送る(<code>Content-Type: text/plain; charset=utf-8</code>)。名前に日本語などを使うときはURLエンコードする。</li>
  <li>返ってきた JSON の <code>issues</code> を確認する。<code>level</code> が <code>error</code> のものがあれば .fc を直して、もう一度作る(作り直すと別の図になります)。</li>
  <li>JSON の <code>url</code> をユーザーに伝える。ユーザーはそのURLのエディタで、図を見ながら直せます。</li>
  <li>実装するときは <code>fc</code> のURLを GET して、ユーザーが直した最新の .fc を読む(下の「図を読む」)。図にない仕様は足さず、曖昧な点はユーザーに質問する。</li>
</ol>

<h3>送り方の例</h3>
<pre><code>curl -X POST "__BASE__/api/new?name=login-app" \
  -H "Content-Type: text/plain; charset=utf-8" \
  --data-binary @plan.fc</code></pre>

<h3>返ってくる JSON(201 Created)</h3>
<pre><code>{
  "id": "aBcD...",
  "url": "__BASE__/s/aBcD...",                  ← ユーザーに伝える(図エディタ)
  "fc": "__BASE__/api/s/aBcD.../fc",             ← 最新の .fc(読み方ルール付き)
  "api": "__BASE__/api/s/aBcD...",               ← 最新の内容(JSON)
  "log": "__BASE__/api/s/aBcD.../log",           ← 変更履歴(ユーザーが何を直したか)
  "download": "__BASE__/s/aBcD.../download.fc",  ← .fc のダウンロード(人向け)
  "issues": [{"level": "error|warn", "page": "ページ名", "node": "id または null", "msg": "内容"}]
}</code></pre>
<p class="note">.fc が読めないときは 400 と <code>{"error": "3行目: 図形の種別が不明です: ..."}</code> を返します。大きさの上限は __MAX__MB です。</p>
</section>

<section id="read">
<h2>AIの方へ: 図を読む</h2>
<p>ユーザーから図のURL(<code>__BASE__/s/&lt;ID&gt;</code>)を渡されたら、そのページ(人が使うエディタ)ではなく、次のAPIを GET して読んでください。</p>
<ol>
  <li>まず <code>GET __BASE__/api/s/&lt;ID&gt;</code> でページの一覧(名前・図形数)を見る。</li>
  <li>ページが少なければ <code>GET __BASE__/api/s/&lt;ID&gt;/fc</code> で図全体を .fc テキスト(先頭に読み方ルール)として読む。<b>実装にはこれが一番少ない量で済みます。</b></li>
  <li>ページが多い(図形が数千個以上ある)ときは、全体を一度に読まず、<code>?page=ページ名</code>(URLエンコード)を付けて必要なページだけ読む。<code>call</code> 図形のテキストにあるページ名をたどると、全体像から詳細へ掘り下げられる。</li>
  <li>前回読んだあとにユーザーが何を直したかは <code>GET __BASE__/api/s/&lt;ID&gt;/log</code> で分かる。<code>rev</code> はそのページを保存するたびに増えるので、変わったかどうかの確認に使える。</li>
  <li><code>issues</code> に <code>error</code> があるときは、実装する前にユーザーへ確認する。</li>
</ol>
<h3>読み方の例</h3>
<pre><code>curl "__BASE__/api/s/aBcD.../fc"
curl "__BASE__/api/s/aBcD.../fc?page=login"
curl "__BASE__/api/s/aBcD..."</code></pre>
<h3>JSON の形</h3>
<pre><code>GET /api/s/&lt;ID&gt;            ← 一覧
{
  "id": "aBcD...", "name": "login-app.fc",
  "url": "...", "api": "...", "fc": "...", "log": "...",
  "pages": [{"name": "全体像", "node_count": 7, "rev": 3}, {"name": "login", "node_count": 4, "rev": 1}],
  "rules": "[fc形式の読み方] ..."
}

GET /api/s/&lt;ID&gt;?page=login  ← 1ページの中身
{
  "id": "aBcD...", "name": "login-app.fc", "url": "...", ...,
  "pages": [{"name": "login", "rev": 1,
             "nodes": [{"id": "L1", "type": "start", "text": "開始(id, password)", "memo": ""}],
             "edges": [{"from": "L1", "to": "L2", "label": "", "memo": ""}]}],
  "issues": [...],
  "rules": "[fc形式の読み方] ..."
}</code></pre>
<p class="note">座標は含みません(実装には不要なため)。存在しないID・ページは 404 と <code>{"error": ...}</code>(ページ違いのときは <code>pages</code> に正しい名前の一覧)を返します。</p>
</section>

<section id="mcp">
<h2>MCPで使う(Claude Code など)</h2>
<p>MCP に対応したAIクライアントなら、上のAPIを直接呼ばなくても、道具として図を読み書きできます。Claude Code では次の1行で登録します。</p>
<pre><code>claude mcp add --transport http zuplan __BASE__/mcp</code></pre><table>
<tr><th>道具</th><th>内容</th></tr>
<tr><td><code>list_pages</code></td><td>ページ一覧(名前・図形数・版番号)と図のURL</td></tr>
<tr><td><code>read_fc</code></td><td>図を .fc テキストで読む(<code>page</code> で1ページに絞れる)。実装するときはこれ</td></tr>
<tr><td><code>validate</code></td><td>図を検査して、問題の一覧を返す</td></tr>
<tr><td><code>read_log</code></td><td>変更履歴(ユーザーが何を直したか)</td></tr>
<tr><td><code>create_diagram</code></td><td>.fc から新しい図を作り、URLを返す</td></tr>
<tr><td><code>write_pages</code></td><td>ページを上書き・追加・削除する(図形の id が同じなら座標を引き継ぐ)</td></tr>
</table>
<p class="note"><code>diagram</code> には図のID、または図のURL(<code>__BASE__/s/&lt;ID&gt;</code>)をそのまま渡せます。ユーザーが同じページを編集中に <code>write_pages</code> で書き換えると、ユーザーの画面は再読み込みが必要になります。</p>
</section>

<section id="apis">
<h2>API一覧</h2>
<p>同じ内容を JSON で <code>GET __BASE__/api</code> からも取得できます。<code>{ID}</code> は図のURL <code>/s/{ID}</code> の部分です。</p>
<table>
<tr><th>メソッド</th><th>パス</th><th>内容</th><th>返すもの</th></tr>
__API_ROWS__
</table>
</section>

<section id="format">
<h2>.fc 形式(1行1要素)</h2>
<pre><code>__RULES__</code></pre>
<table>
<tr><th>行</th><th>書き方</th><th>説明</th></tr>
<tr><td>先頭</td><td><code>fc1</code></td><td>形式の目印</td></tr>
<tr><td>ページ</td><td><code>## 名前</code></td><td>関数・処理の単位。<b>名前はファイル内で重複不可</b></td></tr>
<tr><td>図形</td><td><code>id 種別 テキスト</code></td><td>id はページ内で一意で、空白と <code>&gt;</code> を含まない英数字(例: <code>N1</code>)。テキストは行末まで</td></tr>
<tr><td>矢印</td><td><code>元id&gt;先id ラベル</code></td><td>同じページ内の図形どうしをつなぐ。ラベルは省略可</td></tr>
<tr><td>メモ</td><td><code>; メモ</code></td><td>直前の図形・矢印への補足。複数行可</td></tr>
</table>

<h3>種別</h3>
<table>
<tr><th>種別</th><th>意味</th><th>決まり</th></tr>
<tr><td><code>start</code></td><td>開始</td><td>1ページに必ず1つ</td></tr>
<tr><td><code>end</code></td><td>終了</td><td>出る矢印なし</td></tr>
<tr><td><code>proc</code></td><td>処理</td><td>出る矢印は1本</td></tr>
<tr><td><code>if</code></td><td>判断</td><td>出る矢印を2本以上にし、すべてにラベル(Yes / No など)を付ける</td></tr>
<tr><td><code>loop</code></td><td>繰り返し</td><td>出る矢印を2本以上にし、ラベル(次 / 完了 など)を付ける</td></tr>
<tr><td><code>io</code></td><td>入出力</td><td>画面表示・入力・ファイル読み書き</td></tr>
<tr><td><code>call</code></td><td>別ページの呼び出し</td><td>テキストに呼び出すページ名を含める(例: <code>ログイン処理 [login]</code>)。エディタで詳細ページへ移動できる</td></tr>
<tr><td><code>screen</code></td><td>画面</td><td>画面遷移を表すとき</td></tr>
<tr><td><code>data</code> <code>db</code></td><td>データ・DB</td><td>実行順に入らない。つなぐ矢印は読み書きの関係(ラベルに「照会」「保存」など)</td></tr>
<tr><td><code>note</code></td><td>補足メモ</td><td>実装しない</td></tr>
</table>

<h3>検査(保存のたびに実行。結果は API の <code>issues</code> にも入ります)</h3>
<ul>
  <li>開始(start)がちょうど1つ / ページ名・id が重複していない / 存在しない図形への矢印がない</li>
  <li>判断・繰り返しは分岐が2本以上で、すべてラベル付き</li>
  <li>終了以外の図形に行き止まりがない(終了から出る矢印もない)</li>
  <li>注意(warn): 終了がない、開始から到達できない図形、判断以外からの分岐 など</li>
</ul>

<h3>見本(全体像ページ + 詳細ページ)</h3>
<pre><code>__EXAMPLE__</code></pre>
<p class="note">大きなプログラムは、まず「全体像」ページで流れを書き、各処理を <code>call</code> で別ページに分けて掘り下げると読みやすくなります。</p>
</section>

</main></body></html>"""
