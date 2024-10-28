import json
import logging
import os
import pandas as pd
from datetime import datetime, date, time, timedelta
from time import sleep
from typing import Optional
from climate_web_utilities import (
    ClimateConfig,
    CONFIG_NAME,
    LIVE_FOLDER_PATH,
    RETRIEVE_CONFIG,
    times_to_timedeltas,
)
from light_utilities import flash_lights_thrice, send_to_arduino

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)
CONFIG_PATH = os.path.join(LIVE_FOLDER_PATH, CONFIG_NAME)


def find_next_row(df: pd.DataFrame, elapsed_time: timedelta) -> int:
    """Find the next row of the Dataframe that elapsed_time > elapsed_time.

    Arguments:
        df (DataFrame): A dataframe where the first column are timedeltas that light intensities are to be set.
        elapsed_time (timedelta): The amount of time since the profile was started.
    Returns (int):
        Index of the next row in the dataframe where time <= the elapsed time.
    """
    time_column_name: str = df.columns[0]
    row_idx: int = 0
    # Note: Time values in the dataframe are type datetime.timedelta's
    next_time = df[time_column_name][row_idx]
    while elapsed_time > next_time and row_idx + 1 < len(df):
        next_time = df[time_column_name][row_idx + 1]
        row_idx += 1
    return row_idx


def save_config(config: dict) -> None:
    """Save climate_config.json."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as outfile:
        json.dump(config, outfile, indent=4, sort_keys=True, default=str)
    return


def control_lights(profile_path: str, start_time: datetime):
    logger.info("Light controller starting as pid=%s", os.getpid())
    flash_lights_thrice()
    config = RETRIEVE_CONFIG()
    start_time = config["_started"]
    # Read profile excel file
    df = pd.read_excel(config["_profile_filepath"])
    time_column_name, intensity_column_name = df.columns[:2]
    # Transform input data time column to timedeltas
    df = times_to_timedeltas(df)
    # Determine the profile cycle length and where the current time is relative to when it was started.
    cycle_dur = max(df[time_column_name])
    now = datetime.now()
    total_elapsed_time = now - start_time
    cycle_num = total_elapsed_time // cycle_dur
    cycle_start = start_time + cycle_num * cycle_dur
    dur_into_cycle = now - cycle_start
    if dur_into_cycle > cycle_dur and not config["run_continuously"]:
        logger.info(
            "Duration since start already > profile cycle length. Light controller done."
        )
        controlling = False
    else:
        # Find the next row in the dataframe that is at or after the current elapsed time:
        # Note, this may not be the 1st row if a profile is "restarted".
        row_count = find_next_row(df, dur_into_cycle)
    last_intensity = df[intensity_column_name][0]

    controlling = True
    while controlling:
        # go thru each of the rows
        while row_count < len(df):
            # Extract the "next" row's time and intensity values:
            next_time = df[time_column_name][row_count]
            intensity = df[intensity_column_name][row_count]

            if intensity != last_intensity:
                # Set light intensity
                logger.info(
                    "%s: Updating light intensity to %s."
                    % (now.strftime("%m/%d %H:%M:%S"), intensity)
                )
                send_to_arduino(intensity)
                config["last_updated"] = now
                config["last_intensity"] = intensity
                save_config(config)
                last_intensity = intensity

            while dur_into_cycle <= next_time:
                sleep(0.5)
                now = datetime.now()
                dur_into_cycle = now - cycle_start
            row_count += 1
        row_count = 0
        cycle_num += 1
        now = datetime.now()
        cycle_start = start_time + cycle_num * cycle_dur
        dur_into_cycle = now - cycle_start
        controlling = config["run_continuously"]
    config["rpi_time_script_finished"] = datetime.now()
    save_config(config)


if __name__ == "__main__":
    # Normally the config has already been written and contains the path to the xlsx and when it stared.
    config = ClimateConfig()
    if config.profile_filename:
        control_lights(config._profile_filepath, config.started)
