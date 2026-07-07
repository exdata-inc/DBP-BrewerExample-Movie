import os
import glob
import json
import time
import asyncio
import argparse
from datetime import datetime
from video_processing.save_trimmed_log import save_trimmed_log
from video_processing.video_frame_analyzer import calculate_frame_diff, calculate_frame_variance
from video_processing.video_processer import (
    trim_video,
    trim_video_sections,
    concatenate_videos,
    copy_video_with_reencoding,
    calc_video_duration_and_fps,
)
from json_ld_utils.json_ld_loader import fetch_brewing_demands_json
from utils.utils import get_brewing_arguments, extract_minimum_unit, extract_data_sets
from kintone_api import KintoneClient, create_video_record
from media_metadata import run_ffprobe_metadata, get_mount_ip, extract_thumbnail
from slack_api import SlackNotifier, notify_date_start, notify_video_end, notify_date_end

IS_IN_DOCKER = os.getenv("RUNNING_IN_DOCKER") == "1"

# ホストのディレクトリをコンテナ内へマウントする際の接頭辞
# （main() で JSON-LD の baseUrl を <prefix>/<host_path> に書き換えている）
DOCKER_INPUT_PREFIX = "/input_in_docker"
DOCKER_OUTPUT_PREFIX = "/output_in_docker"


def _to_bool(value):
    """schema:value や環境変数（bool / "true" / "1" など）を真偽値に正規化する"""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _extract_camera(video_path):
    """入力パスから camera 識別子を抽出する（save_trimmed_log と同じ規則）。"""
    return next((part for part in video_path.split("/") if part.startswith("camera")), "unknown")


def _to_host_path(path):
    """
    コンテナ内パスを「ホストから見たパス」に変換する。

    Docker実行時、出力/入力パスは <prefix>/<host_path> に書き換えられている。
    Kintoneに記録するパス(path / thumbnail_img_path)は、コンテナ固有の接頭辞を
    取り除いてホスト側のパスに戻す。ファイル自体の読み書きには使わない。
    """
    if not path or not IS_IN_DOCKER:
        return path
    for prefix in (DOCKER_OUTPUT_PREFIX, DOCKER_INPUT_PREFIX):
        if path == prefix:
            return "/"
        if path.startswith(prefix + "/"):
            return path[len(prefix):]
    return path


def _to_host_text(text):
    """
    文字列（ffmpegコマンド等）に含まれるコンテナ内パスをホストから見たパスに置換する。

    Docker実行時、コマンド中に現れる <prefix>/... をホスト側のパスへ書き換える。
    """
    if not text or not IS_IN_DOCKER:
        return text
    for prefix in (DOCKER_OUTPUT_PREFIX, DOCKER_INPUT_PREFIX):
        text = text.replace(prefix + "/", "/")
    return text


def _build_note_video(
    input_video,
    output_video,
    brewer,
    do_trim,
    do_trim_using_opencv,
    threshold,
    window_threshold,
    codec,
    trimmed_data,
    ffmpeg_commands,
    success,
    error_message,
):
    """
    note_video 用の文字列を生成する。

    本リポジトリでこの処理を一意に再現できるよう、入力・醸造引数・トリミング区間・
    実際に実行した ffmpeg コマンドを JSON 文字列としてまとめる。
    """
    note = {
        "repo": "DBP-BrewerExample-Movie",
        "status": "success" if success else "failed",
        "brewer": brewer,
        "do_trim": bool(do_trim),
        "do_trim_using_opencv": bool(do_trim_using_opencv),
        "threshold": threshold,
        "window_threshold": window_threshold,
        "codec": codec,
        "input_video": _to_host_path(input_video),
        "output_video": _to_host_path(output_video),
        "ffmpeg_commands": [_to_host_text(cmd) for cmd in ffmpeg_commands],
    }
    if error_message:
        note["error_message"] = error_message
    if trimmed_data:
        note["video_length"] = trimmed_data.get("video_length")
        note["video_fps"] = trimmed_data.get("video_fps")
        note["trimmed_sections"] = trimmed_data.get("trimmed_sections")
    return json.dumps(note, ensure_ascii=False)


