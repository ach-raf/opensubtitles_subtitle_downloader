import os
import sys
import configparser
import library.OpenSubtitles as OpenSubtitles
import json


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
OSD_LANGUAGES = json.loads(CONFIG_INFO["osd_languages"])
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


def main(language_choice):
    media_path_list = sys.argv[1:]
    subtitles = OpenSubtitles.OpenSubtitles(OSD_USERNAME, OSD_PASSWORD, OSD_API_KEY)
    subtitles.download_subtitles(media_path_list, language_choice)


if __name__ == "__main__":
    # Usage: python download_subs.py <path_to_media_file>
    # Usage: python download_subs.py <path_to_media_file> <path_to_media_file> # multiple files
    # Usage: python download_subs.py <path_to_media_folder>
    # Usage: python download_subs.py <path_to_media_folder> <path_to_media_folder> # multiple folders
    language_choice = OSD_LANGUAGES[options_menu()]
    main(language_choice)
