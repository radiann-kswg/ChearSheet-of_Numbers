# AGENTS.md — CheatSheet of Numbers (0-999)

> **このファイルが AI エージェント向け指示の SSOT（Single Source of Truth）です。**
> GitHub Copilot（coding agent / VS Code / CLI）・Claude（Claude Code / Cowork / Desktop）・その他の AI ツールは、本ファイルの指示に従ってください。
> `.github/copilot-instructions.md` と `CLAUDE.md` は本ファイルへのポインタであり、内容の重複記載はしません。指示の追加・変更は **必ず本ファイルのみ** を編集してください。

## 前提条件（必読）

- 回答は必ず日本語でしてください。
- 変更量が 500 行を超える可能性が高い場合は、事前に「この指示では変更量が 500 行を超える可能性がありますが、実行しますか?」と確認してください。
- 大きい変更（多数ファイル生成、構成変更、ルール追加など）を加える場合、まず計画を提示し「このような計画で進めようと思います。」と提案してください。
- 大きい変更（複数ファイルにまたがる編集、目次の大幅更新、運用ルールの追加など）を行った場合は、公開可能な範囲で `_wip/` に進捗レポートを残してください。
  - 推奨ファイル名: `YYYY-MM-DD_progress.md`
  - 最低限入れる内容: 目的 / 変更点の要約 / 影響範囲（編集したファイル）/ 未完了タスク / 参考リンク
- 不確かな点がある場合は、既存ファイル（特に `index.md` と `numbers/`）を探索し、ユーザーに「こういう理解で合っていますか？」と確認してください。

## リポジトリ概要

0〜999 の数字について、次をまとめたチートシート集です。

- 数学的な性質（素因数分解・約数・トーシェント関数・表記など）
- 科学・文化に関する一次情報への導線（主に Wikipedia 等へのリンク）

### 技術スタック

- 形式: Markdown（静的ドキュメント）
- ビルド: なし（ページ生成のための補助スクリプトを同梱）
- 依存: Python 標準ライブラリのみ（追加の `pip install` 不要）

## ディレクトリ構成と役割

```
./
├── AGENTS.md                # AI 向け指示の SSOT（このファイル）
├── CLAUDE.md                # Claude 用ポインタ（編集しない）
├── .github/
│   └── copilot-instructions.md  # Copilot 用ポインタ（編集しない）
├── index.md                 # 入口（0〜999 目次）
├── README.md                # リポジトリ概要
├── numbers/                 # 各数字の個別ページ（基本は 1 数字 = 1 ファイル）
│   ├── 0xx/                 # 000〜099
│   ├── 1xx/                 # 100〜199
│   └── ...                  # 〜 9xx/（900〜999）
├── _template/               # 執筆テンプレート（number.md）
├── tools/                   # 生成・補助スクリプト
│   ├── generate_numbers.py  # メイン生成スクリプト
│   ├── check_internal_links.py  # 内部リンク検査
│   ├── wikipedia_ja.py      # Wikipedia（日本語）連携
│   ├── wikidata_cc0.py      # Wikidata（CC0）連携
│   ├── wikipedia_ja_pins_v1.json                 # 引用ピン留め設定
│   ├── wikipedia_ja_importance_overrides_v1.json # 重要度閾値の上書き設定
│   └── _cache/              # 取得キャッシュ（通常 Git 管理しない）
├── _wip/                    # 作業途中メモ（公開してよい内容のみ）
├── .private/                # 非公開メモ（コミット対象外の下書き等）
└── LICENSE                  # CC BY-SA 4.0
```

## 執筆ルール（重要）

### 1ファイル=1数字

- 基本: `numbers/<hundreds>xx/<3桁>.md`
  - 例: `31` → `numbers/0xx/031.md`、`496` → `numbers/4xx/496.md`
- ファイル名は **必ず 3 桁のゼロ埋め**にしてください（リンク安定のため）。

### 生成物の扱い

- `numbers/` 配下と `index.md` / `README.md` は、原則として `tools/generate_numbers.py` で生成します。
- 内容やフォーマットを変更する場合は、個別ファイルの手編集ではなく、**まず生成スクリプト側の更新を優先**してください（整合性維持のため）。
  - `README.md` の文面は `tools/generate_numbers.py` の `render_readme()` から生成されます。

### 数式（KaTeX）記法

VS Code 上で **KaTeX** 記法（拡張機能 `jeff-tian.markdown-katex`、`.vscode/extensions.json` で推奨済み）を用います。

