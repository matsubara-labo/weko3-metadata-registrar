# インポート用ファイルの生成

`src/scripts/generate_metadata_imports.py` で、入力CSV/TSVからWEKOインポート用のTSVまたはZIPを生成します。事前に[初期設定](setup.md)を済ませてください。入力ファイルの仕様は [input-format.md](input-format.md) を参照してください。

```shell
uv run python src/scripts/generate_metadata_imports.py \
  --input path/to/input.csv \
  --output-dir output/zip_data \
  --chunk-size 50 \
  --zip
```

PowerShellでは行末の `\` を `` ` `` に置き換えてください。

## 引数

| 引数 | 必須 | 既定値 | 説明 |
|---|---:|---|---|
| `--input PATH` | 必須 | なし | 入力CSV/TSV |
| `--delimiter {auto,comma,tab}` | 任意 | `auto` | 入力ファイルの区切り文字。`auto` では、拡張子が `.tsv`/`.csv` ならそれに従い、それ以外はヘッダー行のタブとカンマの数から判定する |
| `--output-dir PATH` | 必須 | なし | 生成ファイルの出力先 |
| `--registration-config PATH` | 任意 | `config/metadata_registration.json` | [設定ファイル](setup.md#設定ファイル) |
| `--index-name NAME` | 任意 | 設定の `default_index` | 使用するIndex名。IndexIDは `indexes` から解決する |
| `--publish-date YYYY-MM-DD` | 任意 | 設定の `publish_date` | 公開日。この実行に限り設定値を上書きする |
| `--publish-status {public,private}` | 任意 | 設定の `publish_status`（未設定時は `public`） | 公開ステータス。この実行に限り設定値を上書きする |
| `--chunk-size N` | 任意 | `0` | 1ファイル当たりのレコード数。`0` は分割しない |
| `--zip` | 任意 | 無効 | TSVをインポート用ZIPにまとめる。`--keep-tsv` を指定しない限り、ZIPにまとめたTSVは削除する |
| `--keep-tsv` | 任意 | 無効 | `--zip` を指定しても、ZIPにまとめたTSVを残す |
| `--overwrite` | 任意 | 無効 | 出力先にある前回の生成ファイルを削除してから生成する（[詳細](#既存の生成ファイルがある場合)） |
| `--skip-invalid-rows` | 任意 | 無効 | エラーのある行を除外して生成し、除外した行を `invalid_rows.tsv` に出力する |
| `--strict-columns` | 任意 | 無効 | Item Typeにない列が入力にある場合、警告ではなくエラーとして停止する |
| `--title-fallback LABEL=COLUMN` | 任意 | なし | タイトル項目が空の行を `<接頭辞> (LABEL: <COLUMNの最初の値>)` で埋める。複数指定すると指定順に試す |
| `--title-fallback-prefix TEXT` | 任意 | `NoTitle` | `--title-fallback` で埋めるタイトルの接頭辞 |

- 拡張子と実際の区切り文字が異なるファイル（例: タブ区切りの `.csv`）は、`--delimiter tab` のように明示してください。
- `--chunk-size` は、1ファイルのレコード数を抑えて、一括登録時のエラーを避けるためのものです。JAIRO Cloud（WEKO3）の[v1.0.8](https://nii-auth.atlassian.net/wiki/spaces/JAIROCloudWEKO3/pages/43549582/2025-07-02+v1.0.8)で修正済みとの記載がありますが、設定することをお勧めします。

## エラーのある行

WEKOは、インポートファイル内に1件でもチェックエラーのあるレコードがあると、ファイル全体を取り込みません。そのため既定では、エラーのある行を `path:行番号: 内容` の形式で表示し（最大50行）、何も書き込まずに停止します。

`--skip-invalid-rows` を指定すると、エラーのない行だけで生成し、除外した行を出力先の `invalid_rows.tsv` に書き出します。このファイルはタブ区切りで、先頭の2列（`_invalid_row`、`_invalid_reason`）に行番号とエラー内容、続く列に元の値が入ります。

除外した行を登録するときは、`invalid_rows.tsv` の値を修正し、そのファイルを `--input` に指定して再実行します。先頭の2列は残したままで構いません。`invalid_rows.tsv` も前回の生成ファイルとして扱われるため、前回のZIPを登録して出力先から移動したあと、次のどちらかの方法で再実行してください。

- `--overwrite` を付けて再実行する（`--input` に指定した `invalid_rows.tsv` は削除されません）
- `invalid_rows.tsv` を出力先の外へ移動し、移動先のファイルを `--input` に指定して再実行する

元の入力ファイルで再実行すると、登録済みの行が重複して登録されます。

## タイトルが空の行を埋める

`--title-fallback` を指定すると、タイトルが空の行を別の列の値で埋めます。埋めたレコードは、WEKO上で接頭辞（既定 `NoTitle`）を検索すれば特定できます。LLMなどでタイトルを生成できなかったレコードを後から確認するときに便利です。

```shell
uv run python src/scripts/generate_metadata_imports.py \
  --input path/to/input.tsv \
  --output-dir output/zip_data \
  --title-fallback R=Title_r \
  --title-fallback G=Title_g
```

- この指定では、`Title_r` に値があればその最初の値を使い、`NoTitle (R: DNAxiS)` のようになります。`Title_r` が空なら `Title_g` の値を使い、`NoTitle (G: dnaxis)` のようになります（`Title_r` はAXIES2026のサンプルItem Typeにある列です）。
- 埋めるのは、JPCOARのタイトルにマッピングされた非表示でない項目のうち、最初の項目です（サンプルでは `Title`）。
- 指定したどの列にも値がない行は埋められず、タイトルが空のままになります。サンプルでは `Title` が必須項目のため、その行はエラーになります。
- 埋めた行は、生成後に `filled title: <path>:<行番号>: <タイトル>` と表示されます。

## 出力ファイル

| 条件 | TSV | ZIP |
|---|---|---|
| 出力が1ファイル | `output_write.tsv` | `import.zip` |
| 出力が2ファイル以上 | `output_write_001.tsv` など | `import_001.zip` など |

- `--chunk-size` を指定しても、レコード数がその値以下なら1ファイルになり、連番は付きません。
- 連番は3桁で、ファイル数が1000以上になると桁数が増えます。

TSVはWEKOのインポート形式（UTF-8 BOM付き）で出力し、ZIP内には `data/output_write[_NNN].tsv` として格納します。

### 既存の生成ファイルがある場合

出力先に前回の生成ファイル（上の表のファイルと `invalid_rows.tsv`）が残っていると、何も書き込まずに停止します。前回のファイルを出力先の外へ移動してから再実行してください（登録に成功したZIPは、既定で自動的に移動します）。

- `--overwrite` を指定すると、これらを削除してから生成します。**まだWEKOに登録していないZIPも削除される**ため注意してください。削除は入力の検査を通過したあとに行い、`--input` に指定したファイルは削除しません。`--skip-invalid-rows` を指定して有効な行が1行もなかった場合は、`invalid_rows.tsv` だけを置き換え、前回のTSV/ZIPは残します。
- 生成ファイル以外のZIP（例: `manual.zip`）は削除されず、警告が表示されるだけです。ただし登録コマンドは `--zip-dir`（既定 `output/zip_data`）内のすべてのZIPを登録するため、登録前に移動してください。

### 再生成したZIPと重複登録の防止

同じバージョンのツールで、同じ入力ファイル（内容と更新日時が同じ）と同じ設定（`--chunk-size` などの引数を含む）から生成したZIPは、毎回同じ内容になります。そのため、登録済みのZIPを再生成しても、[インポート台帳](register.md#インポート台帳)で登録済みと判定され、スキップされます。

入力ファイルを再保存したり、Gitでチェックアウトし直したりして更新日時が変わると、内容が同じでも別のZIPとして扱われます（更新日時は2秒単位で記録されます）。台帳で重複登録を防ぎたい場合は、入力ファイルに手を加えずに再生成してください。入力ファイルをコピーするときは、`cp -p` など更新日時を保つ方法を使ってください。

## 引数・設定から決まる列

次の列は、入力CSV/TSVの値ではなく、引数や設定から生成します。

| 列 | 値 |
|---|---|
| `.IndexID[0]` | 使用するIndex名に対応するIndexID（`indexes` から解決） |
| `.POS_INDEX[0]` | 使用するIndex名（`--index-name`、省略時は設定の `default_index`） |
| `.PUBLISH_STATUS` | `--publish-status`。省略時は設定の `publish_status`、それもなければ `public` |
| `PubDate` | `--publish-date`。省略時は設定の `publish_date` |
| `Keep/Upgrade Version` | `keep` |
| `#ID`, `URI`, `.FEEDBACK_MAIL[0]`, `.RESEAECHMAP_LINKAGE`, `.CNRI`, `.DOI_RA`, `.DOI` | 空欄 |
