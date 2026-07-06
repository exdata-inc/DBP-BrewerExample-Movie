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