def _push_process_log_to_kintone(
    depo,
    camera,
    year_month,
    video_path,
    input_video,
    output_video,
    note_video,
    client=None,
):
    """
    処理結果を dbp-video-brewer(TRUSCO) と同一スキーマで Kintone にプッシュする。
    camera × year_month のレコードへ動画行を追記（無ければ新規作成）。
    Kintone側のエラーは動画醸造の処理に影響させない。
    """
    try:
        client = client or KintoneClient()
        if not client.is_configured:
            print(
                "Kintone is not configured "
                "(KINTONE_SUBDOMAIN / KINTONE_APP_ID / KINTONE_API_TOKEN). Skipping log push."
            )
            return

        # ファイルの読み書き・メタデータ取得はコンテナ内パスで行い、
        # Kintoneに記録するパスはホストから見たパスに変換する。
        input_size = os.path.getsize(input_video) if os.path.exists(input_video) else 0
        output_size = os.path.getsize(output_video) if os.path.exists(output_video) else 0

        metadata = run_ffprobe_metadata(input_video) if os.path.exists(input_video) else None
        ip = get_mount_ip(video_path)
        thumbnail = extract_thumbnail(output_video) if os.path.exists(output_video) else None

        video = create_video_record(
            output_path=_to_host_path(output_video),
            original_size=input_size,
            compressed_size=output_size,
            note_video=note_video,
            metadata=metadata,
            ip=ip,
            thumbnail_img_path=_to_host_path(thumbnail),
        )

        result = client.add_or_update_camera(depo, camera, year_month, [video], note="")
        if result.get("success"):
            action = result.get("action", "pushed")
            print(f"Kintone: video {action} (depo={depo}, camera={camera}, year_month={year_month})")
        else:
            print(f"Failed to push Kintone log: {result.get('error')}")
    except Exception as e:
        print(f"Error while pushing Kintone log: {e}")


def _safe_getsize(path):
    """ファイルが存在すればバイトサイズを、無ければ0を返す。"""
    return os.path.getsize(path) if os.path.exists(path) else 0


def _notify_slack_video(
    target_date,
    depo,
    camera,
    video_name,
    success,
    input_size,
    output_size,
    processing_time,
    notifier=None,
):
    """動画1本の処理結果をSlackに通知する（Slack側のエラーは動画処理に影響させない）。"""
    try:
        notifier = notifier or SlackNotifier()
        if not notifier.is_configured:
            return
        notify_video_end(
            target_date=target_date,
            depo=depo,
            camera=camera,
            video_name=video_name,
            success=success,
            input_size=input_size,
            output_size=output_size,
            processing_time=processing_time,
            notifier=notifier,
        )
    except Exception as e:
        print(f"Error while sending Slack notification: {e}")


