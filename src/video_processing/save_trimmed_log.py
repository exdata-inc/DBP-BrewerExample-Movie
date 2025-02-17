import os
import json
from itertools import tee
from datetime import datetime, timedelta


def format_time(seconds):
    return str(timedelta(seconds=seconds))


def parse_time_string(time_str):
    try:
        time_format = "%H:%M:%S.%f"
        return datetime.strptime(time_str, time_format)
    except ValueError:
        time_format = "%H:%M:%S"
        return datetime.strptime(time_str, time_format)


def parse_duration_string(duration_str):
    try:
        if "day" in duration_str:
            days, time_str = duration_str.split(", ")
            days = int(days.split()[0])
            if "." in time_str:
                dt = datetime.strptime(time_str, "%H:%M:%S.%f")
            else:
                dt = datetime.strptime(time_str, "%H:%M:%S")
            return timedelta(
                days=days,
                hours=dt.hour,
                minutes=dt.minute,
                seconds=dt.second,
                microseconds=dt.microsecond if hasattr(dt, "microsecond") else 0,
            )
        else:
            if "." in duration_str:
                dt = datetime.strptime(duration_str, "%H:%M:%S.%f")
            else:
                dt = datetime.strptime(duration_str, "%H:%M:%S")

            return timedelta(
                hours=dt.hour,
                minutes=dt.minute,
                seconds=dt.second,
                microseconds=dt.microsecond if hasattr(dt, "microsecond") else 0,
            )
    except ValueError as e:
        raise ValueError(f"Invalid duration format: {duration_str}") from e


def extract_sections(file_path, threshold):
    data = []

    with open(file_path, "r") as file:
        for line in file:
            frame_number, variance, timestamp = line.strip().split(",")
            data.append(
                {"frame_number": int(float(frame_number)), "variance": float(variance), "timestamp": float(timestamp)}
            )

    trimmed_sections = []
    current_section = {
        "start_time": format_time(0),
        "start_frame_no": 1,
        "end_time": format_time(0),
        "end_frame_no": 0,
        "duration": str(timedelta(seconds=0)),
    }
    prev_data = None

    for entry in data:
        if prev_data is not None:
            if prev_data["variance"] > threshold and entry["variance"] < threshold:
                current_section["start_time"] = format_time(entry["timestamp"])
                current_section["start_frame_no"] = entry["frame_number"]
            if prev_data["variance"] < threshold and entry["variance"] > threshold:
                current_section["end_time"] = format_time(prev_data["timestamp"])
                current_section["end_frame_no"] = prev_data["frame_number"]
                start_time = parse_time_string(current_section["start_time"])
                end_time = parse_time_string(current_section["end_time"])
                current_section["duration"] = str(timedelta(seconds=(end_time - start_time).total_seconds()))
                current_section_copy = current_section.copy()
                trimmed_sections.append(current_section_copy)

        prev_data = entry
    return trimmed_sections


def finalize_trimmed_data(
    trimmed_sections,
    video_name,
    video_path,
    threshold,
    video_length,
    video_fps,
    min_duration_seconds=10,
    max_frame_gap=10,
    codec="h264",
    use_variance=True,
):
    def pairwise(iterable):
        a, b = tee(iterable)
        next(b, None)
        return zip(a, b)

    trimmed_sections = [
        section
        for section in trimmed_sections
        if parse_duration_string(section["duration"]) >= timedelta(seconds=min_duration_seconds)
    ]

    merged_sections = []
    prev_merged_section = None
    for current_section, next_section in pairwise(trimmed_sections):
        if (
            prev_merged_section is not None
            and next_section["start_frame_no"] - prev_merged_section["end_frame_no"] <= max_frame_gap
        ):
            merged_section = {
                "start_time": prev_merged_section["start_time"],
                "start_frame_no": prev_merged_section["start_frame_no"],
                "end_time": next_section["end_time"],
                "end_frame_no": next_section["end_frame_no"],
                "duration": str(
                    parse_duration_string(prev_merged_section["duration"])
                    + parse_duration_string(next_section["duration"])
                ),
            }
            prev_merged_section = merged_section
        elif next_section["start_frame_no"] - current_section["end_frame_no"] <= max_frame_gap:
            merged_section = {
                "start_time": current_section["start_time"],
                "start_frame_no": current_section["start_frame_no"],
                "end_time": next_section["end_time"],
                "end_frame_no": next_section["end_frame_no"],
                "duration": str(
                    parse_duration_string(current_section["duration"]) + parse_duration_string(next_section["duration"])
                ),
            }
            prev_merged_section = merged_section
        else:
            if prev_merged_section is None:
                merged_sections.append(current_section)
            else:
                merged_sections.append(merged_section)
                prev_merged_section = None
    trimmed_sections = merged_sections

    try:
        video_length_str = str(timedelta(seconds=video_length))
    except OverflowError:
        video_length_str = str(timedelta(minutes=30))

    json_data = {
        "camera": next((part for part in video_path.split("/") if part.startswith("camera")), "unknown"),
        "video_name": video_name,
        "video_path": video_path,
        "video_fps": video_fps,
        "video_length": video_length_str,
        "brewer": "variance" if use_variance else "frame_diffs",
        "threshold": str(threshold),
        "codec": codec,
        "trimmed_sections": trimmed_sections,
    }

    return json_data


def save_trimmed_log(
    diffs_file_path, video_path, output_path, video_name, threshold, video_length, video_fps, window_threshold, codec
):
    trimmed_sections = extract_sections(diffs_file_path, threshold)
    result = finalize_trimmed_data(
        trimmed_sections=trimmed_sections,
        video_name=video_name,
        threshold=threshold,
        video_path=video_path,
        video_length=video_length,
        video_fps=video_fps,
        codec=codec,
    )
    output_path = os.path.join(output_path, f"{video_name}-{threshold}-{window_threshold}-trimmed.json")
    with open(output_path, "w") as file:
        json.dump(result, file, indent=4)
    return result


if __name__ == "__main__":
    diffs_file_path = "./sample.txt"
    video_path = "/home/runner/work/Video-Processing/Video-Processing/data/videos/camera1/video1.mp4"
    output_path = "./"
    video_name = "video_04-00-29_37.mkv"
    threshold = 30
    save_trimmed_log(diffs_file_path, video_path, output_path, video_name, threshold)
