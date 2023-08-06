# Opensubtitles.com subtitle downloader

This is a Python script to download subtitles from OpenSubtitles.com.

You can get an API key by registering at https://www.opensubtitles.com/en/consumers .

## Installation

### Windows

1. Install Python

2. Clone this repository, or download the zip file and extract it

```
git clone https://github.com/ach-raf/opensubtitles_subtitle_downloader.git
```

3. Install requirements

```
pip install -r requirements.txt
```

4. Add your OpenSubtitles.org credentials to `config.ini`

```ini
[SETTINGS]
osd_username = YOUR_USERNAME
osd_password = YOUR_PASSWORD
osd_api_key = YOUR_API_KEY
```

### Linux

1. Install Python

2. Clone this repository, or download the zip file and extract it

```
git clone https://github.com/ach-raf/opensubtitles_subtitle_downloader.git
```

3. Install requirements

```
pip3 install -r requirements.txt
```

4. Add your OpenSubtitles.com credentials to `config.ini`

```ini
[SETTINGS]
osd_username = YOUR_USERNAME
osd_password = YOUR_PASSWORD
osd_api_key = YOUR_API_KEY
```

## Usage

### Single file

To download subtitles for a single video file:

```
python download_subs.py <path/to/video.mkv>
```

### Multiple files

To download subtitles for multiple video files:

```
python download_subs.py <path/to/video1.mp4> <path/to/video2.mkv>
```

### Folder

To download subtitles for all video files in a folder:

```
python download_subs.py <path/to/folder>
```

It will search the folder recursively for video files and download subtitles.

### Multiple folders

To download subtitles for multiple folders:

```
python download_subs.py <path/to/folder1> <path/to/folder2>
```

It will look in both folders recursively for video files and download subtitles.

The language can be changed in the config.ini file, and dynamically shown in the interactive menu.

## Credits

- Uses [OpenSubtitles API](https://opensubtitles.stoplight.io/docs/opensubtitles-api/e3750fd63a100-getting-started)
