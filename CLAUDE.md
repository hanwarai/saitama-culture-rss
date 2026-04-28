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
- `.github/workflows/gh-pages.yaml`（push + 毎日 00:00 UTC cron でビルド & Pages デプロイ）
- `.github/workflows/ci.yaml`（push / PR で lint / format / mypy / pytest を実行）
- `.github/workflows/claude.yml`（PR 自動レビュー、`github.actor != 'dependabot[bot]'` で除外）
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
| `list_explanation` | 本文。`</br>` 文字列で改行されている（`<br>` ではない）— description にそのまま入れるか正規化する |
| `sales_list[].sales_term` / `show_sales_status` | 販売期間と空席状況（`"空席あり○"` / `"残りわずか△"`） |
| `code_nm` | 画像のオリジナル拡張子。**公開 URL には拡張子は不要**（下記） |

**派生 URL**（CDN/Web 側、いずれもコードで判明済）:

- 詳細ページ: `https://p-ticket.jp/saitama-culture/event/{show_group_id}` → アイテムの `link`
- メイン画像: `https://cdn.p-ticket.jp/saitama-culture/event/{show_group_id}/internet_pic0_image`（拡張子なしで 200 が返る。`code_nm` を末尾につけると 403 なので注意）

## 想定アーキテクチャ（`main.py`）

`tver-rss/main.py` の `fetch_json` パターンを踏襲:

1. `fetch_json('GET', SHOW_LIST_HOME_URL, params={...})` でリストを 1 リクエストで取得（ページング不要）
2. `data.show_list` を回して、各 show を Atom item に変換:
   - `unique_id = show_group_id`
   - `title = show_group_main_title`（`show_group_sub_title` があれば連結）
   - `link = https://p-ticket.jp/saitama-culture/event/{show_group_id}`
   - `pubdate = parse(disp_sort, JST)`（`YYYYMMDDHHMM` を `Asia/Tokyo` で datetime 化、`tver-rss` 同様 UTC に変換して渡す）
   - `description` に会場/ジャンル/`show_term`/`sales_term`/`show_sales_status`/`list_explanation`（`</br>` → `<br>` に置換）をまとめる
3. `feedgenerator.Atom1Feed` を `dist/feed.xml` に書き出して終わり

`requests` 呼び出しには **必ず `timeout` と `raise_for_status`** を付ける（`tver-rss/main.py:14-17` 参照）。1 アイテムのパース失敗で全体を落とさない per-item `try/except` パターンも踏襲。

## 想定コマンド

Python 3.13 系を `uv` で固定。

```bash
uv sync                     # 依存インストール (dev グループ含む)
uv run main.py              # フィード生成: dist/feed.xml を出力
uv run ruff check .         # lint (mccabe 複雑度 10 まで含む)
uv run ruff format --check . # format チェック (修正は --check を外す)
uv run mypy                 # 型検査 (strict 寄り)
uv run pytest               # テスト + カバレッジ (cov-fail-under=80)
uv run pre-commit run --all-files
```

CI (`.github/workflows/ci.yaml`) は push / PR で `ruff check` / `ruff format --check` / `mypy` / `pytest`（カバレッジ閾値 80% 込み）を回す。1 つでも落ちたら merge 不可の方針。

動作確認は `dist/feed.xml` がパースできること（例: `xmllint --noout dist/feed.xml`）と、CI が緑であることで見る。

## デプロイ

`.github/workflows/gh-pages.yaml`（`tver-rss` と同一テンプレート）:

- トリガー: `main` への push と毎日 00:00 UTC cron
- `astral-sh/setup-uv` → `actions/setup-python`（`python-version-file: pyproject.toml`）→ `uv sync` → `uv run main.py` → `actions/upload-pages-artifact`（path: `dist`）→ `actions/deploy-pages`
- `concurrency` を workflow 単位でまとめて、push と cron の競合を防ぐ

`dist/feed.xml` は `.gitignore` 対象（ランナー上で生成して直接 Pages にアップ）。git で tracked にするものはなし（`dist/` 自体を ignore してもよい）。

購読 URL は `https://hanwarai.github.io/saitama-culture-rss/feed.xml`。ルート (`/`) には `index.html` がないので 404 になる — リーダーには `feed.xml` の URL を直接渡す。

## 自動 PR レビュー & Dependabot

`tver-rss` 同様、`.github/workflows/claude.yml` に `anthropics/claude-code-action` の自動レビュー、`.github/dependabot.yml` に `github-actions` と `uv` の weekly 更新を入れる。

- レビューは `github.actor != 'dependabot[bot]'` でスキップ（trivial bump で subscription quota を食わせない）
- Dependabot の `commit-message.prefix` は `ci`
- 認証は `CLAUDE_CODE_OAUTH_TOKEN` secret（`claude setup-token` で発行）

## コミット慣例

`fix:` / `ci:` / `feat:` を日本語本文と併用（姉妹プロジェクトと統一）。

## 既知の落とし穴

- API は `member_kb_no` を欠くと 500 を返す（`{"status":"fail","data":{}}`）。`0` を必ず付ける
- `list_explanation` は HTML エンティティではなく **リテラルの文字列 `</br>`** が入っている。`<br>` への置換、または `feedgenerator` に任せて XML エスケープのまま流す（リーダー側で読みづらくなる）かは実装時に判断
- `disp_sort` は JST 想定。UTC 変換漏れに注意
- 画像 URL に `code_nm`（`png`/`jpg`）の拡張子を足すと CloudFront 403。**拡張子なしのまま使う**
- 件数は現状 ~18 件で `end_position=100` で全件取れるが、将来増えるなら `record_num` を見て二度引きに
