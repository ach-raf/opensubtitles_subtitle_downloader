import os
import re
import configparser
from pathlib import Path


def read_file(_file_path):
    """
    a simple function that open a file in read mode
    :param _file_path: path to a certain file
    :return: opened file
    """
    with open(_file_path, "r", encoding="utf8") as _file_to_read:
        _file = _file_to_read.read()
    return _file


def save_file(_file_path, _content):
    """
    a function that replaces the content of the file with the new _content
    :param _file_path: path to a certain file
    :param _content: the content you want to write to the file
    :return: create or replace a file at the specified _file_path
    """
    with open(_file_path, "w", encoding="utf8") as _file_to_save:
        _file_to_save.write(str(_content))


def get_ads_list(_ads_file_path, ads_separator=","):
    """
    read and clean the ads file
    :param _ads_file_path: path to the ads file
    :return: a list of each ad
    """
    _ads_to_remove = read_file(_ads_file_path).split(ads_separator)
    _ads_to_remove = [ad.strip() for ad in _ads_to_remove]
    return _ads_to_remove


def clean_ads_regex(_subtitle_file_path, _ads_to_remove):
    full_path = Path(_subtitle_file_path)
    directory_name = full_path.parent
    file_name = full_path.stem
    file_extension = full_path.suffix

    _content = read_file(full_path.absolute())
    between_brackets_regex = r"\[([^]]+)\]"
    # clean _ads_to_remove from empty strings
    _ads_to_remove = [ad for ad in _ads_to_remove if ad]

    # create a dynamic regex based on the start of each ad.
    regex_list = []
    for _ad in _ads_to_remove:
        regex_list.append(f"(^{_ad}.*$)")

    join_ads_regex = "|".join(map(re.escape, regex_list)).replace("\\", "")
    _file_content = re.sub(
        pattern=join_ads_regex, repl="", string=_content, flags=re.MULTILINE
    )

    # result = re.findall(join_ads_regex, _text, re.MULTILINE)

    save_file(full_path.absolute(), _file_content)
    print(f"{full_path.absolute()} cleaned!")


def clean_ads(_subtitle_file_path, ads_separator=","):
    """
    clean ads from a subtitle file
    :param _subtitle_file_path: path to the subtitle file
    :param _ads_file_path: path to the ads file
    :return: a new subtitle file without ads
    """
    current_script_directory = Path(__file__).parent.absolute()
    ads_file_path = Path(current_script_directory, "ads.txt")
    _ads_to_remove = get_ads_list(ads_file_path, ads_separator)
    clean_ads_regex(_subtitle_file_path, _ads_to_remove)


if __name__ == "__main__":
    print("This is a module to clean ads from subtitles.")
