"""
メディアメタデータ取得ユーティリティ

Kintoneログ用に、動画の撮影時刻・マウント元IP・サムネイルを取得する。
dbp-video-brewer(TRUSCO) の cmd.py 相当の処理を移植したもの。
ffprobe / ffmpeg / findmnt が利用できない環境では None / "unknown" を返す
（動画醸造の処理を止めないため、失敗は握りつぶす）。
"""

import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional


@dataclass
class VideoMetadata:
    creation_time: Optional[str]
    duration: Optional[float]
    finished_time: Optional[str]


def _run(cmd: list, capture_output: bool = True, timeout: Optional[int] = None):
    """subprocess.run のラッパー。(success, stdout, stderr) を返す。"""
    try:
        if capture_output:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.returncode == 0, result.stdout, result.stderr
        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=timeout
        )
        return result.returncode == 0, "", result.stderr
    except Exception as e:
        return False, "", str(e)


def run_ffprobe_metadata(video_path: str) -> VideoMetadata:
    """ffprobe で撮影時刻(creation_time)・長さ・終了時刻を取得する。"""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        video_path,
    ]
    ok, stdout, _ = _run(cmd, capture_output=True)

    creation_time = None
    duration = None
    finished_time = None

    if ok:
        try:
            data = json.loads(stdout)

            if "format" in data and "duration" in data["format"]:
                duration = float(data["format"]["duration"])

            if "format" in data and "tags" in data["format"]:
                tags = data["format"]["tags"]
                creation_time = tags.get("creation_time") or tags.get("CREATION_TIME")

            if not creation_time and "streams" in data:
                for stream in data["streams"]:
                    if "tags" in stream:
                        stream_tags = stream["tags"]
                        ct = stream_tags.get("creation_time") or stream_tags.get("CREATION_TIME")
                        if ct:
                            creation_time = ct
                            break

            if creation_time and duration:
                try:
                    ct = creation_time.replace("Z", "+00:00")
                    start_dt = datetime.fromisoformat(ct)
                    end_dt = start_dt + timedelta(seconds=duration)
                    finished_time = end_dt.isoformat()
                except Exception:
                    pass

        except json.JSONDecodeError:
            pass

    return VideoMetadata(
        creation_time=creation_time, duration=duration, finished_time=finished_time
    )


def get_mount_ip(path: str) -> str:
    """findmnt で path のマウント元(NFS/CIFS)のIP/ホストを取得する。取得不可なら "unknown"。"""
    cmd = ["findmnt", "-T", path, "-o", "SOURCE", "-n"]
    ok, stdout, _ = _run(cmd, capture_output=True)

    if ok and stdout.strip():
        source = stdout.strip()
        if ":" in source:
            return source.split(":")[0]
        elif source.startswith("//"):
            parts = source[2:].split("/")
            if parts:
                return parts[0]

    return "unknown"


def extract_thumbnail(video_path: str, output_path: Optional[str] = None) -> Optional[str]:
    """ffmpeg で動画の先頭フレームをサムネイル(.jpg)として書き出し、そのパスを返す。失敗時 None。"""
    if output_path is None:
        output_path = str(Path(video_path).with_suffix(".jpg"))

    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vframes", "1",
        "-f", "image2",
        output_path,
    ]
    ok, _, _ = _run(cmd, capture_output=False)

    if ok and Path(output_path).exists():
        return output_path

    return None
