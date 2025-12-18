import os
import cv2
import tempfile
import numpy as np
from tqdm import tqdm
import matplotlib.pyplot as plt


def calculate_frame_diff(video_dir, video_name, threadhold=1000000, save_diff_video=False):
    video_path = os.path.join(video_dir, video_name)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("Error: Could not open video.")
        return None

    ret, prev_frame = cap.read()
    if not ret:
        print("Error: Could not read the first frame.")
        cap.release()
        return None

    scale_percent = 50
    width = int(prev_frame.shape[1] * scale_percent / 100)
    height = int(prev_frame.shape[0] * scale_percent / 100)
    dim = (width, height)
    prev_frame = cv2.resize(prev_frame, dim, interpolation=cv2.INTER_AREA)
    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)

    temp_file = tempfile.NamedTemporaryFile(delete=False, mode="w")
    out = cv2.VideoWriter("output_video.mp4", cv2.VideoWriter_fourcc(*"mp4v"), 30, dim)
    with open(temp_file.name, "w") as f:
        while True:
            ret, curr_frame = cap.read()
            if not ret:
                break

            curr_frame = cv2.resize(curr_frame, dim, interpolation=cv2.INTER_AREA)
            curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
            frame_diff = cv2.absdiff(curr_gray, prev_gray)
            diff_sum = np.sum(frame_diff)

            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(frame_diff)
            center_x, center_y = max_loc[0], max_loc[1]

            start_x, end_x = calculate_dynamic_window(center_x, width, threadhold, frame_diff[center_y])
            start_y, end_y = calculate_dynamic_window(center_y, height, threadhold, frame_diff[:, center_x])

            dynamic_width = end_x - start_x
            dynamic_height = end_y - start_y
            if save_diff_video and diff_sum > threadhold:
                print(f"Frame: {cap.get(cv2.CAP_PROP_POS_FRAMES)}")
                cv2.rectangle(curr_frame, (start_x, start_y), (end_x, end_y), (0, 255, 0), 2)
                out.write(curr_frame)

            if has_frame_diff_in_window(prev_gray, curr_gray, start_x, start_y, dynamic_width, dynamic_height):
                diff_sum = threadhold + 1

            frame_number = cap.get(cv2.CAP_PROP_POS_FRAMES)
            f.write(f"{frame_number},{diff_sum}\n")
            prev_gray = curr_gray

            del curr_frame
            del curr_gray
            del frame_diff

    out.release()
    return temp_file.name


def calculate_dynamic_window(center, axis_length, threshold, diff_array):
    start = center
    end = center
    while start > 0 and diff_array[start] > threshold:
        start -= 1
    while end < axis_length - 1 and diff_array[end] > threshold:
        end += 1
    return start, end


def has_frame_diff_in_window(frame1, frame2, x, y, width, height, window_threshold=5000):
    if width <= 0 or height <= 0:
        return False

    window1 = frame1[y : y + height, x : x + width]
    window2 = frame2[y : y + height, x : x + width]

    diff = cv2.absdiff(window1, window2)

    diff_sum = np.sum(diff)
    is_diff = diff_sum > window_threshold
    return is_diff


def calculate_frame_variance(
    video_dir, video_name, threshold, window_threshold, save_diff_file=False, show_diff_frames=False
):
    video_path = os.path.join(video_dir, video_name)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("Error: Could not open video.")
        return None

    ret, prev_frame = cap.read()
    if not ret:
        print("Error: Could not read the first frame.")
        cap.release()
        return None

    scale_percent = 50
    width = int(prev_frame.shape[1] * scale_percent / 100)
    height = int(prev_frame.shape[0] * scale_percent / 100)
    dim = (width, height)
    prev_frame = cv2.resize(prev_frame, dim, interpolation=cv2.INTER_AREA)
    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)

    if save_diff_file:
        temp_file = tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".txt", dir="./")
    else:
        temp_file = tempfile.NamedTemporaryFile(delete=False, mode="w")

    process_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) - 2

    with open(temp_file.name, "w") as f:
        with tqdm(total=process_frames, desc="Processing Frames") as pbar:
            while True:
                ret, curr_frame = cap.read()
                if not ret:
                    break

                curr_frame = cv2.resize(curr_frame, dim, interpolation=cv2.INTER_AREA)
                curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
                frame_diff = cv2.absdiff(curr_gray, prev_gray)
                diff_variance = np.var(frame_diff)

                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(frame_diff)
                center_x, center_y = max_loc[0], max_loc[1]

                start_x, end_x = calculate_dynamic_window(center_x, width, 0.1, frame_diff[center_y])
                start_y, end_y = calculate_dynamic_window(center_y, height, 0.1, frame_diff[:, center_x])

                dynamic_width = end_x - start_x
                dynamic_height = end_y - start_y

                if show_diff_frames and diff_variance > threshold:
                    cv2.rectangle(curr_frame, (start_x, start_y), (end_x, end_y), (0, 255, 0), 2)
                    cv2.imshow("Current Frame with Dynamic Window", curr_frame)
                    cv2.waitKey(1)

                if diff_variance < threshold and has_frame_diff_in_window(
                    prev_gray,
                    curr_gray,
                    start_x,
                    start_y,
                    dynamic_width,
                    dynamic_height,
                    window_threshold=window_threshold,
                ):
                    diff_variance = threshold + 1

                frame_number = cap.get(cv2.CAP_PROP_POS_FRAMES)
                timestamp = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                f.write(f"{frame_number},{diff_variance},{timestamp}\n")
                prev_gray = curr_gray

                del curr_frame
                del curr_gray
                del frame_diff

                pbar.update(1)
            pbar.close()

    return temp_file.name


def plot_frame_diffs(frame_diffs):
    times = [fd[0] for fd in frame_diffs]
    diff_sums = [fd[1] for fd in frame_diffs]

    plt.figure(figsize=(10, 5))
    plt.bar(times, diff_sums, color="blue", width=0.1)
    plt.xlabel("Time (seconds)")
    plt.ylabel("Sum of Frame Differences")
    plt.title("Frame Differences Over Time")
    plt.show()


def show_max_diff_frames(frame_diffs):
    max_diff = max(frame_diffs, key=lambda x: x[1])
    time, diff_sum, prev_frame, curr_frame = max_diff

    cv2.imshow("Previous Frame", prev_frame)
    cv2.imshow("Current Frame", curr_frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    video_path = "./data/input/cameraA2"
    video_name = "video_04-00-29_37.mkv"
    calculate_frame_variance(
        video_dir=video_path,
        video_name=video_name,
        threshold=30,
        window_threshold=5000,
        save_diff_file=True,
    )
