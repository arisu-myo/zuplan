<p align="center">
  <img src="static/logo.svg" width="72" alt="Zuplan logo">
</p>

<h1 align="center">Zuplan</h1>

<p align="center">
  <b>図で描く仕様書。AIがそのまま実装する。</b><br>
  Draw your program's spec as a flowchart — and let AI implement it.
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <img alt="Python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-blue.svg">
  <img alt="No dependencies" src="https://img.shields.io/badge/dependencies-none-brightgreen.svg">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-supported-8a2be2.svg">
</p>

![Zuplan のエディタ画面](docs/editor.png)

分岐やループが入り組んだ処理は、文章だけでAIに説明しようとすると、どうしても伝わりきらないことがあります。
Zuplan は、そうした処理の流れをフローチャートで描いて、そのままAIに渡すためのツールです。

描いた図は、AIが読みやすいシンプルなテキスト形式(`.fc`)で保存されます。AIは図のURLやMCPから最新の内容を読み取り、図のとおりに実装してくれます。

> **English summary** — Zuplan is a lightweight, local flowchart editor. Diagrams are stored in a compact, LLM-friendly text format (`.fc`), and AI agents can read and write them through a simple HTTP API or the built-in MCP server — so you can hand over complex control flow as a picture instead of prose. Pure Python standard library, no dependencies. The UI and docs are in Japanese.

## できること
- **ブラウザで手軽に描ける** — draw.io のような感覚で図形を置いて、矢印でつなぐだけ。図形や矢印にはメモも残せて、編集内容は自動で保存されます。
- **AIが読みやすい形式で保存** — `.fc` は1行に1つの要素を書くだけのシンプルな形式です。座標は別に持っているので、AIが読む量(トークン)を抑えられます。
- **AIにそのまま渡せる** — 図のURLを渡せば、AIが最新の図を読み取れます。MCPサーバも入っているので、Claude Code などから図を直接読み書きすることもできます。
- **描き間違いに気づける** — 保存のたびに、開始が1つになっているか、分岐にラベルが付いているか、行き止まりがないかなどをチェックします。
- **何を直したかが残る** — 保存するたびに変更点を記録します。AIは、前回から直された部分だけを確認できます。
- **大きな図でも軽い** — ページごとに保存しているので、1万ページ(django を丸ごと図にしたくらいの規模)でも約0.4秒で開き、保存も一瞬です。
- **インストールするものが少ない** — Python の標準ライブラリだけで動きます。

## はじめかた

[uv](https://docs.astral.sh/uv/) を使います。

**Windows の場合**は、`start.bat` をダブルクリックするだけです。ブラウザでエディタが開きます。終了するときは、黒い画面で Ctrl+C を押してください。

**コマンドで起動する場合**:
```bash
git clone https://github.com/arisu-myo/zuplan.git
cd zuplan
uv run zuplan --serve                        # 新しい図を開く
uv run zuplan --serve examples/ai_agent.fc   # 見本の図を開く
```

描いた図は `data/flowchart.db` に保存されます。

## AIに渡す

### 図のURLを渡す
エディタのURL(`http://127.0.0.1:8000/s/<ID>`)をAIに渡すだけで、AIは次のAPIから図を読み取れます。

| API | 内容 |
|---|---|
| `GET /api/s/<ID>/fc` | 図全体を `.fc` で返します(先頭に読み方の説明付き)。`?page=名前` を付けると1ページだけ |
| `GET /api/s/<ID>` | ページの一覧(名前・図形の数・版番号) |
| `GET /api/s/<ID>/log` | 変更履歴 |
| `POST /api/new?name=名前` | 送った `.fc` から新しい図を作ります(配置は自動) |

トップページ(`http://127.0.0.1:8000/`)には、APIの一覧とAI向けの詳しい説明があります。AIにトップページのURLを渡して「このツールで新しい図を作って」と頼むこともできます。

### MCPで使う
```bash
claude mcp add --transport http zuplan http://127.0.0.1:8000/mcp
```

| ツール | できること |
|---|---|
| `list_pages` | ページの一覧と図のURLを見る |
| `read_fc` | 図を `.fc` で読む(1ページだけでも可) |
| `validate` | 図をチェックする |
| `read_log` | 変更履歴を見る |
| `create_diagram` | `.fc` から新しい図を作る |
| `write_pages` | ページを書き換える・追加する・削除する |

## `.fc` の書き方
```
fc1
## login            ← ページ(関数や処理のまとまり)
a start 開始        ← id 種類 テキスト
b io ID入力
c if 認証OK?
; 3回失敗でロック    ← 直前の行へのメモ
a>b
b>c
c>d Yes            ← 矢印: 元>先 ラベル
```
図形の種類は `start end proc if io loop call screen data db note` です。`data`・`db`・`note` につないだ矢印は、処理の順番ではなく「読む・書く」などの関係を表します。`call` のテキストにページ名を書いておくと、全体像のページから詳しいページへたどれるようになります。

## エディタの使い方
- 左のパレットから図形をドラッグ(またはクリック)して置きます。図形を選ぶと下に ● が出るので、そこから線を引いてほかの図形につなぎます。
- 右クリックすると、図形・矢印・ページごとのメニューが出ます。メモは右側のパネルに書けて、AIにも伝わります。
- ページは上のカードで切り替えます。ページが多いときは、左上の検索欄で名前を絞り込めます。
- 「呼出」図形の「詳細 ↗」を押すと、そのページに移動します。「← 戻る」で元のページに戻れます。
- `.fc` や SVG としてダウンロードすることもできます。

## 自分のパソコンで使うためのツールです
Zuplan は、自分のパソコンの中で使うことを想定した便利ツールです。サーバに置いてインターネットに公開する使い方は想定しておらず、ほかのパソコンからアクセスされても応答しないようになっています(詳しくは [SECURITY.md](SECURITY.md))。

## コマンド
```bash
uv run zuplan --serve [file.fc | file.py]   # エディタを起動(ファイルを指定すると、その内容で開く)
     --port 8000  --db data/flowchart.db
uv run zuplan my.py --fc                    # Python のコードを .fc に変換(out/my.fc)
uv run zuplan my.py --html                  # Python のコードを Mermaid の HTML に変換(out/my.html)
uv run zuplan old.fc --diff new.fc          # 2つの .fc の違いを表示
```
Python のコードからの変換は、1文を1つの図形にするだけの簡単なものです。

## ファイル構成
| ファイル | 役割 |
|---|---|
| `flowchart.py` | コマンドとサーバ、Python コードの取り込み |
| `store.py` | 図の保存(SQLite、ページ単位) |
| `fcspec.py` | `.fc` の読み書き・チェック・自動配置・差分 |
| `mcp_server.py` | MCP サーバ |
| `access.py` | アクセスの制限 |
| `editor_page.py` / `static/` | エディタの画面(HTML / JS・CSS・ロゴ) |
| `landing_page.py` | トップページ(AI向けの説明とAPI一覧) |
| `examples/` | 見本(`ai_agent.py` と、それを図にした `ai_agent.fc`) |
| `start.bat` | Windows 用の起動ファイル |

## ライセンス
[MIT](LICENSE)
