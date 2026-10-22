# 困ったとき

## 生成時

| 症状 | 対処 | 詳細 |
|---|---|---|
| 生成が `path:行番号: ...` のエラーで停止する | 表示された行を修正するか、`--skip-invalid-rows` で除外する | [generate.md](generate.md#エラーのある行) |
| 出力先に既存ファイルがあって停止する | 前回の生成ファイルを出力先の外へ移動するか、`--overwrite` を指定する（未登録のZIPも削除される） | [generate.md](generate.md#既存の生成ファイルがある場合) |
| 生成が `value contains control character U+XXXX` のエラーで停止する | リストのセルなら修復スクリプトで前処理する。それ以外は手作業で修正するか `--skip-invalid-rows` で除外する | [repair-control-chars.md](repair-control-chars.md) |
| `unknown column ... will be ignored` と警告される | 列名をItem Typeの項目名に合わせる（`did you mean` の候補が表示されていれば参考にする）。識別用の列など、意図して含めた列なら無視してよい | [input-format.md](input-format.md#列名) |

## 登録時

| 症状 | 対処 | 詳細 |
|---|---|---|
| 自己署名証明書のWEKOで、ログイン画面が開けない、またはUI要素の待機がタイムアウトする | `--ignore-certificate-errors` を指定する（本番環境では使用しない） | [register.md](register.md#引数) |
| ZIPが登録されずにスキップされる | インポート台帳に記録済みのZIPです。WEKO上の登録状況を確認したうえで、`--allow-reimport` を指定して再登録する | [register.md](register.md#インポート台帳) |
| 登録結果が不明（`ImportOutcomeUnknownError`） | WEKO上で登録状況を手動で確認してから、必要な場合だけ再登録する | [register.md](register.md#エラー時の動作) |
| 一部のレコードの登録に失敗した | ZIP全体は再登録せず、`<ZIP名>_failed_rows.tsv` を修正して再登録する（成功したレコードは登録済み） | [register.md](register.md#登録に失敗したレコードの再登録) |
