import os
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


def process_video(
    video_path,
    video_name,
    output_path,
    threshold,
    window_threshold,
    codec="h264",
    use_variance=True,
    do_trim_using_opencv=False,
):
    if output_path.startswith("file://"):
        output_path = output_path.replace("file://", "")
        print(f"Processing video: {video_path}/{video_name}")
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
                frame_diffs_file=frame_diffs_file,
                threshold=threshold,
            )
        else:
            part_files = trim_video_sections(input_dir=video_path, output_dir=output_path, trimmed_data=triimed_data)
            if not part_files:
                print("No sections to trim.")
                copy_video_with_reencoding(
                    input_dir=video_path, output_dir=output_path, video_name=video_name, codec=codec
                )
            else:
                concatenate_videos(
                    output_dir=output_path,
                    video_name=video_name,
                    part_files=part_files,
                    threshold=threshold,
                    window_threshold=window_threshold,
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
    pattern,
    data_set_base_path,
    brewing_arguments,
    output_path,
    dt_start,
    dt_end,
    duration,
):
    match pattern:
        case "%Y/%Y-%m-%d.mp4":
            if data_set_base_path.startswith("file://"):
                file_path = data_set_base_path.replace("file://", "")
                dt = dt_start
                while dt <= dt_end:
                    year_str = dt.strftime("%Y")
                    date_str = dt.strftime("%Y-%m-%d")
                    data_set_path = f"{file_path}{year_str}"
                    video_name = f"{date_str}.mp4"
                    threshold = brewing_arguments.get("threshold", 30)
                    window_threshold = brewing_arguments.get("window_threshold", 5000)
                    codec = brewing_arguments.get("codec", "libx264")
                    if output_path.endswith("/"):
                        output_path = output_path[:-1]
                    process_video(
                        output_path=output_path,
                        video_path=data_set_path,
                        video_name=video_name,
                        threshold=int(threshold),
                        window_threshold=int(window_threshold),
                        codec=codec,
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
                data_set_pattern = data_set_object.get("dbp:pattern")
                if data_set_pattern == data_output_path_pattern:
                    if data_set_pattern.endswith("mp4"):
                        brewing_videos(
                            pattern=data_set_pattern,
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
    parser.add_argument("json_ld", type=str, help="Path to the video file or directory")
    args = parser.parse_args()
    main(args.json_ld)
