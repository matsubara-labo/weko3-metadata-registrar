# weko3-metadata-registrar

WEKOのItem TypeエクスポートとCSV/TSV形式のソースデータから、メタデータ一括登録用のTSVまたはZIPを生成し、SeleniumでWEKOへ登録するツールです。

## 0. 利用の流れ

0. Item Typeの項目名に合わせたCSV/TSVを準備する
1. 初期設定を行う
2. WEKOインポート用ZIPを生成する
3. 生成したZIPをSeleniumでWEKOへ登録する

コマンドは、特に記載がない限りリポジトリルートで実行します。

(0のファイルは各自でメタデータを収集してください。形式は[サンプルファイル](./sample/AXIES2025/sourcedata_sample.tsv)をご参照ください。)


## 1. 初期設定

### 前提条件

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- Google Chrome（Selenium登録を行う場合）
- Item TypeをエクスポートできるWEKO環境と権限
  - (GitHub上で公開されている[WEKO3](https://github.com/RCOSDP/weko.git) 2.0.0で動作を確認しています。JAIRO Cloudや他のバージョンでの動作は確認していません。)


依存パッケージをインストールします。

```shell
uv sync
```

### Item Type の設定（インポート・エクスポート）

WEKO内でAdministration > Item Types > Metadataに移動し、Item Typeを設定してください。

同梱の `sample/AXIES2025/config/ItemType_export_sample.zip` は設定例です。WEKOにインポートして、設定ファイルとして利用できます。


別の項目を設定する場合は、Item Typeの設定を行ったうえで、sample/AXIES2025/configのZIPファイルをエクスポートしたZIPへ置き換えてください。（あるいは、configの中で、参照先のファイルパスを変更してください。）


### Index Tree の設定

WEKO内でAdministration > Index Tree > Edit Treeに移動し、Index Treeの設定を行ってください。
（詳細は省略します。公式のドキュメントをご参照ください）

### Workflow の設定

WEKO内でAdministration >  WorkFlow > FlowList・WorkFlow Listに移動し、WorkFlowを設定してください。
以下が設定例です。
![Flow List](./sample/AXIES2025/config/img/flowlist.png)

![WorkFlow List](./sample/AXIES2025/config/img/workflowlist.png)

### 設定

[config/metadata_registration.json](config/metadata_registration.json) に、対象WEKOとItem Typeに対応する値を設定します。

```json
{
  "weko_base_url": "https://weko.example.org",
  "item_type_export": "../sample/AXIES2025/config/ItemType_export_sample.zip",
  "indexes": {
    "Example": "1234567890"
  },
  "default_index": "Example",
  "publish_date": "2025-05-27",
  "default_languages": {
    "Title": "en",
    "Title_g": "en"
  }
}
```

| キー | 必須 | 用途 |
|---|---:|---|
| `weko_base_url` | 必須 | Item Schema URLの生成とSelenium登録先の既定値 |
| `item_type_export` | 必須 | WEKOからエクスポートしたItem Type のZIPファイルへのパス |
| `indexes` | 必須 | Index名をキー、IndexIDを値とする対応表 |
| `default_index` | 必須 | `--index-name`（後述） を省略した場合に使用するIndex名 |
| `publish_date` | 必須 | `--publish-date`（後述） を省略した場合に使用する公開日。`2025-05-27` のようにゼロ埋めした `YYYY-MM-DD` 形式の実在する日付で指定する（それ以外は設定エラー） |
| `default_languages` | 必須 | 言語子項目（`*_language`）を持つ項目の既定の言語コード（例: `en`）を、入力列名ごとに指定するオブジェクト。行ごとの言語は入力の `<列名>_lang` 列で上書きできる（後述）。タイトル項目のいずれにも、ここにも入力の `<列名>_lang` 列にも言語がなければ生成を停止する |
| `publish_status` | 任意 | `.PUBLISH_STATUS` に設定する公開ステータス。`public`（公開、既定値）または `private`（非公開）のみ指定可能 |
| `date_timezone` | 任意 | UTCオフセット付きの日時を日付に換算するときのタイムゾーン（IANA名）。既定値はWEKOの `BABEL_DEFAULT_TIMEZONE` と同じ `Asia/Tokyo`。未知の名前（`JST` など）は設定エラー |

`Index` はメタデータの登録先となるWEKO上のコレクションです。対象WEKOのIndex管理画面で登録先のIndex名とIndexIDを確認し、`indexes` に設定してください。
（メタデータの登録結果（[例](./sample/AXIES2025/ResearchArtifact(40001).tsv)や、ワークフローの設定画面から確認できます）

`item_type_export` の相対パスは、`metadata_registration.json` があるディレクトリを基準に解決されます。`default_index` には、`indexes` に存在する名前を指定してください。

### 認証情報

Selenium登録を行う場合は、`.env.sample` をリポジトリルートの `.env` へコピーします。

macOS/Linux:

```shell
cp .env.sample .env
```

PowerShell:

```powershell
Copy-Item .env.sample .env
```

`.env` の値を対象WEKOのアカウントに変更します。

```dotenv
WEKO_EMAIL=<login-email>
WEKO_PASSWORD=<login-password>
```

### 入力CSV/TSV

入力ファイルの列名は、Item Type ZIP内のメタデータ項目名と一致させます。列名は重複させないでください。同じ列名が複数あるとエラーになります。複数の値は、同名の列を並べずに1つのセルへリストとして記述します。次の例は、同梱されているサンプルItem Typeに対応するもので、すべてのItem Typeに共通する列名ではありません。

```csv
corpusid,Title,Title_g,Creator,PublicationYear_g
123,Main title,Alternative title,"['Alice', 'Bob']",2026-08-23T12:34:56
```

複数の値を持つ項目は、`"['Alice', 'Bob']"` のように各要素を引用符で囲んだPython形式のリストで記述します。リストとして解釈されるのは、前後の空白を除いた値が `[` で始まり `]` で終わるセルだけです。それ以外のセル（例: `1.50`、`0x1F`、`None`、`1, 2`）は文字列としてそのまま扱われます。`[draft] Title` のようにリストとして解釈できない値も、そのまま1つの文字列になります。リストの要素に文字列以外の値（例: `[1.50]`、`[['a', 'b']]`）を含めるとエラーになるため、`"['1.50']"` のように各要素を文字列として記述してください。仕様として、すべてのセルの値とリストの各要素について、前後の空白（半角・全角スペース、タブ、改行、NBSPなど）は取り除かれます。値の途中の空白や改行はそのまま残り、空白だけのセルは空値として扱われます。リストの要素のうち `None`、空文字（`''`）、空白だけの要素は取り除かれます。たとえば `"['a', '', ' ', 'b']"` は `a` と `b` の2要素になり、`"[None]"` や `"['']"` は空のセルと同じ扱いになるため、必須（`Required`）の項目では行単位のエラーになります。複数の値を持てるのは、Item Typeで配列（`array`）型の項目です（サンプルでは `Title`、`Creator`、`Contributor`、`Subject`、`Description`）。これらの項目は値ごとに `Title[0]`、`Title[1]` ... のように列が展開されます。配列型でない項目（サンプルでは `Title_g` など）にリストを記述した場合、空でない要素が1つだけなら値として使われますが、2つ以上あると行単位のエラー（`'<列名>' accepts a single value but got N`）になります。

日付の列（Item Typeで日付入力の項目）は、前後の空白を除いて日付部分を取り出したうえで、`YYYY-MM-DD`、`YYYY-MM`、`YYYY` のいずれかの形式であることを検査します。WEKOは日付を時刻とタイムゾーンを持たない文字列として保存するため、`2020-04-02T21:11:47+00:00` や `2023-03-09T19:58:55Z` のようにUTCオフセット付きの日時は、設定の `date_timezone`（既定値 `Asia/Tokyo`）の時刻に換算してから日付を取り出します（例はそれぞれ `2020-04-03`、`2023-03-10` になります）。オフセットのない日時は換算せず `T` 以降を取り除きます（例: `2020-01-02T10:00:00` や ` 2020-01-02 ` は `2020-01-02` になります）。月・日はゼロ埋めが必要で、`2020-1-2`、`2020/01/02`、存在しない日付（`2020-02-30`、`2020-13`）は行単位のエラー（`'<列名>' value '<値>' is not a WEKO date ...`）になります。この検査はWEKO自身の日付検証ルール（weko-search-ui の `validation_date_property`）と同じですが、WEKOがこのルールを適用するのは一部の日付項目だけです。そのため、WEKOでは受け付けられる、または変換される値（例: `YYYY/MM/DD`）も、このツールではエラーになることがあります。

ヘッダーにItem Typeの項目名と一致しない列があると、`warning: <path>:1: unknown column 'Titel' (did you mean 'Title'?) will be ignored` のように警告し、その列を無視して生成します。入力にない項目の中に似た項目名がある場合（大文字小文字や前後の空白の違いを含む）は候補を表示します。Item Typeの項目に対応する列が入力にない場合は `warning: <path>:1: missing column 'X'` と警告し、必須項目では末尾に `(Required)` を付けます（必須項目の列がない場合は、各行も必須項目が空のエラーになります）。Item Typeにない識別用の列などを意図して含めている場合、この警告は無視して構いません。`--strict-columns` を指定すると、未知の列があるときは警告ではなく、すべての未知の列を列挙して生成を停止します（不足している列は引き続き警告のみです）。`invalid_rows.tsv` の `_invalid_row` と `_invalid_reason` の列と、列名が空の列（pandasで保存したCSVのインデックス列など）は未知の列として扱わず、警告もエラーも出しません。

言語子項目（`*_language`）を持つ項目（サンプルでは `Title` と `Title_g`）は、入力に `<列名>_lang` 列（例: `Title_lang`、`Title_g_lang`）を追加すると、行ごとに言語コード（例: `ja`、`en`）を指定できます。各行の言語は、`<列名>_lang` 列のセルが空でなければその値、空なら `default_languages` のその列名の値、どちらもなければ空になります。複数の値を持つ項目では、`Title` に `"['T1', 'T2']"`、`Title_lang` に `"['ja', 'en']"` のように値と同じ順・同じ数の言語をリストで指定すると、`T1` に `ja`、`T2` に `en` が対応します。`ja` や `"['ja']"` のように言語を1つだけ指定した場合と、`default_languages` を使う場合は、その言語がすべての値に適用されます。値のリストと言語のリストはどちらも空の要素を取り除いてから、空でない値に順に対応付けられます（たとえば `Title` が `"['T1', '', 'T2']"`、`Title_lang` が `"['ja', 'fr', 'en']"` の場合は値2つに言語3つとなります）。言語の数が1つでも値の数とも一致しない場合は行単位のエラー（`'<列名>_lang' has N languages but '<列名>' has M value(s) ...`）になります。言語は値が空でない要素にだけ出力されます。言語コードの妥当性はこのツールでは検査しないため、WEKOが受け付けないコードはインポート時に拒否されることがあります。`<列名>_lang` 列は言語子項目を持つ項目についてだけ既知の列として扱い、それ以外の項目の `_lang` 列は未知の列として警告されます。Item Typeに `<列名>_lang` と同じ名前の項目があると区別できないため、生成はエラーで停止します。

WEKOは、JPCOARのタイトル（`title`、言語属性付き）にマッピングされた非表示（`Hide`）でない項目のいずれにも値と言語の組が1つもないレコードを `Title is required item.` として取り込みません。このツールはItem Type ZIP内の `ItemTypeMapping.json` の `jpcoar_mapping` からタイトル項目を判定し（このファイルがない場合はタイトル項目なしとして扱います）、非表示のタイトル項目は判定から除きます。タイトル項目がすべて非表示の場合と、どのタイトル項目も `default_languages` にも入力の `<列名>_lang` 列にも言語がない場合は、行を読む前に生成を停止します。値と言語の組を持つタイトル項目が1つもない行は行単位のエラー（`no title field (...) has both a value and a language ...`）になります。言語がどちらにもない項目（タイトル項目の一部を含む）は、その列が入力にあれば `warning: <path>:1: field 'X' has no language ...` と警告し、言語を空のまま生成します。

セルの値やリストの要素に制御文字（タブ・LF・CRを除くU+0000〜U+001FとU+007F）が含まれる行は、行単位のエラー（`'<列名>': value contains control character U+XXXX ...`）になります。NULはWEKOが読み込めずファイル全体の取り込みが `Internal server error` で失敗し、それ以外の制御文字は壊れた値のまま登録されるためです。前後の空白を取り除く前に検査するため、要素の先頭・末尾の制御文字も検出します。リストの要素にPython表記（`\x00` など）から生じた制御文字は、後述の `src/scripts/repair_control_chars.py` で修復できます。リストでないセルや、リストとして解析できないセル（生のNULバイトを含む場合など）の制御文字は修復スクリプトの対象外のため、エラーメッセージの案内に従って手作業で修正するか `--skip-invalid-rows` で除外してください。`\ud800` のような対になっていないサロゲートも、UTF-8で出力できないため同様に行単位のエラーになります。

出力TSVの1つのセルに入る値は131,072文字までです。WEKOはTSVの読み込み時にこれより長いセルを受け付けず、そのTSVのすべてのレコードが取り込めなくなるためです。リストの場合は要素ごとに数えます。この上限を超える値があると、生成はファイル名・行番号・列名を表示して停止します。行単位のエラー（`path:行番号:` 形式）の行番号はヘッダーを1行目として数えたレコード番号で、セル内に改行がある場合は物理的な行番号と一致しないことがあります。CSV/TSVとして読み取れない入力のエラー（`path: line N:` 形式）には物理的な行番号が表示されます。

サンプルファイルは[こちら](./sample/AXIES2025/sourcedata_sample.tsv)

### 入力データの前処理（制御文字の修復）

LLMで生成した入力では、`\u00e1` やLaTeXの `\beta` などのバックスラッシュがエスケープとして誤って解釈され、リストのセルに `'Moro-Vel\x00e1zquez'` のようなPython表記の制御文字が含まれることがあります。生成時にリストとして読み込むとNUL（U+0000）などの制御文字になり、WEKOはNULを含むファイルを読み込めず `Internal server error` で停止します。NUL以外の制御文字はWEKOが受け付けるため、壊れた値のまま公開されます。

`src/scripts/repair_control_chars.py` は、リストのセル（`[...]` のPythonリスト）の文字列要素について、壊れ方が1通りに決まるものだけを次の規則で機械的に戻し、残りを見える文字列にします。LLMの出力の内容（READMEとの表記の違いなど）は修正しません。

| 規則 | 変換 | 例 |
|---|---|---|
| R1 | 制御文字（タブ・LF・CRを除く）＋16進数2桁 → その番号の文字（文字・記号・数字の場合のみ） | `Moro-Vel\x00e1zquez` → `Moro-Velázquez` |
| R2 | `\x07` `\x08` `\x0b` `\x0c`＋英字 → `\a` `\b` `\v` `\f`＋英字 | `$\x08eta$` → `$\beta$` |
| R3 | タブ＋既知のLaTeXコマンド名（`\text...`、`tilde`、`theta` など）→ `\t`＋名前、CR＋英字 → `\r`＋英字 | `Mu<TAB>ilde{n}oz` → `Mu\tilde{n}oz` |
| R4 | 上記に当てはまらない制御文字 → `\xNN` という文字列 | `$\x12$` → `$\x12$`（文字として表示） |

R1は値に書かれた番号どおりに戻すため、LLMが誤った番号を書いた場合（例: READMEでは `Yi\u{g}it` の値が `YiĐit` になる）はそのまま残ります。本物のタブ（表やコードの区切り）とLF、LFの前のCRは変更しません。R1は、R2の対象の `\x07` `\x08` `\x0b` `\x0c` には適用しません（`\vec` や `\backslash` を別の文字にしないため）。要素の先頭・末尾の制御文字もR4の対象にします（生成時に空白として黙って取り除かれ、`\infty-Diff` が `iff` になるなど、壊れていることがわからなくなるため）。リストでないセルと、変更のないセルは元の表記のまま出力します。

```shell
uv run python src/scripts/repair_control_chars.py \
  --input path/to/input.tsv \
  --output path/to/input_repaired.tsv
```

変更した要素ごとに、行番号（ヘッダーを1行目とするレコード番号）、`--id-column`（既定 `corpusid`）の値、列名、リスト内の位置、適用した規則、変更前（`repr` 表記）、変更後を `<出力名>_repairs.tsv`（`--report` で変更可能）に書き出します。出力先や一覧が既にある場合は停止するため、置き換えるときは `--overwrite` を指定してください。

LaTeXの `\n` で始まるコマンド（`\nu`、`\nabla`、`\neq` など）も同じ原因でLF（改行）に変わる可能性がありますが、本物の改行と区別できないため変更しません。LFの直後に既知の `\n...` コマンド名が続く要素を、確認用に `<出力名>_review.tsv`（`--review` で変更可能）へ行番号・ID・列名・リスト内の位置・コマンド名・前後の文字列とともに書き出すので、手作業で確認してください（`\ne`、`\ni`、`\neg`、`\nexists`、`\nmid`、`\nparallel`、`\nsubset`、`\nsim`、`\ncong` は、折り返した文章の行頭の `e.g.`、`eg.`、`parallel` などと区別できないため対象外です）。

出力ファイルの更新日時は、既定で入力ファイルと同じにします（`--no-keep-mtime` で無効化）。ZIP内のTSVの日時は入力ファイルの更新日時から決まるため（「出力ファイル」を参照）、修復したファイルから同じ `--chunk-size` で生成し直しても、修復した行を含まないZIPは元のファイルから生成したZIPと同じSHA-256になり、インポート台帳で登録済みと判定されます。修復した行を含むZIPだけが新しいZIPとして登録されます。この性質を保つため、生成し直すときは `--chunk-size` などの設定を変えず、台帳（`--ledger-path`）も同じものを使ってください。

ただし、NUL以外の制御文字だけを含むZIPはWEKOが受け付けるため、修復前のファイルで既に登録されている場合があります。そのようなZIPは修復によってSHA-256が変わり、台帳では未登録と判定されて重複登録されます。修復の一覧の行番号から該当するZIP（`--chunk-size` が50なら `(行番号 - 2) // 50 + 1` 番目。生成時に `--skip-invalid-rows` で除外した行がある場合は、その分ずれるため当てはまりません）を求め、登録済みのものは再投入の対象から外してください。

## メタデータファイルの生成

### 基本コマンド

次の例では、50レコードごとに分割したWEKOインポート用ZIPを `output/zip_data` へ生成します。

```shell
uv run python src/scripts/generate_metadata_imports.py \
  --input path/to/input.csv \
  --output-dir output/zip_data \
  --chunk-size 50 \
  --zip
```

### 生成コマンドの引数

| 引数 | 必須 | 既定値 | 説明 |
|---|---:|---|---|
| `--input PATH` | 必須 | なし | ソースCSV/TSV |
| `--delimiter {auto,comma,tab}` | 任意 | `auto` | 入力ファイルの区切り文字。`comma` はカンマ、`tab` はタブ |
| `--output-dir PATH` | 必須 | なし | 生成ファイルの出力先 |
| `--registration-config PATH` | 任意 | `config/metadata_registration.json` | 登録設定JSON |
| `--index-name NAME` | 任意 | 設定の `default_index` | 使用するIndex名。IndexIDは `indexes` から解決する |
| `--publish-date YYYY-MM-DD` | 任意 | 設定の `publish_date` | 公開日を一時的に上書きする。`YYYY-MM-DD` 形式の実在する日付でない場合はエラー |
| `--publish-status {public,private}` | 任意 | 設定の `publish_status`（未設定時は `public`） | 公開ステータスを一時的に上書きする |
| `--chunk-size N` | 任意 | `0` | 1ファイル当たりのレコード数。`0` は分割しない |
| `--zip` | 任意 | 無効 | TSVに加えて登録用ZIPを生成する |
| `--keep-tsv` | 任意 | 無効 | `--zip` 使用時もZIP化前のTSVを残す |
| `--overwrite` | 任意 | 無効 | 出力先にある既存の生成ファイルをすべて削除してから生成する |
| `--skip-invalid-rows` | 任意 | 無効 | エラーのある行を除外して生成し、除外した行を `invalid_rows.tsv` に出力する |
| `--strict-columns` | 任意 | 無効 | Item Typeにない列が入力にある場合、警告ではなくエラーとして停止する |
| `--title-fallback LABEL=COLUMN` | 任意 | なし | タイトル項目が空の行を `<接頭辞> (LABEL: <COLUMNの値>)` で埋める。複数指定すると指定順に試す（後述） |
| `--title-fallback-prefix TEXT` | 任意 | `NoTitle` | `--title-fallback` で埋めるタイトルの接頭辞 |

`--delimiter auto` では、拡張子が `.tsv` ならタブ、`.csv` ならカンマとして読み込みます。それ以外の拡張子（`.txt` や拡張子なしなど）では、ヘッダー行（1行目）のタブとカンマの数で判定し、タブの方が多ければタブ、それ以外はカンマとして扱います。ヘッダーにItem Typeの項目名と一致する列が1つもない場合は、区切り文字の誤りとみなして生成を停止します。拡張子と実際の区切り文字が異なるファイル（例: タブ区切りの `.csv`）は `--delimiter tab` のように明示してください。

`--zip` を指定しない場合はTSVだけを生成し、TSVは常に残ります。`--zip` を指定して `--keep-tsv` を指定しない場合、TSVはZIPへ格納した後に削除されます。

行単位のエラー（必須項目が空、リストの要素が文字列でない、日付の形式が不正、セルが長すぎるなど）がある場合、既定では入力全体を検査してエラーのある行をすべて `path:行番号: 内容` の形式で表示し（最大50行。それ以上は `... and N more`）、ファイルを何も書き込まずに停止します。WEKOはインポートファイル内に1件でもチェックエラーのあるレコードがあるとファイル全体を取り込まないため、既定ではすべての行が正しい場合だけ生成します。ヘッダーの誤りやCSV/TSVとして読み取れない入力など、ファイル全体に関わるエラーは最初の1件で停止します。

`--skip-invalid-rows` を指定すると、エラーのない行だけで生成し、除外した行を出力先の `invalid_rows.tsv` に書き出して `skipped <件数> invalid row(s); see <パス>` と表示します。`invalid_rows.tsv` はUTF-8 BOM付きのタブ区切りで、1行目は `_invalid_row`、`_invalid_reason` と入力ファイルの列名、2行目以降は除外した行の行番号、エラー内容、入力されていた元の値です。

除外した行を登録し直すときは、`invalid_rows.tsv` の値を修正し、修正した行だけを入力として再実行してください。元の入力ファイルで再実行すると、生成済みのZIPで登録した行が重複して登録されます。`invalid_rows.tsv` はそのまま `--input` に指定できます（`_invalid_row` と `_invalid_reason` の列は生成時に無視されます）。出力先に前回の `invalid_rows.tsv` が残っていると生成は停止するため、移動・削除するか `--overwrite` を指定してください。`--input` に指定したファイルは、出力先にあっても `--overwrite` で削除されません。ただし修正後もエラーが残る行がある場合、そのファイルは新しい `invalid_rows.tsv` で上書きされます。

エラーのある行がない場合、`invalid_rows.tsv` は作成されません。すべての行にエラーがある場合は `invalid_rows.tsv` だけを書き出し、TSV/ZIPは生成せずに終了コード1で終了します。このとき `--overwrite` を指定していても、前回生成したTSV/ZIPは削除されず、前回の `invalid_rows.tsv` だけが置き換えられます。

`--title-fallback` を指定すると、タイトル項目が空（空白だけのセルや、`[]`・`['']`・`[None]` のように空でない要素がないリストを含む。必須項目の空判定と同じ）の行を、指定した列の値で埋めます。対象はJPCOARのタイトルにマッピングされた非表示でない項目のうち、Item Typeで最初の項目です（サンプルでは `Title`）。指定した順に列を調べ、最初に値のある列の最初の要素を使って `<接頭辞> (LABEL: <値>)` とします。たとえば次の指定では、`Title_r` があれば `NoTitle (R: DNAxiS)`、なければ `NoTitle (G: dnaxis)` になります。LLMなどでタイトルを生成できなかったレコードを、`NoTitle` で検索して特定できます。

```shell
uv run python src/scripts/generate_metadata_imports.py \
  --input path/to/input.tsv \
  --output-dir output/zip_data \
  --title-fallback R=Title_r \
  --title-fallback G=Title_g
```

すべてのTSV/ZIPを書き出した後に、埋めた行を `filled title: <path>:<行番号>: <タイトル>` と表示し、最後に件数を表示します（エラーのある行があって生成を停止した場合や、書き出しの途中でエラーになった場合は表示しません。`--skip-invalid-rows` では除外されなかった行だけを表示します）。埋めたタイトルの言語は、通常の値と同じく `<列名>_lang` 列または `default_languages` から決まります。指定する列はItem Typeの項目でなくても構いません。Item Typeにない列でも未知の列として警告されず、`--strict-columns` でも停止しません。指定した列が入力のヘッダーにない場合は、行を読む前に生成を停止します。どの列にも値がない行は埋めず、従来どおり必須項目が空の行単位のエラーになります。`invalid_rows.tsv` には埋める前の入力値を出力します。

`--chunk-size`は一括登録時のエラー回避のためのものです。[v1.0.8の修正](https://nii-auth.atlassian.net/wiki/spaces/JAIROCloudWEKO3/pages/43549582/2025-07-02+v1.0.8)によって改修されたと思われますが、設定する事をお勧めします。

### 出力ファイル

| 条件 | TSV | ZIP |
|---|---|---|
| 分割なし | `output_write.tsv` | `import.zip` |
| 分割あり | `output_write_001.tsv` など | `import_001.zip` など |

`--skip-invalid-rows` で除外した行がある場合は、除外した行の一覧として `invalid_rows.tsv` も出力します。ZIP内ではTSVを `data/output_write[_NNN].tsv` として格納します。入力にレコードがない場合、ファイルは生成されません。生成TSVはWEKOのインポート形式に合わせてUTF-8 BOM付きで出力されます。

ZIPは入力ファイルと設定から一意に決まるように書き出します。ZIP内のTSVの日時には入力ファイル（`--input`）の更新日時をUTCで記録し（ZIPの仕様により2秒単位に切り捨て。1980年より前は1980-01-01 00:00:00、2107年より後は2107-12-31 23:59:58として記録）、権限などその他の属性には固定値を使い、圧縮結果がzlibの実装によって変わらないようTSVを無圧縮で格納します。そのため、同じ入力ファイル（内容と更新日時が同じ）・同じ設定から再生成したZIPは、生成日時や出力先、OS・Python・zlibが異なっても通常は同じSHA-256になり、登録時にインポート台帳で登録済みと判定されて `--allow-reimport` を指定しない限りスキップされます。入力の行が異なる場合や、`publish_date`・`publish_status`・`--chunk-size` などの設定の違いによりZIPに格納されるTSV（ファイル名を含む）が変わる場合は、別のSHA-256になります。

入力ファイルをコピー・再保存したり、Gitで再チェックアウトしたりすると、内容が同じでも更新日時が変わるためSHA-256も変わり、台帳は同じデータのZIPとして認識しなくなります。台帳による重複登録防止に頼る場合は、生成から再生成までの間に入力ファイルに手を加えないでください。FAT/exFATなど更新日時をローカル時刻で保存するファイルシステム上の入力は、タイムゾーン設定の異なる環境（例: WindowsとWSL）では更新日時がずれ、SHA-256が一致しないことがあります。`invalid_rows.tsv` を入力にして再生成し、なおエラーのある行が残った場合は `invalid_rows.tsv` が書き直されるため、その更新日時が変わり、次に同じファイルから生成するZIPのSHA-256も変わります。

無圧縮のためZIPのサイズはTSVとほぼ同じになり、圧縮する場合より大きくなりますが、WEKOはそのまま受け付けます。

この方式に変更する前に生成したZIPは、生成時のTSVの更新日時を含んでいたため、同じデータから現在のバージョンで再生成したZIPとはSHA-256が一致しません。以前のZIPで登録済みのデータを再生成した場合、台帳ではスキップされないため、台帳とWEKO上の登録状況を手動で確認してから登録してください。

出力先ディレクトリの直下に `output_write.tsv`、`output_write_<数字>.tsv`、`import.zip`、`import_<数字>.zip`、`invalid_rows.tsv` のいずれかが既にある場合、既定では何も書き込まずにエラーで停止します。前回の生成ファイルを移動するか登録してから再実行してください。`--overwrite` を指定すると、これらの既存ファイルを分割数にかかわらずすべて削除してから生成し、削除したファイルを `removed <パス>` として表示します。まだWEKOに登録していないZIPも削除されるため注意してください。入力の読み込みでエラーになって停止した場合や入力にレコードがない場合は、既存ファイルを削除しません。それ以外のファイルやサブディレクトリは対象外です。ファイル名の大文字・小文字は区別しません（例: `IMPORT.ZIP` も対象）。

`--overwrite` は新しいファイルを書き込む前に既存ファイルを削除します。削除後の書き込みに失敗した場合（ディスク容量不足、ファイルのロックなど）、出力先には前回のファイルが残らないことがあります。

出力先にある上記以外のZIP（例: `manual.zip`）は削除も停止の対象にもならず、生成後に `warning: <パス> is not a generated file ...` と警告を表示するだけです。登録処理は `--zip-dir` 内のすべての `*.zip` を登録対象にするため、その出力先を `--zip-dir` として使う場合は事前に移動してください。

登録時に `--keep-zip-after-import` を指定するとZIPが `output/zip_data` に残るため、同じ出力先へ再生成するには `--overwrite` が必要です。


## WEKOへの登録

### 登録前の確認

- `.env` の `WEKO_EMAIL` と `WEKO_PASSWORD` が対象環境の値である
- `output/zip_data` に今回登録するZIPだけが置かれている

生成時のItem Schema URLには、登録設定の `weko_base_url` が常に使われます。一方、Seleniumの登録先URLは次の優先順位で決まります。

```text
--weko-base-url
  > metadata_registration.json の weko_base_url
```

環境変数や `.env` の `WEKO_URL` は参照されません。CLIでURLを上書きする場合は、生成時と登録時が異なるWEKO環境になっていないことを確認してください。

### 基本コマンド

Chromeを表示して登録します。

```shell
uv run python src/scripts/selenium_auto_register.py
```

Chromeを画面に表示せず実行する場合は、`--headless` を指定します。

```shell
uv run python src/scripts/selenium_auto_register.py --headless
```

既定では `output/zip_data` 内のすべてのZIPをファイル名順に登録します。

### 登録コマンドの引数

| 引数 | 既定値 | 説明 |
|---|---|---|
| `--base-dir PATH` | リポジトリルート | `.env` と既定入出力ディレクトリの基準 |
| `--weko-base-url URL` | 登録設定の `weko_base_url` | Seleniumの登録先URLを一時的に上書きする |
| `--registration-config PATH` | `config/metadata_registration.json` | 登録設定JSON |
| `--selector-config PATH` | `config/weko_ui_selectors.json` | WEKO画面のUIセレクタ設定 |
| `--zip-dir PATH` | `output/zip_data` | 登録対象ZIPのディレクトリ |
| `--download-dir PATH` | `output/import_results` | WEKOから取得するインポート結果の保存先 |
| `--processed-zip-dir PATH` | `output/uploaded_zip_data` | 登録済みZIPの移動先 |
| `--failed-zip-dir PATH` | `output/failed_zip_data` | 失敗・要確認ZIP（インポート結果に失敗が含まれるZIP、またはImport後に結果を確認できなかったZIP）の移動先 |
| `--ledger-path PATH` | `output/import_ledger.jsonl` | インポート台帳（JSON Lines、追記のみ）のパス |
| `--allow-reimport` | 無効 | 台帳に記録済みのZIPもスキップせずに登録する |
| `--headless` | 無効 | Chromeを画面に表示せず実行する |
| `--ignore-certificate-errors` | 無効 | TLS証明書エラーを無視する（自己署名証明書のWEKO向け。後述） |
| `--limit N` | 制限なし | ファイル名順の先頭N件だけ登録する。0以上の整数のみ指定可能 |
| `--keep-zip-after-import` | 無効 | 全件登録に成功したZIPを元の場所に残す（`--delete-zip-after-import` と同時指定不可） |
| `--delete-zip-after-import` | 無効 | 全件登録に成功したZIPを削除する（`--keep-zip-after-import` と同時指定不可） |

`--zip-dir`、`--download-dir`、`--processed-zip-dir`、`--failed-zip-dir`、`--ledger-path` の既定値は、`--base-dir` を基準に解決されます。明示的に指定したパスは、実行時のカレントディレクトリを基準に解決されます。

> [!WARNING]
> 既定ではTLS証明書を検証します（以前のバージョンでは常に証明書エラーを無視していました）。`https://<IPアドレス>` のように自己署名証明書を使うWEKOへ接続する場合は、`--ignore-certificate-errors` を指定してください。このオプションはChromeに `--ignore-certificate-errors` と `--allow-insecure-localhost` を渡し、接続先の取り違えにも気づけなくなるため、正規の証明書を持つ本番環境に対しては使用しないでください。

### タイムアウト引数

すべてミリ秒単位です。各値はその工程全体の待機時間の上限で、UIセレクタの候補数では分割されません。候補は定期的に先頭から順に確認し、最初に条件を満たした要素を使います。

| 引数 | 既定値 | 対象 |
|---|---:|---|
| `--ui-timeout-ms` | `45000` | 入力欄やボタンなど、個々のUI要素の待機 |
| `--post-login-timeout-ms` | `45000` | ログイン完了の待機 |
| `--load-timeout-ms` | `240000` | ZIP読込みとインポートボタン有効化の待機 |
| `--import-timeout-ms` | `480000` | インポート完了の待機 |
| `--download-timeout-ms` | `120000` | 結果ファイルのダウンロード完了待機 |

Importボタンのクリックを試みる前にWebDriverの切断と判定された場合に限り、ログインからやり直して1ファイルにつき最大4回試行します。その他のエラーでは処理を中断し、未処理のZIPはそのまま残ります。

WEKO画面にエラー表示（インポート実行中、Celery停止、サーバ内部エラーなど）が出た場合や、Checkタブでチェックエラーが1件以上ある場合は、タイムアウトを待たずに即座に処理を中断します。チェックエラーの場合は、エラーのある行番号と内容をエラーメッセージに出力します。Importボタンのクリック前にこれらが発生した場合、対象ZIPは元の場所に残ります。

### Import後のエラー（要手動確認）

Importボタンのクリックを試みた後は、クリックがWEKOに届いたかどうかを判別できないため、自動再試行を行いません。クリック以降（インポート完了待機、結果のダウンロードとその待機・タイムアウトを含む）に発生したエラーは、WebDriverの切断であっても `ImportOutcomeUnknownError` として扱います。このとき対象ZIPを失敗・要確認ZIPとして `output/failed_zip_data`（`--failed-zip-dir` で変更可能）へ移動し、登録結果が不明であることを表示して処理を中断します。重複登録を避けるため、WEKO上で該当アイテムが登録されたかどうかを手動で確認してから、必要な場合だけ再投入してください。

### インポート台帳と再実行時のスキップ

同一データの重複登録を防ぐため、各ZIPの投入状況を追記専用のインポート台帳 `output/import_ledger.jsonl`（`--ledger-path` で変更可能）に記録します。台帳はJSON Lines形式で、1行が1件の記録です。各行は書き込むたびにディスクへ同期します。

| キー | 内容 |
|---|---|
| `timestamp` | 記録日時（ローカル時刻、UTCオフセット付きISO 8601） |
| `zip_name` | ZIPのファイル名 |
| `sha256` | ZIPファイル内容のSHA-256 |
| `status` | `started`（Importボタンのクリック直前）、`succeeded`（結果検証に成功）、`failed`（結果検証に失敗）、`unknown`（Import後のエラーで結果不明） |
| `result_path` | 結果ファイルのパス（ある場合のみ） |
| `detail` | エラー内容などの補足（ある場合のみ） |

各ZIPの登録前にSHA-256を計算し、同じ内容の記録が台帳にあれば、ファイル名が変わっていてもそのZIPを登録せずにスキップします（ステータスは問いません）。スキップ時は、前回のステータスと記録日時を表示し、ZIPは移動しません。`started` だけが残っている記録は、前回の実行が途中で中断された（Ctrl+Cなど）ことを示し、登録済みの可能性があるため同様にスキップします。WEKO上の状況を確認したうえで再登録する場合は、`--allow-reimport` を指定してください。`--limit N` はスキップ対象を含むファイル名順の先頭N件に適用され、終了時にスキップした件数を表示します。台帳の空行や解析できない行は警告を表示して読み飛ばします。

生成ツールはZIPを入力ファイルと設定から一意に決まるように書き出すため（「出力ファイル」を参照）、更新日時を含め変更していない同じ入力ファイルから再生成したZIPも登録済みとしてスキップされます。

WEKO上の既存アイテムを識別子（`corpusid` など）で検索して重複を確認する機能は実装していません。台帳は、このツールで投入したZIPの内容だけを照合します。

### 登録後のファイル

インポートが完了すると、WEKOのResultタブからダウンロードした結果ファイル（TSV、またはWEKOの設定によりCSV）を `output/import_results`（`--download-dir` で変更可能）に保存し、その内容を検証します。結果ファイルはZIPと対応が取れるように `<ZIP名>_result.tsv`（例: `import_001.zip` なら `import_001_result.tsv`）へ名前を変更します。同名のファイルがある場合は `import_001_result_001.tsv` のように連番を付け、上書きしません。インポート台帳の `result_path` には変更後のパスを記録します。次の条件をすべて満たす場合だけ、ZIPの登録に成功したとみなします。

- 結果ファイルに1行以上のレコードがある
- 結果ファイルのレコード数が、ZIP内のTSVに含まれるデータ行数（先頭セルが `#` で始まらない行）と一致する
- すべての行のステータスが `Done`（`完了`）、インポート結果が `Success`（`成功`）である

全件成功したZIPは、指定したオプションに応じて次のように処理し、`result: success=<成功件数>/<件数>` を表示します。

| オプション | 全件登録に成功したZIP |
|---|---|
| どちらも指定しない | `output/uploaded_zip_data` へ移動 |
| `--keep-zip-after-import` | 元のディレクトリに残す |
| `--delete-zip-after-import` | 削除する |

`--delete-zip-after-import` による削除は元に戻せません。`--keep-zip-after-import` と `--delete-zip-after-import` は同時に指定できず、両方を指定するとコマンドはエラーで終了します（`WekoImportConfig` で両方を有効にして `run_import` を呼んだ場合も、ZIPを処理する前に `ValueError` になります）。

失敗行がある場合、件数が一致しない場合、または結果ファイルを解析できない場合は、上記のオプションにかかわらずZIPを削除せず、元のディレクトリにも残さずに `output/failed_zip_data`（`--failed-zip-dir` で変更可能）へ移動します。同名のファイルがある場合は連番を付けて移動します。このとき成功件数・失敗件数・期待件数と、失敗行（最大20行）の No.、Item ID、ステータス、インポート結果を表示し、`ImportResultError` で処理を中断します。この場合は再試行しません。

結果ファイルで失敗（ステータスが `Done`/`完了` かつ結果が `Success`/`成功` 以外）となったレコードは、移動したZIPと同じディレクトリに `<ZIP名>_failed_rows.tsv`（例: `import_001_failed_rows.tsv`）として書き出し、`failed rows: <件数> row(s) written to <パス>` と表示します。このファイルはZIP内のTSVのヘッダー5行と失敗したレコードの行だけからなるWEKOインポート形式のTSV（UTF-8 BOM付き）で、結果ファイルの No. をZIP内のTSVのデータ行の順番（1始まり）として対応付けています。WEKOは失敗したレコードの登録を取り消すため（通常は登録されていません）、値を修正したうえで `data/` 配下に置いたZIPにすれば、そのレコードだけを再投入できます。

```shell
cd output/failed_zip_data
mkdir -p retry/data
cp import_001_failed_rows.tsv retry/data/output_write.tsv
(cd retry && python -m zipfile -c ../import_001_retry.zip data)
```

結果ファイルの行数がZIP内のレコード数と一致しない場合は、失敗行ファイルを作成せず `could not write failed rows: ... cannot be matched to records` と表示します。WEKOは取り込み対象から外したレコードを詰めて番号を振るため、件数が一致しないと No. とレコードの対応が取れないからです。この場合と結果ファイルを解析できない場合は、WEKO上の登録状況と結果ファイルを確認してから、必要なレコードだけを再投入してください。失敗行ファイルと同名のファイルがすでにある場合は、上書きせず `import_001_failed_rows_001.tsv` のように連番を付けます。

コンソールに `imported=<zip-path> result=<結果ファイルのパス>` が表示され、結果ファイルが保存されていることを確認してください。登録対象がない場合は `No zip files were found to import.` と表示して終了します。登録対象のZIPがあっても `--limit 0` を指定した場合は、`No zip files were imported because --limit 0 was given.` と表示して終了します。登録対象のZIPがすべて台帳によりスキップされた場合は、`No zip files were imported; <件数> zip file(s) were skipped because they are already in the import ledger.` と表示して終了します。

## 生成物の仕様

### WEKOインポート制御列

Item Typeのメタデータ項目ではない制御列は、次の方針で生成します。

| 列 | 登録値 | 属性 |
|---|---|---|
| `#ID`, `URI` | 空欄 | WEKOインポート形式の固定値 |
| `.IndexID[0]`, `.POS_INDEX[0]` | `indexes` / 選択したIndex名 | `Allow Multiple` |
| `.PUBLISH_STATUS` | `--publish-status` / 設定の `publish_status`（既定値 `public`） | `Required` |
| `.FEEDBACK_MAIL[0]`, `.RESEAECHMAP_LINKAGE`, `.CNRI`, `.DOI_RA`, `.DOI` | 空欄 | WEKOインポート形式の固定値 |
| `Keep/Upgrade Version` | `keep` | `Required` |
| `PubDate` | `publish_date` | Item Type ZIPの `render.meta_fix.pubdate.option` から取得した属性 |

## 関連論文等

本レポジトリのコードは、以下の論文におけるメタデータの収載に用いたものです。
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

収載されたメタデータは以下で公開されています。
[https://scholar.jp](https://scholar.jp)