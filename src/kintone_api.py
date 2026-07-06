"""
Kintone API連携モジュール

動画醸造（トリミング・再エンコード）の結果ログをKintoneに記録する。
dbp-video-brewer(TRUSCO) と同一のスキーマ・挙動を移植したもの
（HTTPクライアントのみ requests -> 既存依存の httpx に置き換え）。

レコード構造:
  - トップレベル: depo / camera / year_month でレコードを一意に識別
  - サブテーブル table: 動画1本 = 1行（path, サイズ, 撮影時刻, ip, note_video ...）
  - add_or_update_camera: 既存レコードがあれば動画行を追記、無ければ新規作成

本機能はオプションであり、以下の環境変数がすべて設定されている場合のみ有効化される。
  KINTONE_SUBDOMAIN / KINTONE_APP_ID / KINTONE_API_TOKEN
未設定の場合はプッシュをスキップし、動画醸造の処理には影響しない。
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

import httpx

DEFAULT_TIMEOUT = 30.0


@dataclass
class VideoRecord:
    """サブテーブル table の1行（動画1本分）"""

    path: str
    record_started_at: str
    ip: str
    original_size: str
    compressed_size: str
    semantipack_metadata_video: str = "{}"
    dbp_metadata_video: str = "{}"
    url: str = ""
    note_video: str = ""
    record_finished_at: Optional[str] = None
    thumbnail_img_path: Optional[str] = None


@dataclass
class CameraRecord:
    """トップレベルレコード（camera × year_month で1件）"""

    depo: str
    camera: str
    year_month: str
    videos: list = field(default_factory=list)
    semantipack_metadata: str = "{}"
    dbp_metadata: str = "{}"
    note: str = ""


class KintoneClient:
    """Kintone API クライアント"""

    def __init__(
        self,
        subdomain: Optional[str] = None,
        app_id: Optional[str] = None,
        api_token: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.subdomain = subdomain if subdomain is not None else os.getenv("KINTONE_SUBDOMAIN", "")
        app_id_raw = app_id if app_id is not None else os.getenv("KINTONE_APP_ID", "")
        self.app_id = int(app_id_raw) if str(app_id_raw).strip() else 0
        self.api_token = api_token if api_token is not None else os.getenv("KINTONE_API_TOKEN", "")
        self.timeout = timeout

        self._configured = bool(self.subdomain and self.app_id and self.api_token)
        self.base_url = f"https://{self.subdomain}.cybozu.com/k/v1" if self._configured else None

    @property
    def is_configured(self) -> bool:
        """Kintone連携に必要な設定がそろっているか"""
        return self._configured

    def _get_headers(self, include_content_type: bool = True) -> dict:
        headers = {"X-Cybozu-API-Token": self.api_token}
        if include_content_type:
            headers["Content-Type"] = "application/json"
        return headers

    def _build_video_table_rows(self, videos: list) -> list:
        table_rows = []
        for v in videos:
            row = {
                "value": {
                    "path": {"value": v.path},
                    "semantipack_metadata_video": {"value": v.semantipack_metadata_video},
                    "dbp_metadata_video": {"value": v.dbp_metadata_video},
                    "record_started_at": {"value": v.record_started_at},
                    "ip": {"value": v.ip},
                    "original_size_0": {"value": v.original_size},
                    "compressed_size_0": {"value": v.compressed_size},
                    "url": {"value": v.url},
                    "note_video": {"value": v.note_video},
                }
            }
            if v.record_finished_at:
                row["value"]["record_finished_at"] = {"value": v.record_finished_at}
            if v.thumbnail_img_path:
                row["value"]["thumbnail_img_path"] = {"value": v.thumbnail_img_path}
            table_rows.append(row)
        return table_rows

    def _build_video_table(self, videos: list) -> dict:
        return {"value": self._build_video_table_rows(videos)}

    def add_camera_record(self, record: CameraRecord) -> dict:
        if not self.is_configured:
            return {"success": False, "error": "Kintone is not configured"}

        url = f"{self.base_url}/record.json"
        payload = {
            "app": self.app_id,
            "record": {
                "depo": {"value": record.depo},
                "camera": {"value": record.camera},
                "year_month": {"value": record.year_month},
                "semantipack_metadata": {"value": record.semantipack_metadata},
                "dbp_metadata": {"value": record.dbp_metadata},
                "note": {"value": record.note},
                "table": self._build_video_table(record.videos),
            },
        }

        try:
            response = httpx.post(
                url, json=payload, headers=self._get_headers(), timeout=self.timeout
            )
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except httpx.HTTPError as e:
            return {"success": False, "error": _format_http_error(e)}

    def find_record_id(self, depo: str, camera: str, year_month: str) -> Optional[str]:
        url = f"{self.base_url}/records.json"
        query = (
            f'depo = "{depo}" and camera = "{camera}" and year_month = "{year_month}" '
            "order by $id desc limit 1"
        )

        params = {
            "app": self.app_id,
            "query": query,
            "fields[0]": "$id",
        }

        try:
            response = httpx.get(
                url,
                params=params,
                headers=self._get_headers(include_content_type=False),
                timeout=self.timeout,
            )
            response.raise_for_status()
            records = response.json().get("records", [])
            if records:
                return records[0]["$id"]["value"]
            return None
        except httpx.HTTPError:
            return None

    def get_record_by_id(self, record_id: str) -> Optional[dict]:
        url = f"{self.base_url}/record.json"
        params = {"app": self.app_id, "id": record_id}

        try:
            response = httpx.get(
                url,
                params=params,
                headers=self._get_headers(include_content_type=False),
                timeout=self.timeout,
            )
            response.raise_for_status()
            record = response.json().get("record", {})
            revision = record.get("$revision", {}).get("value")
            table_rows = record.get("table", {}).get("value", [])
            table_row_ids = [row["id"] for row in table_rows if "id" in row]
            return {"revision": revision, "table_row_ids": table_row_ids}
        except httpx.HTTPError:
            return None

    def update_camera_record(
        self,
        record_id: str,
        revision: str,
        table_row_ids: list,
        videos: list,
    ) -> dict:
        url = f"{self.base_url}/record.json"

        existing_rows = [{"id": row_id} for row_id in table_row_ids]
        new_rows = self._build_video_table_rows(videos)
        updated_table = existing_rows + new_rows

        payload = {
            "app": self.app_id,
            "id": record_id,
            "revision": revision,
            "record": {
                "table": {"value": updated_table},
            },
        }

        try:
            response = httpx.put(
                url, json=payload, headers=self._get_headers(), timeout=self.timeout
            )
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except httpx.HTTPError as e:
            return {"success": False, "error": _format_http_error(e)}

    def upload_file(self, file_path: str) -> Optional[str]:
        url = f"{self.base_url}/file.json"
        headers = {"X-Cybozu-API-Token": self.api_token}

        try:
            with open(file_path, "rb") as f:
                files = {"file": (Path(file_path).name, f)}
                response = httpx.post(url, headers=headers, files=files, timeout=self.timeout)
                response.raise_for_status()
                return response.json().get("fileKey")
        except Exception:
            return None

    def add_or_update_camera(
        self, depo: str, camera: str, year_month: str, videos: list, note: str = ""
    ) -> dict:
        if not self.is_configured:
            return {"success": False, "error": "Kintone is not configured"}

        record_id = self.find_record_id(depo, camera, year_month)

        if record_id:
            record_info = self.get_record_by_id(record_id)
            if record_info is None:
                return {"success": False, "error": f"Failed to get record {record_id}"}

            result = self.update_camera_record(
                record_id, record_info["revision"], record_info["table_row_ids"], videos
            )
            if result["success"]:
                result["action"] = "updated"
                result["record_id"] = record_id
            return result

        record = CameraRecord(
            depo=depo, camera=camera, year_month=year_month, videos=videos, note=note
        )
        result = self.add_camera_record(record)
        if result["success"]:
            result["action"] = "created"
        return result


def _format_http_error(e: "httpx.HTTPError") -> str:
    error_msg = str(e)
    response = getattr(e, "response", None)
    if response is not None:
        try:
            error_msg += f" - {response.text}"
        except Exception:
            pass
    return error_msg


def format_size_mb(size_bytes: int) -> str:
    """バイト数をMB単位の小数文字列に変換する（TRUSCOと同じ表現）。"""
    mb = size_bytes / (1024 * 1024)
    return f"{mb:.2f}"


def create_video_record(
    output_path: str,
    original_size: int,
    compressed_size: int,
    note_video: str,
    metadata=None,
    ip: str = "unknown",
    thumbnail_img_path: Optional[str] = None,
) -> VideoRecord:
    """エンコード結果から VideoRecord（サブテーブル1行）を組み立てる。

    metadata は media_metadata.VideoMetadata（creation_time / finished_time を持つ）。
    撮影時刻が取れない場合は record_started_at に現在時刻を用いる。
    """
    if metadata is not None and getattr(metadata, "creation_time", None):
        record_started_at = metadata.creation_time
    else:
        record_started_at = datetime.now().astimezone().isoformat()

    record_finished_at = None
    if metadata is not None and getattr(metadata, "finished_time", None):
        record_finished_at = metadata.finished_time

    return VideoRecord(
        path=output_path,
        record_started_at=record_started_at,
        ip=ip,
        original_size=format_size_mb(original_size),
        compressed_size=format_size_mb(compressed_size),
        url="",
        note_video=note_video,
        record_finished_at=record_finished_at,
        thumbnail_img_path=thumbnail_img_path,
    )
