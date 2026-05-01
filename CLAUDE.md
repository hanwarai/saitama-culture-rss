# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

`https://p-ticket.jp/saitama-culture`（さいたま市文化センター等のチケット販売）に掲載中の公演を **単一 Atom フィード** にして GitHub Pages で公開するスクリプト。購読 URL は `https://hanwarai.github.io/saitama-culture-rss/feed.xml`。GitHub Actions が 1 日 1 回（00:00 UTC）に再ビルド → デプロイする。

**HTML のインデックスページは出さない**（フィード 1 本だけなので一覧 UI 不要）。姉妹プロジェクト `tver-rss` と同じ構成だが、Jinja2 / `templates/` は不要 — 純粋に XML を 1 本吐くだけ。`saitama-culture` は **JSON API が公開されている** ので playwright や HTML パースも不要、素の `requests + feedgenerator` で十分。

## 現状

レイアウト（`tver-rss` をひな形にしつつ品質ゲートを増強）:

- `pyproject.toml` — Python 3.13、本体依存 `requests` / `feedgenerator`。dev 依存に `ruff` / `mypy` / `pytest` / `pytest-cov` / `pre-commit` / `types-requests`。`[tool.ruff]` `[tool.mypy]` `[tool.pytest.ini_options]` も同居
- `.python-version`
- `.gitignore`（`/dist/` を ignore。`uv.lock` は **commit する**）
- `.pre-commit-config.yaml`（pre-commit-hooks + ruff + ruff-format + mypy）
- `main.py`（実装は下記）
- `tests/test_main.py`（pytest。カバレッジ閾値 80%）
- `.github/workflows/gh-pages.yaml`（push + 毎日 00:00 UTC cron でビルド & Pages デプロイ。**唯一のワークフロー**）
- `.github/dependabot.yml`（`github-actions` と `uv` を weekly、`commit-message.prefix: "ci"`）

`feed.csv` も `templates/` も `feeds/index.html` も **使わない**（単一フィードなので URL/client_id は `main.py` に直書き、出力は `feed.xml` 一本）。

出力先は `dist/feed.xml`。`actions/upload-pages-artifact` の `path: dist`。

## ソースサイトの API（重要）

サイト本体は Nuxt.js SPA で、トップ HTML はローダーしか返さない。実際のデータは下記 API を直接叩いて取得する:

```
GET https://api.p-ticket.jp/show/get-list-home
  ?client_id=saitama-culture
  &start_position=1
  &end_position=100      # 現在 ~18 件。50 程度でも十分だが余裕を持って 100
  &member_kb_no=0        # 0 = 非ログイン
```

レスポンス形 (`status:"success"` のとき `data.show_list[]`):

| field | 用途 |
|---|---|
| `show_group_id` | 一意キー（例 `bc260501`）。フィードアイテムの `unique_id` と詳細 URL に使う |
| `show_group_main_title` | アイテム title |
| `show_group_sub_title` | サブタイトル（あれば description 冒頭に） |
| `show_term` | 公演日時の表示文字列 (`"2026/5/1(金) 18:30"`)。description 用 |
| `disp_sort` | 公演開始日時 `YYYYMMDDHHMM` 形式（ソート/`pubdate` 用、こちらが機械可読） |
| `genre_nm` / `sub_genre_nm` | ジャンル（description / category） |
| `hall_nm` | 会場名（例: `さいたま市文化センター`） |
| `list_explanation` | 本文の長文（`</br>` 文字列で改行）。**現在の実装では使っていない** — フィード本文を肥大化させる原因なので意図的に捨てている。詳細は link 先で読ませる方針 |
| `sales_list[].sales_term` / `show_sales_status` | 販売期間と空席状況（`"空席あり○"` / `"残りわずか△"`） |
| `code_nm` | 画像のオリジナル拡張子。**公開 URL には拡張子は不要**（下記） |

**派生 URL**（CDN/Web 側、いずれもコードで判明済）:

- 詳細ページ: `https://p-ticket.jp/saitama-culture/event/{show_group_id}` → アイテムの `link`
- メイン画像: `https://cdn.p-ticket.jp/saitama-culture/event/{show_group_id}/internet_pic0_image`（拡張子なしで 200 が返る。`code_nm` を末尾につけると 403 なので注意）

## アーキテクチャ（`main.py`）

