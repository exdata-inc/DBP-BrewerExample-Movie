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
  -v <your_mount_directory>:/app/<your_data_directory> \
  dbp-brewer-example-movie \
  "<brewing_demand_json_ld>"
```
