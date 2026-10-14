"""ブラウザ上の図エディタのHTML。flowchart.py の --serve が配信する。

見た目は static/editor.css、動きは static/editor.js(普通のファイルなので、文法チェックや色分けが効く)。
__INIT__(図の一覧と先頭ページのJSON)・__FC_URL__・__API_URL__・__V__(キャッシュ対策の版)はサーバが置き換える。
"""

PAGE = r"""<!doctype html>
<html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Zuplan</title>
<link rel="icon" type="image/svg+xml" href="/static/logo.svg?v=__V__">
<link rel="alternate" type="text/plain" title="この図の .fc(AI向け)" href="__FC_URL__">
<link rel="alternate" type="application/json" title="この図のJSON(AI向け)" href="__API_URL__">
<link rel="stylesheet" href="/static/editor.css?v=__V__">
<body>
<p class="ai-hint">AIの方へ: このページは人が使う図エディタです。図の内容は __FC_URL__ (.fc テキスト、読み方ルール付き)または __API_URL__ (JSON)を GET して読んでください。1ページだけ読むときは ?page=ページ名 を付けます。</p>
<header>
  <a class="brand" href="/" title="トップページへ"><img src="/static/logo.svg?v=__V__" alt="">Zuplan</a>
  <span id="path"></span><span id="dirty" style="font-size:12px;color:#1f7a3a">✓ 保存済み</span>
  <label class="sw" title="オンにすると、編集の約1秒後に自動で保存します"><input type="checkbox" id="auto"><i></i><span>自動保存</span></label>
  <div class="spacer"></div>
  <div class="group"><small>書き出し</small><button id="sfc" title="保存済みの内容を .fc ファイルでダウンロード">.fc</button><button id="ssvg">SVG</button></div>
  <button id="save" class="pri">保存 <small style="opacity:.75">Ctrl+S</small></button>
</header>
<div id="pagebar">
  <div id="pfind"><input id="pq" type="search" placeholder="ページを検索" title="ページ名の一部で絞り込みます"><small id="pcount"></small></div>
  <div id="tabs"></div>
</div>
<div id="main">
  <aside id="pal"></aside>
  <div id="wrap">
    <div id="tools">
      <button id="tsel" class="on" title="選択・移動">↖ 選択</button>
      <button id="conn" title="接続元→接続先の順にクリック">↗ 矢印</button><i></i>
      <button id="back" title="詳細ページから元のページへ">← 戻る</button><i></i>
      <button id="undo" title="Ctrl+Z">↶ 戻す</button><button id="del" title="Delete">🗑 削除</button><i></i>
      <button id="zout" title="縮小">−</button><button id="zin" title="拡大">＋</button><button id="fit">全体表示</button>
    </div>
    <svg id="svg" xmlns="http://www.w3.org/2000/svg"></svg>
    <textarea id="ed" rows="1"></textarea>
    <div id="empty"><div>左の図形をドラッグして置きましょう<br>図形を選ぶと下に出る <b style="color:#2f6bd8">●</b> から線を伸ばして、つなげます</div></div>
  </div>
  <aside id="side"></aside>
</div>
<div id="issues"></div>
<div id="ctx"></div>
<div id="toast"></div>
<script>window.INIT = __INIT__;</script>
<script src="/static/editor.js?v=__V__"></script>
</html>"""