def process_video(
    video_path,
    video_name,
    output_path,
    threshold,
    window_threshold,
    codec="h264",
    use_variance=True,
    do_trim=True,
    do_trim_using_opencv=False,
    output_prefix="",
    push_kintone=False,
    push_slack=False,
    depo="",
    year_month=None,
    target_date=None,
):
    output_video_name = os.path.basename(f"{output_prefix}{video_name}")
    triimed_data = None
    success = True
    error_message = None
    # Kintoneログ（note_video）に実行した ffmpeg コマンドを記録して再現可能にする
    ffmpeg_commands = []
    brewer = ("variance" if use_variance else "frame_diffs") if do_trim else "reencode_only"
    camera = _extract_camera(video_path)
    resolved_year_month = year_month or datetime.now().strftime("%Y-%m")
    result = None
    start_time = time.time()
    # 出力先の種類にかかわらず、処理後にKintone/Slackへ通知できるよう try を全ブランチの外側に取る
    try:
        if output_path.startswith("file://"):
            output_path = output_path.replace("file://", "")
            print(f"Processing video: {video_path}/{video_name}")
            if do_trim:
                print("Calculating frame differences...")
                if use_variance:
                    frame_diffs_file = calculate_frame_variance(
                        video_dir=video_path, video_name=video_name, threshold=threshold, window_threshold=window_threshold
                    )
                else:
                    frame_diffs_file = calculate_frame_diff(video_dir=video_path, video_name=video_name, threadhold=threshold)

                print("Saving trimmed log...")
                video_length, video_fps = calc_video_duration_and_fps(video_path, video_name)
                triimed_data = save_trimmed_log(
                    diffs_file_path=frame_diffs_file,
                    video_path=video_path,
                    output_path=output_path,
                    video_name=video_name,
                    output_video_name=output_video_name,
                    threshold=threshold,
                    video_length=video_length,
                    video_fps=video_fps,
                    window_threshold=window_threshold,
                    codec=codec,
                )

                if do_trim_using_opencv:
                    print("Trimming video...")
                    trim_video(
                        video_dir=video_path,
                        video_name=video_name,
                        output_dir=output_path,
                        output_video_name=output_video_name,
                        frame_diffs_file=frame_diffs_file,
                        threshold=threshold,
                    )
                else:
                    part_files = trim_video_sections(
                        input_dir=video_path,
                        output_dir=output_path,
                        output_video_name=output_video_name,
                        trimmed_data=triimed_data,
                        command_log=ffmpeg_commands,
                    )
                    if not part_files:
                        print("No sections to trim.")
                        copy_video_with_reencoding(
                            input_dir=video_path,
                            output_dir=output_path,
                            video_name=video_name,
                            output_video_name=output_video_name,
                            codec=codec,
                            command_log=ffmpeg_commands,
                        )
                    else:
                        concatenate_videos(
                            output_dir=output_path,
                            output_video_name=output_video_name,
                            part_files=part_files,
                            threshold=threshold,
                            window_threshold=window_threshold,
                            codec=codec,
                            command_log=ffmpeg_commands,
                        )
            else:
                print("Re-encoding video without trimming...")
                copy_video_with_reencoding(
                    input_dir=video_path,
                    output_dir=output_path,
                    video_name=video_name,
                    output_video_name=output_video_name,
                    codec=codec,
                    command_log=ffmpeg_commands,
                )
        # elif output_path.startswith("ftp://"):
        #     pass                                          #TODO: Implement this!
        # elif output_path.startswith("http://"):
        #     pass                                          #TODO: Implement this!
        # elif output_path.startswith("https://"):
        #     pass                                          #TODO: Implement this!
        else:
            raise ValueError("Error: Unknown output_path")
    except Exception as e:
        success = False
        error_message = str(e)
        raise
    finally:
        input_video = os.path.join(video_path, video_name)
        output_video = os.path.join(output_path, output_video_name)
        input_size = _safe_getsize(input_video)
        output_size = _safe_getsize(output_video)
        processing_time = time.time() - start_time
        result = {
            "success": success,
            "camera": camera,
            "video_name": video_name,
            "input_size": input_size,
            "output_size": output_size,
            "processing_time": processing_time,
        }
        if push_kintone:
            note_video = _build_note_video(
                input_video=input_video,
                output_video=output_video,
                brewer=brewer,
                do_trim=do_trim,
                do_trim_using_opencv=do_trim_using_opencv,
                threshold=threshold,
                window_threshold=window_threshold,
                codec=codec,
                trimmed_data=triimed_data,
                ffmpeg_commands=ffmpeg_commands,
                success=success,
                error_message=error_message,
            )
            _push_process_log_to_kintone(
                depo=depo,
                camera=camera,
                year_month=resolved_year_month,
                video_path=video_path,
                input_video=input_video,
                output_video=output_video,
                note_video=note_video,
            )
        if push_slack:
            _notify_slack_video(
                target_date=target_date or resolved_year_month,
                depo=depo,
                camera=camera,
                video_name=video_name,
                success=success,
                input_size=input_size,
                output_size=output_size,
                processing_time=processing_time,
            )

    print("Process completed successfully.")
    print("----------params----------")
    print(f"Threshold:        {threshold}")
    print(f"Window Threshold: {window_threshold}")
    print(f"Codec:            {codec}")
    return result


def brewing_videos(
    data_set_pattern,
    data_set_base_path,
    brewing_arguments,
    output_path,
    dt_start,
    dt_end,
    duration,
):
    threshold = brewing_arguments.get("threshold", 30)
    window_threshold = brewing_arguments.get("window_threshold", 5000)
    codec = brewing_arguments.get("codec", "libx264")
    do_trim = brewing_arguments.get("do_trim", True)
    output_prefix = brewing_arguments.get("output_prefix", "")
    # 醸造引数 push_kintone、または環境変数 KINTONE_PUSH_LOG が有効ならKintoneにログを送信する
    push_kintone = _to_bool(brewing_arguments.get("push_kintone", False)) or _to_bool(
        os.getenv("KINTONE_PUSH_LOG")
    )
    # Kintoneレコードのキーとなる拠点。醸造引数 depo または環境変数 KINTONE_DEPO
    depo = brewing_arguments.get("depo") or os.getenv("KINTONE_DEPO", "")
    # 醸造引数 push_slack、または環境変数 SLACK_NOTIFY が有効ならSlackに通知する
    push_slack = _to_bool(brewing_arguments.get("push_slack", False)) or _to_bool(
        os.getenv("SLACK_NOTIFY")
    )
    slack = SlackNotifier() if push_slack else None
    if slack and not slack.is_configured:
        print("Slack is not configured (SLACK_BOT_TOKEN / SLACK_CHANNEL). Skipping notifications.")
        push_slack = False
        slack = None

    if data_set_base_path.startswith("file://"):
        file_path = data_set_base_path.replace("file://", "")
        if data_set_pattern.startswith("/"):
            data_set_pattern = data_set_pattern[1:]
        dt = dt_start
        while dt <= dt_end:
            # year_month は処理対象日から決定（TRUSCOと同じ規則）
            year_month = dt.strftime("%Y-%m")
            date_str = dt.strftime("%Y-%m-%d")
            video_path_pattern = os.path.join(file_path, dt.strftime(data_set_pattern))
            video_paths = glob.glob(video_path_pattern)
            if not video_paths:
                print(f"No videos found for pattern: {video_path_pattern}")
            else:
                if slack:
                    notify_date_start(date_str, depo, len(video_paths), notifier=slack)
                date_success = 0
                date_fail = 0
                date_input_size = 0
                date_output_size = 0
                for video_path in sorted(video_paths):
                    video_name = os.path.basename(video_path)
                    relative_path = os.path.relpath(video_path, file_path)
                    output_video_path = os.path.join(output_path, relative_path)
                    brewed_output_path = os.path.dirname(output_video_path)
                    result = process_video(
                        output_path=brewed_output_path,
                        video_path=os.path.dirname(video_path),
                        video_name=video_name,
                        threshold=int(threshold),
                        window_threshold=int(window_threshold),
                        codec=codec,
                        do_trim=do_trim,
                        output_prefix=output_prefix,
                        push_kintone=push_kintone,
                        push_slack=push_slack,
                        depo=depo,
                        year_month=year_month,
                        target_date=date_str,
                    )
                    if result:
                        date_success += 1 if result["success"] else 0
                        date_fail += 0 if result["success"] else 1
                        date_input_size += result["input_size"]
                        date_output_size += result["output_size"]
                if slack:
                    notify_date_end(
                        date_str, depo, date_success, date_fail, date_input_size, date_output_size, notifier=slack
                    )
            dt += duration
    # elif data_set_base_path.startswith("ftp://"):
    #     pass                                          #TODO: Implement this!
    # elif data_set_base_path.startswith("http://"):
    #     pass                                          #TODO: Implement this!
    # elif data_set_base_path.startswith("https://"):
    #     pass                                          #TODO: Implement this!
    else:
        raise ValueError("Error: Unknown data_set_base_path")


