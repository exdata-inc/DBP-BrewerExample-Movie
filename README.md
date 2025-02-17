# dbp-video-brewer

## Build

```
docker build --no-cache -t dbp-brewer-example-movie .
```

## Run

```bash
docker run -it \
  -v <your_mount_directory>:/app/<your_data_directory> \
  dbp-brewer-example-movie \
  "<brewing_demand_json_ld>"
```