- インライン数式: `$...$` / 別行立て: `$$...$$`（`\(...\)` や `\[...\]` は使わない）
- `numbers/` 配下の表記ゆれを避けるため、数式化が必要な表現は **生成スクリプト側で整形**する
- Wikipedia 由来の短い引用は基本は原文のまま扱う。
  - **数式表記を KaTeX に整形して掲載する場合**は「整形版（改変あり）」として扱い、引用行に `整形`（例: 「短い引用・整形」）と改変がある旨を明記する。
  - 原文と整形版の併記は原則不要（可読性を優先）。
- **整形時の注意（既知の不具合防止）**: HTML 実体参照（`&times;` `&minus;` など）は KaTeX 記号（`\times` `-`）へ**必ずデコードしてから**整形すること。数式と後続の説明文が連結されて誤った等式（例: `$715 = 714$`）にならないよう、式と文の境界を保持すること。

### 内容の方針（公開に耐えるための注意）

- Wikipedia / 解説サイト等の本文を長文で転載しない（要約＋参照リンク中心）。
- 引用する場合は短くし、出典 URL を必ず添える。
- 断定が難しい「文化的ないわれ」は、一次情報へのリンクを付けた上で、言い切りを避ける。
- Wikipedia は CC BY-SA。本リポジトリ（CC BY-SA 4.0）と整合は取りやすいが、無制限の転載は避け「要約＋リンク」を基本とする。
- Wikidata の構造化データは CC0。規格・コード等の"事実データ"は Wikidata 由来で自動拡充し、一次情報へリンクする。
- 数学的性質の記述（素因数分解・約数・トーシェント等）を追加・変更した場合は、可能なら計算機（Python / Wolfram 等)で検算する。

## 生成ワークフロー

### 基本生成

```powershell
python tools/generate_numbers.py
```

- VS Code: `Terminal: Run Task` から生成タスクを実行可（選択中インタープリタを使用）
- venv（任意）: Windows `py -3 -m venv .venv`、macOS/Linux `python3 -m venv .venv`

### Wikidata（CC0）連携（自動拡充）

Wikidata Query Service / Action API から以下を自動追記（ネットワーク不可時はスキップ可）:

- 数そのものの Wikidata 項目（説明の要約＋リンク）
- ISO 3166-1 numeric（3桁の国・地域コード）
- 国番号（国際電話・E.164。数字のみの国番号に限定）

オプション: `--no-wikidata`（無効化）/ `--refresh-wikidata`（キャッシュ更新）

### Wikipedia（日本語）連携

- 冒頭（概要）取得で `Wikipedia（要点）` を補強。オプション: `--no-wikipedia` / `--refresh-wikipedia`
- `--wikipedia-sections` で『性質』『その他』から短い引用を抽出。
  - キャッシュ更新: `--refresh-wikipedia-sections` / オフライン生成: `--offline`
  - キャッシュ: `tools/_cache/wikipedia_ja_properties_v1.json` ほか
- 採用制御（ハードコード回避）:
  - 固有名詞のピン留め: `tools/wikipedia_ja_pins_v1.json`（本文内の部分一致）
  - 重要度閾値の上書き: `tools/wikipedia_ja_importance_overrides_v1.json`

### 追加・更新時の最低限手順

1. `tools/` や設定を更新したら、まずサンプル生成（`--only 6,57,496` など）で意図した変更を確認
2. 全数生成: `python tools/generate_numbers.py --wikipedia-sections`
3. 内部リンク検査: `python tools/check_internal_links.py`（Missing links: 0 を確認）

### 公開（リリース）

- 全数生成 → リンク検査成功 → main へ反映
- タグ（例: `vYYYY.MM.DD`）を作成し、GitHub Release に変更点（要約）を記載

## アンチパターン

- 既存の命名規則と異なる場所に新規ファイルを作る（例: `31.md` を `numbers/` 直下に置く）。
- 外部資料の文章をコピペして長文転載する（要約し、参照リンクを付ける）。
- `index.md` と実ファイルのリンクが不整合のまま放置される。
- 生成物（`numbers/` 配下）を手編集して生成スクリプトとの整合性を壊す。
- 本ファイル以外（`copilot-instructions.md` / `CLAUDE.md`）に指示本文を書いて SSOT を崩す。

## ライセンス（CC BY-SA 公開のための注意）

- `LICENSE` は CC BY-SA 4.0。公開可能な内容のみを含めてください。
- 外部資料は「短い引用＋出典」または「要約＋リンク」を基本にし、転載は避けてください。
- Wikipedia 本文を取り込む場合は、CC BY-SA の要件（表示・継承・変更表示など）を満たす形で、出典 URL を明確に付けてください。
