import os
import sys
import configparser
import library.OpenSubtitles as OpenSubtitles
import library.sync_subtitles as sync_subtitles
import json
import threading
import multiprocessing


def read_config_file(file_path):
    """function to read informations from an info.ini file and return a list of info.

    Args:
        file_path ([str]): [path to read regex from]

    Returns:
        [dict]: [dict of credentials]
    """
    config = configparser.ConfigParser()
    config.read(file_path)
    credentials = {}
    for section in config.sections():
        for key in config[section]:
            # print(f'{key} = {config[section][key]}')
            credentials[key] = config[section][key]
    return credentials


# ================================ Paths =============================
CURRENT_DIR_PATH = os.path.dirname(os.path.realpath(__file__))
INFO_FILE_PATH = os.path.join(CURRENT_DIR_PATH, "config.ini")
# ====================================================================

# =============== Reading from config.ini ==============================
CONFIG_INFO = read_config_file(INFO_FILE_PATH)

OSD_USERNAME = CONFIG_INFO["osd_username"]
OSD_PASSWORD = CONFIG_INFO["osd_password"].replace('"', "")
OSD_API_KEY = CONFIG_INFO["osd_api_key"]
OSD_USER_AGENT = CONFIG_INFO["osd_user_agent"]
OSD_LANGUAGES = json.loads(CONFIG_INFO["osd_languages"])

SKIP_INTERACTIVE_MENU = CONFIG_INFO["osd_skip_interactive_menu"]
SKIP_SYNC = CONFIG_INFO["skip_sync"]
OPT_FORCE_UTF8 = CONFIG_INFO["opt_force_utf8"]


# ====================================================================
def print_menu():  # much graphic, very handsome
    global OSD_LANGUAGES
    language_number = 0
    choice_conversion = []
    print(30 * "-", "Select language for your subtitles", 30 * "-")
    for language_name in OSD_LANGUAGES:
        choice_conversion.append(language_name)
        print(f"{language_number}. {language_name}")
        language_number += 1

    print(f"{language_number}. Exit")
    print(66 * "-")
    return choice_conversion


def options_menu():
    choice_conversion = print_menu()
    user_choice = int(input("Subtitle language: "))
    # because the list (folder choice) in the printed menu is dynamic the showing order is the same as the index of the list
    if choice_conversion[user_choice]:
        print(f"Downloading subtitles in {choice_conversion[user_choice]}")
        return choice_conversion[user_choice]
    else:
        print("Exiting...")
        sys.exit()


def sync_choice_menu():
    print(30 * "-", "Sync subtitle to video", 30 * "-")
    print("1. No")
    print("2. Yes")
    print("3. Exit")
    print(66 * "-")
    user_choice = int(input("Sync choice: "))
    return user_choice


def main_multiprocessing(language_choice, sync_choice):
    media_path_list = sys.argv[1:]

    # Split the media_path_list into two parts
    split_index = len(media_path_list) // 2
    first_half = media_path_list[:split_index]
    second_half = media_path_list[split_index:]

    open_subtitles = OpenSubtitles.OpenSubtitles(
        OSD_USERNAME, OSD_PASSWORD, OSD_API_KEY, OSD_USER_AGENT, sync_choice=sync_choice
    )

    # Create two threads to run in parallel
    thread1 = multiprocessing.Process(
        target=open_subtitles.download_subtitles,
        args=(first_half, language_choice),
    )
    thread2 = multiprocessing.Process(
        target=open_subtitles.download_subtitles,
        args=(second_half, language_choice),
    )

    # Start the threads
    thread1.start()
    thread2.start()

    # Wait for both threads to finish
    thread1.join()
    thread2.join()


def main(language_choice, sync_choice):
    media_path_list = sys.argv[1:]

    open_subtitles = OpenSubtitles.OpenSubtitles(
        OSD_USERNAME, OSD_PASSWORD, OSD_API_KEY, OSD_USER_AGENT, sync_choice=sync_choice
    )

    open_subtitles.download_subtitles(media_path_list, language_choice)


if __name__ == "__main__":
    # Usage: python download_subs.py <path_to_media_file>
    # Usage: python download_subs.py <path_to_media_file> <path_to_media_file> # multiple files
    # Usage: python download_subs.py <path_to_media_folder>
    # Usage: python download_subs.py <path_to_media_folder> <path_to_media_folder> # multiple folders
    if SKIP_INTERACTIVE_MENU == "True":
        language_choice = list(OSD_LANGUAGES.items())[0][1]
        sync_choice = True if SKIP_SYNC == "True" else False
        main_multiprocessing(language_choice, sync_choice)
        sys.exit()

    user_choice = options_menu()
    language_choice = OSD_LANGUAGES[user_choice]
    sync_choice = True if sync_choice_menu() == 2 else False
    main_multiprocessing(language_choice, sync_choice)
