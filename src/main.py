import os
import glob
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

IS_IN_DOCKER = os.getenv("RUNNING_IN_DOCKER") == "1"


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
):
    if output_path.startswith("file://"):
        output_path = output_path.replace("file://", "")
        output_video_name = os.path.basename(f"{output_prefix}{video_name}")
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
                )
                if not part_files:
                    print("No sections to trim.")
                    copy_video_with_reencoding(
                        input_dir=video_path,
                        output_dir=output_path,
                        video_name=video_name,
                        output_video_name=output_video_name,
                        codec=codec,
                    )
                else:
                    concatenate_videos(
                        output_dir=output_path,
                        output_video_name=output_video_name,
                        part_files=part_files,
                        threshold=threshold,
                        window_threshold=window_threshold,
                        codec=codec,
                    )
        else:
            print("Re-encoding video without trimming...")
            copy_video_with_reencoding(
                input_dir=video_path,
                output_dir=output_path,
                video_name=video_name,
                output_video_name=output_video_name,
                codec=codec,
            )
    # elif output_path.startswith("ftp://"):
    #     pass                                          #TODO: Implement this!
    # elif output_path.startswith("http://"):
    #     pass                                          #TODO: Implement this!
    # elif output_path.startswith("https://"):
    #     pass                                          #TODO: Implement this!
    else:
        raise ValueError("Error: Unknown output_path")

    print("Process completed successfully.")
    print("----------params----------")
    print(f"Threshold:        {threshold}")
    print(f"Window Threshold: {window_threshold}")
    print(f"Codec:            {codec}")


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

    if data_set_base_path.startswith("file://"):
        file_path = data_set_base_path.replace("file://", "")
        if data_set_pattern.startswith("/"):
            data_set_pattern = data_set_pattern[1:]
        dt = dt_start
        while dt <= dt_end:
            video_path_pattern = os.path.join(file_path, dt.strftime(data_set_pattern))
            video_paths = glob.glob(video_path_pattern)
            if not video_paths:
                print(f"No videos found for pattern: {video_path_pattern}")
            else:
                for video_path in sorted(video_paths):
                    video_name = os.path.basename(video_path)
                    relative_path = os.path.relpath(video_path, file_path)
                    output_video_path = os.path.join(output_path, relative_path)
                    brewed_output_path = os.path.dirname(output_video_path)
                    process_video(
                        output_path=brewed_output_path,
                        video_path=os.path.dirname(video_path),
                        video_name=video_name,
                        threshold=int(threshold),
                        window_threshold=int(window_threshold),
                        codec=codec,
                        do_trim=do_trim,
                        output_prefix=output_prefix,
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
                '/output_in_docker', output_path_wo_protocol.lstrip('/')
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
                        '/input_in_docker', data_set_base_path_wo_protocol.lstrip('/')
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
