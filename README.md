# CheatSheet of Numbers (0-999)

0〜999 の数字について、数学的な性質と、科学/文化に関する一次情報への導線をまとめたチートシート集です。

- 入口: [index.md](index.md)
- 個別ページ: `numbers/` 配下（基本は 1 数字 = 1 ファイル）
- 一部の規格・コード情報は Wikidata（CC0）から自動取得して補強します
- Wikipedia（日本語）の冒頭（概要）に加え、『性質』『その他』から短い引用を抽出して要点の入口を補強します（長文転載はしません）

## 方針（公開に耐えるための注意）

- 外部サイトの本文を長文転載しません（要約＋参照リンク中心）。
- 引用する場合は短くし、出典 URL を必ず添えます。
- 数式表記を KaTeX に整形して掲載する場合は、改変がある旨（例: 『短い引用・整形』）を明記します。

## ライセンス

本リポジトリは **CC BY-SA 4.0** です。詳細は [LICENSE](LICENSE) を参照してください。

- Wikidata の構造化データは CC0（パブリックドメイン相当）です。取得したデータの出典は各ページの Wikidata リンクを参照してください。

## 生成について

このリポジトリの `numbers/` 以下は、`tools/generate_numbers.py` で生成できます。

- 依存: Python 標準ライブラリのみ（追加の `pip install` は不要）

```powershell
python tools/generate_numbers.py
```

- VS Code を使う場合は、`Terminal: Run Task` から生成タスクを実行できます（`python` が PATH で解決できる前提）。
- `python` が見つからない場合: Python 3 をインストールして PATH に追加（Windows なら `py -3` の利用も可）。
- venv を使う場合（任意）: `python -m venv .venv`

### 相対リンク（リポジトリ内）

各数字ページに `リポジトリ内リンク` を自動出力し、近傍（±1/±10/±100）に移動できる相対リンクを付与します。

### Wikipedia 引用（性質/その他）

Wikipedia の『性質』『その他』セクションから短い引用を抽出するには `--wikipedia-sections` を指定します。

```powershell
python tools/generate_numbers.py --wikipedia-sections
```

- セクション取得キャッシュを更新したい場合: `--refresh-wikipedia-sections`
- ネットワーク無しで生成したい場合: `--offline`（キャッシュのみ使用）

特定の固有名詞を含む引用を優先したい場合は pins 設定で部分一致ピン留めできます:
- pins: `tools/wikipedia_ja_pins_v1.json`
重要度の採用閾値を数字ごとに調整したい場合は上書き設定を使います:
- overrides: `tools/wikipedia_ja_importance_overrides_v1.json`

Wikidata 連携の制御（任意）:

```powershell
python tools/generate_numbers.py --no-wikidata
python tools/generate_numbers.py --refresh-wikidata
```

Wikipedia（日本語）連携の制御（任意）:

```powershell
python tools/generate_numbers.py --no-wikipedia
python tools/generate_numbers.py --refresh-wikipedia
```

### 公開（リリース）

- 生成スクリプト/設定を更新 → `python tools/generate_numbers.py --wikipedia-sections` で全ページ再生成
- 内部リンクが壊れていないことを確認（例: `python tools/check_internal_links.py`）
- main に反映後、タグ（例: `vYYYY.MM.DD`）を作成して GitHub Release を作成（差分/変更点を記載）

## 参考リンク

- Wikipedia 数の記事（例）: https://ja.wikipedia.org/wiki/31
