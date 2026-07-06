import re
from datetime import datetime, timedelta
import asyncio
import json_ld_utils.json_ld_loader as fetch_brewing_demands_json


def get_brewing_arguments(brewing_demands_json):
    brewing_arguments = {}
    try:
        for brewing_argument_info in brewing_demands_json["dbp:brewingArgument"]:
            if "threshold" == brewing_argument_info["dbp:key"]:
                brewing_arguments["threshold"] = brewing_argument_info["schema:value"]
            if "window_threshold" == brewing_argument_info["dbp:key"]:
                brewing_arguments["window_threshold"] = brewing_argument_info["schema:value"]
            if "codec" == brewing_argument_info["dbp:key"]:
                brewing_arguments["codec"] = brewing_argument_info["schema:value"]
            if "do_trim" == brewing_argument_info["dbp:key"]:
                brewing_arguments["do_trim"] = brewing_argument_info["schema:value"]
            if "output_prefix" == brewing_argument_info["dbp:key"]:
                brewing_arguments["output_prefix"] = brewing_argument_info["schema:value"]
            if "push_kintone" == brewing_argument_info["dbp:key"]:
                brewing_arguments["push_kintone"] = brewing_argument_info["schema:value"]
            if "depo" == brewing_argument_info["dbp:key"]:
                brewing_arguments["depo"] = brewing_argument_info["schema:value"]
        return brewing_arguments
    except Exception:
        print("No Brewing Arguments Found")


def extract_minimum_unit(output_pattern):
    try:
        pattern = re.compile(r"%([YmdHMS])")
    except re.error as e:
        print(f"Failed to compile regex: {e}")
        exit(1)

    captures = pattern.finditer(output_pattern)
    min_duration = timedelta.max

    for match in captures:
        duration = None
        unit = match.group(1)

        if unit == "Y":
            duration = timedelta(days=365)
        elif unit == "m":
            duration = timedelta(days=30)
        elif unit == "d":
            duration = timedelta(days=1)
        elif unit == "H":
            duration = timedelta(hours=1)
        elif unit == "M":
            duration = timedelta(minutes=1)
        elif unit == "S":
            duration = timedelta(seconds=1)

        if duration:
            min_duration = min(min_duration, duration)

    return min_duration


def extract_data_sets(brewing_demands_json):
    base_array = brewing_demands_json.get("dbp:brewerInput")
    if base_array:
        data_sets = []
        for element in base_array:
            dataset_object = element.get("schema:dataset")
            distribution_array = dataset_object.get("schema:distribution")
            if distribution_array:
                data_sets.append(distribution_array)
        return data_sets

