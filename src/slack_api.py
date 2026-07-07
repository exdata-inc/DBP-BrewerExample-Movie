"""
Slack通知モジュール

動画醸造（トリミング・再エンコード）の進捗・結果をSlackに通知する。
dbp-video-brewer(TRUSCO) の slack_api.py 相当の処理を移植したもの
（HTTPクライアントのみ requests -> 既存依存の httpx に置き換え）。

本機能はオプションであり、以下の環境変数がすべて設定されている場合のみ有効化される。
  SLACK_BOT_TOKEN  : Slack Bot のトークン（xoxb-...）
  SLACK_CHANNEL    : 投稿先チャンネルID
未設定の場合は通知をスキップし、動画醸造の処理には影響しない。
"""

import os
from datetime import datetime, timezone, timedelta

import httpx

JST = timezone(timedelta(hours=9))
SLACK_API_URL = "https://slack.com/api/chat.postMessage"
DEFAULT_TIMEOUT = 30.0


class SlackNotifier:
    """Slack通知クライアント"""

    def __init__(self, token=None, channel=None, timeout=DEFAULT_TIMEOUT):
        self.token = token if token is not None else os.getenv("SLACK_BOT_TOKEN", "")
        self.channel = channel if channel is not None else os.getenv("SLACK_CHANNEL", "")
        self.timeout = timeout
        self._configured = bool(self.token and self.channel)

    @property
    def is_configured(self) -> bool:
        """Slack通知に必要な設定がそろっているか"""
        return self._configured

    def send(self, message: str, channel=None) -> bool:
        if not self.is_configured:
            return False

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-type": "application/json; charset=utf-8",
        }
        payload = {"channel": channel or self.channel, "text": message}

        try:
            response = httpx.post(
                SLACK_API_URL, json=payload, headers=headers, timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            if not result.get("ok", False):
                print(f"Slack notification failed: {result.get('error')}")
            return result.get("ok", False)
        except httpx.HTTPError as e:
            print(f"Slack notification failed: {e}")
            return False


def format_duration(seconds: float) -> str:
    """秒数を読みやすい形式に変換する。"""
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}分{secs}秒"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}時間{minutes}分"


def format_size(size_bytes: int) -> str:
    """バイト数を読みやすい単位付き文字列に変換する。"""
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size) < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def notify_date_start(target_date, depo, video_count, notifier=None) -> bool:
    """処理対象日の圧縮開始を通知する。"""
    notifier = notifier or SlackNotifier()
    if not notifier.is_configured:
        return False
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    message = f"[{depo}] {target_date} 圧縮開始 ({video_count}動画) - {now}"
    return notifier.send(message)


def notify_video_end(
    target_date,
    depo,
    camera,
    video_name,
    success,
    input_size,
    output_size,
    processing_time=0,
    notifier=None,
) -> bool:
    """動画1本の圧縮完了を通知する（TRUSCOの notify_camera_end 相当）。"""
    notifier = notifier or SlackNotifier()
    if not notifier.is_configured:
        return False
    now = datetime.now(JST).strftime("%H:%M:%S")
    status = "OK" if success else "NG"
    ratio = (output_size / input_size) if input_size > 0 else 0
    time_str = f" ({format_duration(processing_time)})" if processing_time > 0 else ""
    message = (
        f"  [{depo}] {target_date} {camera}/{video_name} {status} "
        f"({format_size(input_size)}->{format_size(output_size)}, {ratio:.1%}){time_str} {now}"
    )
    return notifier.send(message)


def notify_date_end(
    target_date,
    depo,
    success_count,
    fail_count,
    total_input_size,
    total_output_size,
    notifier=None,
) -> bool:
    """処理対象日の圧縮完了サマリを通知する。"""
    notifier = notifier or SlackNotifier()
    if not notifier.is_configured:
        return False
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    status = "完了" if fail_count == 0 else f"完了 (失敗: {fail_count}件)"
    ratio = (total_output_size / total_input_size) if total_input_size > 0 else 0
    message = (
        f"[{depo}] {target_date} 圧縮{status}\n"
        f"  成功: {success_count}件 / 失敗: {fail_count}件\n"
        f"  サイズ: {format_size(total_input_size)} -> {format_size(total_output_size)} ({ratio:.1%})\n"
        f"  終了時刻: {now}"
    )
    return notifier.send(message)
