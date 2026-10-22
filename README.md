# weko3-metadata-registrar

CSV/TSV形式のメタデータから、WEKOの一括登録（インポート）に使うインポート用ZIPを生成し、SeleniumでWEKOへ登録するツールです。

```text
CSV/TSV ──(generate_metadata_imports.py)──> インポート用ZIP ──(selenium_auto_register.py)──> WEKO
```

## 前提条件

- Python 3.13、[uv](https://docs.astral.sh/uv/)
- Google Chrome（Selenium登録を行う場合）
- Item TypeをエクスポートできるWEKO環境と権限（[WEKO3](https://github.com/RCOSDP/weko.git) 2.0.0で動作確認済み。JAIRO Cloudや他のバージョンは未確認）

## 使い方

コマンドは、特に記載がない限りリポジトリルートで実行します。

1. **初期設定**: 依存パッケージのインストール、WEKO側の準備、設定ファイルと `.env` の編集を行います（[docs/setup.md](docs/setup.md)）。
2. **入力データの用意**: Item Typeの項目名に合わせたCSV/TSVを用意します（[docs/input-format.md](docs/input-format.md)、[サンプル](sample/AXIES2025/sourcedata_sample.tsv)）。
3. **ZIPの生成**（[docs/generate.md](docs/generate.md)）

   ```shell
   uv run python src/scripts/generate_metadata_imports.py --input path/to/input.csv --output-dir output/zip_data --chunk-size 50 --zip
   ```

4. **WEKOへの登録**（[docs/register.md](docs/register.md)）

   ```shell
   uv run python src/scripts/selenium_auto_register.py
   ```

   `output/zip_data` 内のZIPをファイル名順に登録し、結果を `output/import_results` に保存します。全件成功したZIPは `output/uploaded_zip_data` へ移動します。

エラーになった場合は [docs/troubleshooting.md](docs/troubleshooting.md) を参照してください。

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [setup.md](docs/setup.md) | 初期設定（インストール、WEKO側の準備、設定ファイル、認証情報） |
| [input-format.md](docs/input-format.md) | 入力CSV/TSVの書き方と仕様 |
| [generate.md](docs/generate.md) | 生成コマンドの引数と出力ファイル |
| [register.md](docs/register.md) | 登録コマンドの引数、登録結果の判定、インポート台帳 |
| [repair-control-chars.md](docs/repair-control-chars.md) | LLM生成データの制御文字の修復 |
| [troubleshooting.md](docs/troubleshooting.md) | 困ったとき |

## 関連論文

本リポジトリのコードは、以下の論文におけるメタデータの収載に用いたものです。収載されたメタデータは [https://scholar.jp](https://scholar.jp) で公開されています。

```bibtex
@article{axies2025,
  title   = {研究データのオープンアクセスを加速化する：生成AIを用いたメタデータ生成と機関リポジトリへの収載},
  author  = {渡邉 優 and 茂木 光志 and 松原 茂樹},
  journal = {大学ICT推進協議会年次大会論文集},
  volume  = {2025},
  number  = {},
  pages   = {702-708},
  year    = {2025},
  doi     = {10.24669/axies.2025.0\_702}
}
```
