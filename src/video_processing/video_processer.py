import os
import cv2
import subprocess
from tqdm import tqdm


def run_ffmpeg_command(input_video, previous_end_time, start_time, codec, output_file):
    command = [
        "ffmpeg",
        "-y",
        "-vsync",
        "0",
        "-i",
        input_video,
        "-ss",
        previous_end_time,
        "-to",
        start_time,
        "-c:v",
        codec,
        "-b:v",
        "780k",
        "-bufsize",
        "780k",
        "-maxrate",
        "780k",
        output_file,
    ]

    try:
        subprocess.run(command, check=True)
        print(f"Trimmed section saved as: {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"Error occurred while trimming section: {e}")


def trim_video_sections(input_dir, output_dir, trimmed_data):
    video_name = trimmed_data["video_name"]
    input_video = os.path.join(input_dir, video_name)
    codec = trimmed_data.get("codec", "h264")
    trimmed_sections = trimmed_data["trimmed_sections"]
    part_files = []

    previous_end_time = "0:00:00"

    for i, section in enumerate(trimmed_sections):
        start_time = section["start_time"]
        if previous_end_time != start_time:
            output_file = f"{output_dir}/{video_name}-part{i+1}.mkv"
            part_files.append(output_file)
            run_ffmpeg_command(input_video, previous_end_time, start_time, codec, output_file)

        previous_end_time = section["end_time"]

    # process the last section
    if trimmed_sections:
        last_section = trimmed_sections[-1]
        last_start_time = last_section["end_time"]
        last_end_time = trimmed_data["video_length"]
        if last_start_time != last_end_time:
            output_file = f"{output_dir}/{video_name}-part{len(trimmed_sections)+1}.mkv"
            part_files.append(output_file)
            run_ffmpeg_command(input_video, last_start_time, last_end_time, codec, output_file)

    return part_files


def concatenate_videos(output_dir, video_name, part_files, threshold, window_threshold, codec="h264"):
    print("Concatenating trimmed videos...")
    list_file = f"{output_dir}/concat_list.txt"

    with open(list_file, "w") as file:
        for part_file in part_files:
            modified_part_file = part_file.replace(output_dir, "")
            if modified_part_file.startswith("/"):
                modified_part_file = modified_part_file[1:]

            file.write(f"file '{modified_part_file}'\n")

    concatenated_output = f"{output_dir}/{video_name}-{threshold}-{window_threshold}-concatenated.mkv"

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        list_file,
        "-c:v",
        codec,
        "-preset",
        "fast",
        "-crf",
        "22",
        concatenated_output,
    ]

    try:
        subprocess.run(command, check=True)
        print(f"Concatenated video saved as: {concatenated_output}")
    except subprocess.CalledProcessError as e:
        print(f"Error occurred while concatenating videos: {e}")
    finally:
        try:
            os.remove(list_file)
            for part_file in part_files:
                os.remove(part_file)
        except Exception as e:
            print(f"Error occurred while cleaning up: {e}")


def copy_video_with_reencoding(input_dir, output_dir, video_name, codec):
    input_video = os.path.join(input_dir, video_name)
    output_video = os.path.join(output_dir, video_name)
    command = [
        "ffmpeg",
        "-y",
        "-vsync",
        "0",
        "-i",
        input_video,
        "-c:v",
        codec,
        "-b:v",
        "780k",
        "-bufsize",
        "780k",
        "-maxrate",
        "780k",
        output_video,
    ]
    try:
        subprocess.run(command, check=True)
        print(f"Video copied to {output_video}")
    except subprocess.CalledProcessError as e:
        print(f"Error occurred while copying video: {e}")


def calc_video_duration_and_fps(video_dir, video_name):
    video_path = os.path.join(video_dir, video_name)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("Error: Could not open video.")
        return None

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps

    cap.release()
    return duration, fps


def read_frame_diffs(file_path):
    frame_diffs = []
    with open(file_path, "r") as f:
        lines = f.readlines()
        for i in range(len(lines)):
            frame_number, diff_sum, timestamp = map(float, lines[i].strip().split(","))
            prev_diff = float(lines[i - 1].strip().split(",")[1]) if i > 0 else 0
            next_diff = float(lines[i + 1].strip().split(",")[1]) if i < len(lines) - 1 else 0
            max_diff = max(diff_sum, prev_diff, next_diff)
            frame_diffs.append((frame_number, max_diff))
    return frame_diffs


def trim_video(video_dir, video_name, output_dir, frame_diffs_file, threshold):
    video_path = os.path.join(video_dir, video_name)
    print("Opening video...")
    cap = cv2.VideoCapture(video_path)
    output_path = os.path.join(output_dir, f"{video_name}-trimmed.mkv")

    if not cap.isOpened():
        print("Error: Could not open video.")
        return

    print("Video opened successfully.")
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    if not frame_diffs_file:
        print("Error: No frame differences calculated.")
        return

    frame_diffs = read_frame_diffs(frame_diffs_file)
    print("Frame differences calculated successfully.")
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    frame_number = 0

    pbar = tqdm(total=len(frame_diffs), desc="Processing frames")
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_number < len(frame_diffs) and frame_diffs[frame_number][1] > threshold:
            out.write(frame)
        pbar.update(1)
        frame_number += 1
    pbar.close()

    cap.release()
    out.release()
    print(f"Video trimmed and saved to {output_path}")


if __name__ == "__main__":
    threshold = 50
    video_path = "../../data/input/07-43-03-cameraA2.mkv"
    output_path = f"../../data/output/07-43-03-cameraA2-trimmed-threshold{threshold}.mkv"
    trim_video(video_path, output_path, threshold)