1. `fetch_show_list()`: `requests.get(API_URL, params=..., headers=API_HEADERS, timeout=TIMEOUT)` → `raise_for_status` → JSON unwrap。ページング不要 (1 リクエストで全件)
2. `data.show_list` を回して、各 show を Atom item に変換:
   - `unique_id = show_group_id`
   - `title = show_group_main_title`（`show_group_sub_title` があれば連結）
   - `link = https://p-ticket.jp/saitama-culture/event/{show_group_id}`
   - `pubdate = parse(disp_sort, JST)`（`YYYYMMDDHHMM` を `Asia/Tokyo` で datetime 化、`tver-rss` 同様 UTC に変換して渡す）
   - `description` は **コンパクト**に `公演日時 / 会場 / ジャンル / 販売状況` を `<br>` 区切りで並べるだけ。`list_explanation` は使わない（リーダー上で情報過多になる）
   - サムネイル画像は **`<media:thumbnail>`**（Media RSS, `xmlns:media="http://search.yahoo.com/mrss/"`）で出す。本文に `<img>` は埋めない（リーダー側で二重表示になるため）。これは `feedgenerator.Atom1Feed` を継承した `AtomFeedWithMedia` で実装: `root_attributes` で namespace を増やし、`add_item_elements` で `media:thumbnail` を吐く。アイテム側は `add_item(media_thumbnail=URL, ...)` で渡す
3. `AtomFeedWithMedia`（`feedgenerator.Atom1Feed` 派生）で `dist/feed.xml` に書き出して終わり

`requests` 呼び出しには **必ず `timeout` と `raise_for_status`** を付ける（`main.py:43-50`）。1 アイテムのパース失敗で全体を落とさない per-item `try/except` は `build_feed` で実装。

## コマンド

Python 3.13 系を `uv` で固定。

```bash
uv sync                     # 依存インストール (dev グループ含む)
uv run main.py              # フィード生成: dist/feed.xml を出力
SSL_VERIFY=False uv run main.py  # 自己署名証明書環境用 (社内プロキシ等)
uv run ruff check .         # lint (mccabe 複雑度 10 まで含む)
uv run ruff format --check . # format チェック (修正は --check を外す)
uv run mypy                 # 型検査 (strict 寄り)
uv run pytest               # テスト + カバレッジ (cov-fail-under=80)
uv run pre-commit run --all-files
```

**CI ワークフローは置いていない**（`gh-pages.yaml` 単独）。lint / format / mypy / pytest は `pre-commit` のローカル実行で担保する方針。動作確認は `dist/feed.xml` がパースできること（例: `xmllint --noout dist/feed.xml`）と、`gh-pages.yaml` のビルドが通っていることで見る。

## デプロイ

`.github/workflows/gh-pages.yaml`（`tver-rss` と同一テンプレート）:

- トリガー: `main` への push と毎日 00:00 UTC cron
- `astral-sh/setup-uv` → `actions/setup-python`（`python-version-file: pyproject.toml`）→ `uv sync` → `uv run main.py` → `actions/upload-pages-artifact`（path: `dist`）→ `actions/deploy-pages`
- `concurrency` を workflow 単位でまとめて、push と cron の競合を防ぐ

`dist/` 配下は `.gitignore` 済み（ランナー上で生成して直接 Pages にアップ）。git tracked な成果物はない。

購読 URL は `https://hanwarai.github.io/saitama-culture-rss/feed.xml`。ルート (`/`) には `index.html` がないので 404 になる — リーダーには `feed.xml` の URL を直接渡す。

## Dependabot

`.github/dependabot.yml` に `github-actions` と `uv` の weekly 更新を入れる。Dependabot の `commit-message.prefix` は `ci`。自動 PR レビュー (`claude.yml`) は置いていない。

## コミット慣例

`fix:` / `ci:` / `feat:` を日本語本文と併用（姉妹プロジェクトと統一）。

## 既知の落とし穴

- **API は `Origin: https://p-ticket.jp` と `Referer: https://p-ticket.jp/saitama-culture` の両ヘッダが必須**。欠けると **502 Bad Gateway**（WAF/CDN 挙動）。`main.py` の `API_HEADERS` で固定済み — リクエスト経路を変えるとき要注意
- API は `member_kb_no` を欠くと 500 を返す（`{"status":"fail","data":{}}`）。`0` を必ず付ける
- `list_explanation` は HTML エンティティではなく **リテラルの文字列 `</br>`** が混じる。現状は使っていないので問題にならないが、もし将来本文として使うなら `replace("</br>", "<br>")` を忘れずに
- `disp_sort` は JST 想定。UTC 変換漏れに注意
- 画像 URL に `code_nm`（`png`/`jpg`）の拡張子を足すと CloudFront 403。**拡張子なしのまま使う**
- 件数は現状 ~18 件で `end_position=100` で全件取れるが、将来増えるなら `record_num` を見て二度引きに
