#!/bin/bash

# Function to activate virtualenv
activate_venv() {
  source /root/programming/opensubtitles_subtitle_downloader/venv/bin/activate
}

deactivate_venv() {
  deactivate
}

# Function to run python script
run_script() {
  python "/root/programming/opensubtitles_subtitle_downloader/download_subs.py" "${@:1}"
}

# Activate virtualenv
activate_venv

# Run script passing all arguments
run_script "${@:1}"

# Deactivate virtualenv
deactivate_venv