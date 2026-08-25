# weko3-metadata-registrar

WEKOのItem TypeエクスポートとCSV/TSVデータから、メタデータ一括登録用のTSVまたはZIPを生成します。

## Development setup

```shell
uv sync --dev
uv run pre-commit install
```

コードチェックとテストは次のコマンドで実行できます。

```shell
uv run pre-commit run --all-files
PYTHONPATH=src uv run python -m unittest discover -s tests -v
```

## 設定

[config/metadata_registration.json](config/metadata_registration.json) に、環境ごとの値と利用するItem Typeエクスポートを設定します。

```json
{
  "weko_base_url": "https://133.167.95.87",
  "item_type_export": "../sample/config/ItemType_export_sample.zip",
  "indexes": {
    "S2ORC": "1623632832836",
    "PWCD": "1776751280302"
  },
  "default_index": "S2ORC",
  "publish_date": "2025-05-27",
  "default_languages": {
    "Title": "en",
    "Title_g": "en"
  }
}
```

- `item_type_export` の相対パスは、この設定ファイルがあるディレクトリを基準に解決されます。
- `indexes` はIndex名をキー、IndexIDを値として登録します。
- `default_index` はCLIで `--index-name` を省略したときに使用するIndex名です。
- `weko_base_url` とエクスポート内のItem Type IDから、Item Schema URLを組み立てます。
- `default_languages` は、言語子項目へ設定する既定値を入力列名ごとに指定します。

### WEKOインポート制御列

Item Typeのメタデータ項目ではない制御列は、次の方針で生成します。

| 列 | 登録値 | 属性 |
|---|---|---|
| `#ID`, `URI` | 空欄 | WEKOインポート形式の固定値 |
| `.IndexID[0]`, `.POS_INDEX[0]` | `indexes` / `default_index` | `Allow Multiple` |
| `.PUBLISH_STATUS` | `public` | `Required` |
| `.FEEDBACK_MAIL[0]`, `.RESEAECHMAP_LINKAGE`, `.CNRI`, `.DOI_RA`, `.DOI` | 空欄 | WEKOインポート形式の固定値 |
| `Keep/Upgrade Version` | `keep` | `Required` |
| `PubDate` | `publish_date` | Item Type ZIPの `render.meta_fix.pubdate.option`から取得 |

## Item Typeエクスポート

WEKOから機械的にエクスポートしたZIPを、そのまま `item_type_export` に指定します。手動での展開やJSON編集は不要です。

生成処理はZIP内のファイルを次のように使用します。

- `ItemType.json`: Item Type ID、項目順、項目名、内部キー、型、必須・非表示・複数可設定
- `ItemTypeName.json`: Item Type名

単一値、子要素を1つ持つ繰り返し項目、および「値1つ＋言語」の複合項目を扱います。値を入れる子要素が複数あり一意に決められないItem Typeは、誤ったTSVを生成せずエラーにします。

## 生成コマンド

リポジトリルートで実行します。

```shell
uv run python src/scripts/generate_metadata_imports.py \
  --input source_data/sample.csv \
  --output-dir output/zip_data \
  --registration-config config/metadata_registration.json \
  --chunk-size 50 \
  --zip
```

設定内の別Indexを選択する場合は、Index名を指定します。IndexIDは `indexes` から解決されます。

```shell
uv run python src/scripts/generate_metadata_imports.py \
  --input source_data/sample.csv \
  --output-dir output/zip_data \
  --index-name PWCD \
  --zip
```

`--publish-date` は設定値を一時的に上書きできます。公開状態はWEKO登録方針として常に `public`、Keep/Upgrade Versionは常に `keep` です。それ以外の固定制御値は、IndexID・Index名・PubDateを除いて空欄です。`--zip --keep-tsv` を指定すると、ZIP内に格納したTSVも出力ディレクトリに残します。

生成TSVはWEKOのインポート形式に合わせてUTF-8 BOM付きで出力されます。
