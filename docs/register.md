# WEKOへの登録

`src/scripts/selenium_auto_register.py` で、生成したZIPをSeleniumでWEKOへ登録します。

```shell
# Chromeを表示して登録する
uv run python src/scripts/selenium_auto_register.py

# Chromeを画面に表示せず実行する
uv run python src/scripts/selenium_auto_register.py --headless
```

既定では `output/zip_data` 内のすべてのZIPをファイル名順に登録します。登録前に次を確認してください。

- `.env` の `WEKO_EMAIL` と `WEKO_PASSWORD` が対象環境の値である（[setup.md](setup.md#認証情報)）
- `output/zip_data` に今回登録するZIPだけが置かれている

## 引数

| 引数 | 既定値 | 説明 |
|---|---|---|
| `--base-dir PATH` | リポジトリルート | `.env` の場所と、入出力ディレクトリ・台帳の既定パスの基準。設定ファイルの既定パスは変わらない |
| `--weko-base-url URL` | 設定の `weko_base_url` | 登録先URL。この実行に限り設定値を上書きする。生成時と異なるWEKOを指定しないよう注意 |
| `--registration-config PATH` | `config/metadata_registration.json` | [設定ファイル](setup.md#設定ファイル) |
| `--selector-config PATH` | `config/weko_ui_selectors.json` | WEKO画面のUIセレクタ設定 |
| `--zip-dir PATH` | `output/zip_data` | 登録対象ZIPのディレクトリ |
| `--download-dir PATH` | `output/import_results` | インポート結果ファイルの保存先 |
| `--processed-zip-dir PATH` | `output/uploaded_zip_data` | 登録に成功したZIPの移動先 |
| `--failed-zip-dir PATH` | `output/failed_zip_data` | 登録に失敗したZIP・結果が不明なZIPの移動先 |
| `--ledger-path PATH` | `output/import_ledger.jsonl` | [インポート台帳](#インポート台帳)のパス |
| `--allow-reimport` | 無効 | 台帳に記録済みのZIPもスキップせずに登録する |
| `--headless` | 無効 | Chromeを画面に表示せず実行する |
| `--ignore-certificate-errors` | 無効 | TLS証明書エラーを無視する（下記の注意を参照） |
| `--limit N` | 制限なし | ファイル名順で先頭のN件だけを対象にする。台帳でスキップされるZIPも件数に含む |
| `--keep-zip-after-import` | 無効 | 登録に成功したZIPを移動せず元の場所に残す |
| `--delete-zip-after-import` | 無効 | 登録に成功したZIPを削除する（元に戻せない） |

> [!WARNING]
> `--ignore-certificate-errors` は、IPアドレスで接続する場合（`https://<IPアドレス>`）など、自己署名証明書を使うWEKOに接続するためのオプションです。証明書を検証しないため、接続先を取り違えても気づけません。正規の証明書を持つ本番環境では使用しないでください。

### タイムアウト

すべてミリ秒単位です。

| 引数 | 既定値 | 対象 |
|---|---:|---|
| `--ui-timeout-ms` | `45000` | 入力欄やボタンなど、個々のUI要素の待機 |
| `--post-login-timeout-ms` | `45000` | ログイン完了の待機 |
| `--load-timeout-ms` | `240000` | ZIPの読み込みと、Importボタンの有効化・クリックの待機 |
| `--import-timeout-ms` | `480000` | インポート完了の待機 |
| `--download-timeout-ms` | `120000` | 結果ファイルのダウンロード完了の待機 |

## 登録結果

インポートが完了すると、WEKOから結果ファイルをダウンロードし、`output/import_results` に `<ZIP名>_result.tsv`（WEKOの設定によっては `.csv`）として保存します。同名のファイルがある場合は、`_001` などの連番を付けます。

次の条件をすべて満たす場合だけ、登録に成功したとみなします。

- 結果ファイルのレコード数が、ZIP内のレコード数と一致する（1件以上）
- すべての行で、ステータスが `Done`、インポート結果が `Success` である（日本語のUIではそれぞれ `完了`、`成功`）

| 結果 | ZIPの扱い | 表示 |
|---|---|---|
| 成功 | `output/uploaded_zip_data` へ移動（`--keep-zip-after-import` / `--delete-zip-after-import` で変更可） | `result: success=<成功件数>/<件数>` |
| 失敗 | `output/failed_zip_data` へ移動し、残りのZIPは登録せずに終了 | 件数の集計、失敗した行（最大20行）の `No.`・`ItemID`・`Status`・`Result`、`ImportResultError` |

失敗したZIPでも、成功したレコードはWEKOに登録済みです。ZIP全体を再登録すると成功したレコードが重複するため、次の手順で失敗したレコードだけを再登録してください。

### 登録に失敗したレコードの再登録

失敗したレコードは、移動したZIPと同じディレクトリに `<ZIP名>_failed_rows.tsv` として書き出されます（同名のファイルがある場合は連番が付きます）。WEKOは失敗したレコードを登録しないため、このファイルの値を修正し、`data/` 配下に置いてZIPにすれば、そのレコードだけを再登録できます。

```shell
cd output/failed_zip_data
mkdir -p retry/data
cp import_001_failed_rows.tsv retry/data/output_write.tsv
(cd retry && uv run python -m zipfile -c ../import_001_retry.zip data)
mv import_001_retry.zip ../zip_data/
cd ../..
```

PowerShellでは次のように実行します。

```powershell
cd output/failed_zip_data
New-Item -ItemType Directory -Force retry/data | Out-Null
Copy-Item import_001_failed_rows.tsv retry/data/output_write.tsv
Push-Location retry; uv run python -m zipfile -c ../import_001_retry.zip data; Pop-Location
Move-Item import_001_retry.zip ../zip_data/
Set-Location ../..
```

登録コマンドは `output/zip_data`（`--zip-dir`）内のZIPだけを登録するため、作成したZIPをそこへ移動し、リポジトリルートに戻ってから登録します。

結果ファイルとZIPのレコード数が一致しない場合や、結果ファイルを解析できない場合など、結果の行とZIP内の行を対応付けられないときは、`<ZIP名>_failed_rows.tsv` は作成されません。WEKO上の登録状況と結果ファイルを確認してから、必要なレコードだけを再登録してください。

## エラー時の動作

| エラーの発生時点 | ZIPの扱い | 対処 |
|---|---|---|
| Importボタンを押す前（ログイン失敗、WEKOのチェックエラーなど） | 元の場所に残る | 原因を取り除いて再実行する |
| Importボタンを押した後（インポート完了待ちのタイムアウトなど） | `output/failed_zip_data` へ移動し、`ImportOutcomeUnknownError` で終了 | WEKO上で登録されたかを確認してから、必要な場合だけ再登録する |

Importボタンを押す前にブラウザとの接続が切れた場合は、ログインからやり直して、最大4回まで自動で試行します。Importボタンを押した後は、インポートが実行されたかを判別できないため、重複登録を避けるために自動では再試行しません。

## インポート台帳

同じデータの重複登録を防ぐため、各ZIPの登録状況を `output/import_ledger.jsonl`（JSON Lines、追記のみ）に記録します。各行には、ZIPのファイル名・SHA-256・ステータス（`started` / `succeeded` / `failed` / `unknown`）・記録日時などが入ります。

登録前に各ZIPのSHA-256を台帳と照合し、記録があればスキップします。ファイル名が変わっていても、ステータスが何であってもスキップします。途中で中断した実行（`started` だけが残った記録）も、登録済みの可能性があるためスキップします。

- WEKO上の登録状況を確認したうえで再登録する場合は、`--allow-reimport` を指定してください。
- 台帳が照合するのは、このツールで登録したZIPの内容だけです。WEKO上の既存アイテムとの重複は確認しません。
- 同じ入力から再生成したZIPがスキップされる条件は、[generate.md](generate.md#再生成したzipと重複登録の防止) を参照してください。
