# DBP-BrewerExample-Movie

このリポジトリは，動画内の変化が少ない箇所をトリミングし，指定されたコーデックに変換するデータ醸造プログラムです．
JSON-LD 形式の醸造需要データを受け取り，指定されたデータソースからデータを読み込み，動画変換処理を行います．
醸造結果は指定された保存先に保存されます．

## Build

```bash
docker build --no-cache -t dbp-brewer-example-movie .
```

## Run

```bash
docker run -it \
  -v <input_video_directory>:/input_in_docker \
  -v <output_video_directory>:/output_in_docker \
  dbp-brewer-example-movie \
  "<brewing_demand_json_ld>"
```

### パラメータ説明

- `<input_video_directory>`: 入力動画ファイルが格納されているホストマシン上のディレクトリパス
- `<output_video_directory>`: 処理済み動画を保存するホストマシン上のディレクトリパス
- `<brewing_demand_json_ld>`: JSON-LD形式の醸造需要データまたはそのURL

## Kintoneへのログ記録（オプション）

動画醸造（トリミング・再エンコード）の結果を Kintone に記録できます。
レコード構造・挙動は [dbp-video-brewer(TRUSCO)](https://github.com/exdata-inc/dbp-video-brewer) と**同一**です。
本機能は**オプション**であり、有効化しない限り従来どおり動作します。

### レコード構造

`camera` × `year_month` ごとに **1レコード**を作成し、その中の**サブテーブル `table`** に
動画1本ごとの行を追記していきます（既存レコードがあれば追記、無ければ新規作成）。

**トップレベル**（`depo` / `camera` / `year_month` でレコードを一意に識別）

| フィールドコード | 型 | 内容 |
| --- | --- | --- |
| `depo` | 文字列（1行） | 拠点（醸造引数 `depo`） |
| `camera` | 文字列（1行） | カメラ識別子（入力パスの `camera*` を抽出） |
| `year_month` | 文字列（1行） | 処理対象月（`%Y-%m`） |
| `semantipack_metadata` | 文字列（複数行） | 予約（`{}`） |
| `dbp_metadata` | 文字列（複数行） | 予約（`{}`） |
| `note` | 文字列（複数行） | 予約（空） |
| `table` | テーブル | 動画ごとの行（下記） |

**サブテーブル `table`（動画1本 = 1行）**

| フィールドコード | 型 | 内容 |
| --- | --- | --- |
| `path` | 文字列（1行） | 出力動画のフルパス（**ホストから見たパス**。Docker実行時はコンテナ接頭辞 `/output_in_docker` を除去） |
| `original_size_0` | 文字列（1行） | 入力サイズ（MB, 小数） |
| `compressed_size_0` | 文字列（1行） | 出力サイズ（MB, 小数） |
| `record_started_at` | 文字列（1行） | 撮影開始時刻（ffprobe の creation_time、無ければ処理時刻） |
| `record_finished_at` | 文字列（1行） | 撮影終了時刻（creation_time + 長さ、任意） |
| `ip` | 文字列（1行） | 入力のマウント元IP（findmnt、取得不可なら `unknown`） |
| `note_video` | 文字列（複数行） | **本リポジトリで処理を一意に再現できるJSON**（下記） |
| `thumbnail_img_path` | 文字列（1行） | サムネイル画像のパス（ffmpeg、任意。`path` と同じくホストから見たパス） |
| `url` | 文字列（1行） | 予約（空） |
| `semantipack_metadata_video` | 文字列（複数行） | 予約（`{}`） |
| `dbp_metadata_video` | 文字列（複数行） | 予約（`{}`） |

`note_video` は、入力パス・醸造引数（`threshold` / `window_threshold` / `codec` / `do_trim`）・
`brewer`・トリミング区間・**実際に実行した ffmpeg コマンド**を含むJSON文字列です。
このレコードを見れば、本リポジトリで同じ処理を再現できます。

### 有効化の条件

以下の2つを満たしたときにログが送信されます。

1. Kintoneの接続情報が環境変数で設定されていること
   - `KINTONE_SUBDOMAIN` … サブドメイン（`https://<subdomain>.cybozu.com`）
   - `KINTONE_APP_ID` … 記録先アプリのID
   - `KINTONE_API_TOKEN` … 対象アプリのAPIトークン
2. 送信の有効化フラグが立っていること。以下のいずれか。
   - 醸造需要JSON-LDの `dbp:brewingArgument` に `dbp:key: "push_kintone"`, `schema:value: "true"` を指定
   - もしくは環境変数 `KINTONE_PUSH_LOG=1` を設定

さらに、レコードのキーとなる**拠点 `depo`** を指定してください。
醸造需要JSON-LDの `dbp:brewingArgument`（`dbp:key: "depo"`）、または環境変数 `KINTONE_DEPO` で指定できます。

接続情報が未設定の場合や、フラグが無効の場合はプッシュをスキップします。
また、Kintone側の送信に失敗しても動画醸造の処理は継続されます（ログ送信は動画処理を止めません）。
`record_started_at` / `ip` / `thumbnail_img_path` の取得には ffprobe / findmnt / ffmpeg を用い、
利用できない環境ではそれぞれ処理時刻 / `unknown` / 省略にフォールバックします。

### 実行例

```bash
docker run -it \
  -e KINTONE_SUBDOMAIN=your-subdomain \
  -e KINTONE_APP_ID=123 \
  -e KINTONE_API_TOKEN=your-api-token \
  -e KINTONE_PUSH_LOG=1 \
  -e KINTONE_DEPO=p_tokai \
  -v <input_video_directory>:/input_in_docker \
  -v <output_video_directory>:/output_in_docker \
  dbp-brewer-example-movie \
  "<brewing_demand_json_ld>"
```

環境変数のサンプルは [.env.sample](.env.sample) を参照してください。
