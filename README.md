# CheatSheet of Numbers (0-999)

0〜999 の数字について、数学的な性質と、科学/文化に関する一次情報への導線をまとめたチートシート集です。

- 入口: [index.md](index.md)
- 個別ページ: `numbers/` 配下（基本は 1 数字 = 1 ファイル）
- 一部の規格・コード情報は Wikidata（CC0）から自動取得して補強します

## 方針（公開に耐えるための注意）

- 外部サイトの本文を長文転載しません（要約＋参照リンク中心）。
- 引用する場合は短くし、出典 URL を必ず添えます。

## ライセンス

本リポジトリは **CC BY-SA 4.0** です。詳細は [LICENSE](LICENSE) を参照してください。

- Wikidata の構造化データは CC0（パブリックドメイン相当）です。取得したデータの出典は各ページの Wikidata リンクを参照してください。

## 生成について

このリポジトリの `numbers/` 以下は、`tools/generate_numbers.py` で生成できます。

```powershell
"D:/VisualStudio Code Userfile/ChearSheet-of_Numbers/.venv/Scripts/python.exe" tools/generate_numbers.py
```

Wikidata 連携の制御（任意）:

```powershell
"D:/VisualStudio Code Userfile/ChearSheet-of_Numbers/.venv/Scripts/python.exe" tools/generate_numbers.py --no-wikidata
"D:/VisualStudio Code Userfile/ChearSheet-of_Numbers/.venv/Scripts/python.exe" tools/generate_numbers.py --refresh-wikidata
```

## 参考リンク

- Wikipedia 数の記事（例）: https://ja.wikipedia.org/wiki/31