def main(json_ld):
    try:
        brewing_demands_json = asyncio.run(fetch_brewing_demands_json(json_ld))
        brewing_schema_name = brewing_demands_json["dbp:brewerInfo"]["schema:name"]
        if brewing_schema_name != "videoCompression":
            print("This is not demand for video compression")
            exit()
        else:
            print("This is demand for video compression")

        brewing_arguments = get_brewing_arguments(brewing_demands_json)
        output_path = brewing_demands_json.get("dbp:brewerOutputStore", {}).get("dbp:baseUrl")
        if IS_IN_DOCKER and output_path.startswith("file://"):
            output_path_wo_protocol = output_path.replace("file://", "")
            output_path_in_docker = os.path.join(
                DOCKER_OUTPUT_PREFIX, output_path_wo_protocol.lstrip('/')
            )
            output_path = f"file://{output_path_in_docker}"
        data_output_path_pattern = brewing_demands_json.get("dbp:brewerOutputStore", {}).get("dbp:pattern")
        dt_start_str = brewing_demands_json.get("dbp:timePeriodStart")
        dt_start = datetime.fromisoformat(dt_start_str)
        dt_end_str = brewing_demands_json.get("dbp:timePeriodEnd")
        dt_end = datetime.fromisoformat(dt_end_str)
        duration = extract_minimum_unit(data_output_path_pattern)

        data_sets = extract_data_sets(brewing_demands_json)

        for data_set in data_sets:
            for data_set_object in data_set:
                data_set_base_path = data_set_object.get("dbp:baseUrl")
                if IS_IN_DOCKER and data_set_base_path.startswith("file://"):
                    data_set_base_path_wo_protocol = data_set_base_path.replace("file://", "")
                    data_set_base_path_in_docker = os.path.join(
                        DOCKER_INPUT_PREFIX, data_set_base_path_wo_protocol.lstrip('/')
                    )
                    data_set_base_path = f"file://{data_set_base_path_in_docker}"
                data_set_pattern = data_set_object.get("dbp:pattern")
                if data_set_pattern == data_output_path_pattern:
                    if data_set_pattern.endswith("mp4") or data_set_pattern.endswith("mkv"):
                        brewing_videos(
                            data_set_pattern=data_set_pattern,
                            data_set_base_path=data_set_base_path,
                            brewing_arguments=brewing_arguments,
                            output_path=output_path,
                            dt_start=dt_start,
                            dt_end=dt_end,
                            duration=duration,
                        )
                    else:
                        raise ValueError("Error: Unknown data_set_pattern")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process a video file or all videos in a directory.")
    parser.add_argument("json_ld", type=str, help="JSON-LD or its URL", default="https://dev-rwdb.srv.exdata.co.jp/api/v0/brewing_demands/69/?format=json")
    args = parser.parse_args()
    main(args.json_ld)
