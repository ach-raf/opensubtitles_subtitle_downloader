# Opensubtitles.com Subtitle Downloader

🎬 A powerful Python tool for automating subtitle downloads and management from multiple sources.

## ✨ Key Features

- 🔍 **Multi-Source Support**
  - OpenSubtitles.com integration
  - SubDL.com integration
  - Automatic source selection
- 🧹 **Smart Processing**
  - Automatic subtitle cleaning (removes ads)
  - Audio synchronization using ffsubsync
  - UTF-8 encoding support
- 🎯 **Flexible Usage**
  - Single video file processing
  - Bulk folder processing
  - Interactive or automated mode
  - Multiple language support

## 🚀 Quick Start

For the fastest way to get started:

```bash
# Install UV and clone repository
pip install uv  # Windows
# or
curl -LsSf https://astral.sh/uv/install.sh | sh  # Linux/MacOS

git clone https://github.com/ach-raf/opensubtitles_subtitle_downloader.git && cd opensubtitles_subtitle_downloader

# Setup and run
uv venv && uv pip install -r requirements.txt  # Creates .venv folder
cp config.yaml.sample config.yaml  # Edit this file with your API keys
python download_subs.py path/to/your/movie.mkv
```

For detailed installation instructions, alternative methods, and configuration options, see the [Installation](#-installation) section below.

## 📥 Installation

### Prerequisites

- Python 3.7 or higher
- `uv` package manager (recommended) or pip
- Git (optional, for cloning)

### Step-by-Step Installation

1. **Install UV Package Manager** (Recommended)

   ```bash
   # On Windows (PowerShell)
   pip install uv

   # On Linux/MacOS
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Get the Code**

   ```bash
   # Option 1: Clone with git
   git clone https://github.com/ach-raf/opensubtitles_subtitle_downloader.git
   cd opensubtitles_subtitle_downloader

   # Option 2: Download ZIP
   # Download and extract the ZIP file from the GitHub repository
   ```

3. **Set Up Python Environment**

   ```bash
   # Create and activate virtual environment using uv
   uv venv

   # On Windows:
   .venv\Scripts\activate
   # On Linux/Mac:
   source .venv/bin/activate

   # Install dependencies (much faster with uv)
   uv pip install -r requirements.txt
   ```

   Alternative using traditional pip:

   ```bash
   # Create virtual environment
   python -m venv venv

   # Activate virtual environment
   # On Windows:
   .\venv\Scripts\activate
   # On Linux/Mac:
   source venv/bin/activate

   # Install dependencies
   pip install -r requirements.txt
   ```

> 💡 **Why UV?**
>
> - Up to 10-100x faster than pip
> - Better dependency resolution
> - Built-in virtual environment management
> - Reproducible installations
> - Compatible with all existing Python packages

## 🔑 Getting API Keys

1. **For OpenSubtitles.com:**

   - Register at https://www.opensubtitles.com/en/consumers
   - Create an API consumer account
   - Get your API key from the dashboard

2. **For SubDL.com:**
   - Create an account at https://subdl.com
   - Find your API key under Account Settings

## ⚙️ Configuration

Rename `config.yaml.sample` to `config.yaml` and configure the following sections:

### General Settings

```yaml
general:
  preferred_backend: subdl # Options: opensubtitles, subdl, auto, ask
  skip_interactive_menu: false # Options: true, false
  sync_audio_to_subs: true # Options: true, false, ask
  auto_selection: false # Options: true, false
  opt_force_utf8: true # Options: true, false
```

### OpenSubtitles Configuration

```yaml
opensubtitles:
  username: YOUR_USERNAME
  password: YOUR_PASSWORD
  api_key: YOUR_API_KEY
  user_agent: YOUR_USER_AGENT
  languages:
    English: en
    Arabic: ar
    French: fr
    Japanese: ja
```

### SubDL Configuration

```yaml
subdl:
  api_key: YOUR_SUBDL_API_KEY
  languages:
    English: en
    Arabic: ar
    French: fr
    Japanese: ja
```

### Subtitle Cleaning Configuration

```yaml
ads:
  separator: ","
  file_path: "" # Example: "C:\\clean_subtitles\\ads.txt"
```

### Configuration Examples

#### Automated Mode

```yaml
general:
  preferred_backend: auto
  skip_interactive_menu: true
  sync_audio_to_subs: true
  auto_selection: true
  opt_force_utf8: true

opensubtitles:
  api_key: your_api_key_here
  languages:
    English: en
```

#### Interactive Mode

```yaml
general:
  preferred_backend: ask
  skip_interactive_menu: false
  sync_audio_to_subs: ask

opensubtitles:
  api_key: your_api_key_here
  languages:
    English: en
    Spanish: es
    French: fr
    German: de
```

## 📝 Usage

### Basic Usage

#### Single file

To download subtitles for a single video file:

```bash
python download_subs.py <path/to/video.mkv>
```

#### Multiple files

To download subtitles for multiple video files:

```bash
python download_subs.py <path/to/video1.mp4> <path/to/video2.mkv>
```

#### Folder

To download subtitles for all video files in a folder:

```bash
python download_subs.py <path/to/folder>
```

It will search the folder for video files and download subtitles.

#### Multiple folders

To download subtitles for multiple folders:

```bash
python download_subs.py <path/to/folder1> <path/to/folder2>
```

It will look in both folders for video files and download subtitles.

### Advanced Usage

```bash
# Download with specific language preference
python download_subs.py --lang eng "Movie.mkv"

# Process an entire season of a TV show
python download_subs.py "/TV Shows/Breaking Bad/Season 1"

# Bulk process with specific file types
python download_subs.py "/movies/*.mkv"
```

### System-wide Installation (Optional)

#### For Windows (Send To Menu)

1. Open the "Send To" directory:

   - Press `Win + R`
   - Type `shell:sendto` and press Enter

2. Create `Download Subtitles.bat`:
   ```batch
   @echo off
   cls
   cmd /k "cd /d PATH_TO_PROJECT_FOLDER\venv\Scripts & activate & cd /d PATH_TO_PROJECT_FOLDER & python download_subs.py %*"
   pause
   ```
   Replace `PATH_TO_PROJECT_FOLDER` with your actual project path (e.g., `D:\PycharmProjects\new_opensubtitles`)

After setup, you can right-click any video file or folder and select "Send To" → "Download Subtitles".

#### For Linux/MacOS:

1. Add to your `.bashrc` or `.bash_profile`:

   ```bash
   export PATH="$PATH:$HOME/bin"
   ```

2. Create `$HOME/bin/download_subs.sh`:

   ```bash
   #!/bin/bash

   # Function to activate virtualenv
   activate_venv() {
     source /path/to/project/venv/bin/activate  # Change this path
   }

   deactivate_venv() {
     deactivate
   }

   # Function to run python script
   run_script() {
     python "/path/to/project/download_subs.py" "${@:1}"  # Change this path
   }

   # Activate virtualenv
   activate_venv

   # Run script passing all arguments
   run_script "${@:1}"

   # Deactivate virtualenv
   deactivate_venv
   ```

3. Make it executable:
   ```bash
   chmod +x $HOME/bin/download_subs.sh
   ```

After setup, you can use `download_subs.sh` from anywhere in the terminal.

## ❓ Troubleshooting

### Common Issues

1. **API Key Issues**

   - Ensure your API keys are correctly entered in `config.yaml`
   - Check if you have reached the daily API limit
   - Verify your account status on the respective platforms

2. **Subtitle Sync Problems**

   - Make sure ffmpeg is properly installed
   - Check if the video file is corrupted
   - Try with a different subtitle file

3. **Encoding Issues**
   - Enable `opt_force_utf8: true` in config
   - Try manually converting subtitle file encoding
   - Check if the subtitle file is corrupted

### Error Messages

- `API rate limit exceeded`: Wait for a few minutes and try again
- `No subtitles found`: Try with different search terms or language
- `Failed to sync subtitles`: Check video file integrity and ffmpeg installation

For more help, please [open an issue](https://github.com/ach-raf/opensubtitles_subtitle_downloader/issues) on GitHub.

## 🔗 Credits

- [OpenSubtitles API](https://opensubtitles.stoplight.io/docs/opensubtitles-api/e3750fd63a100-getting-started)
- [ffsubsync](https://github.com/smacke/ffsubsync) for subtitle synchronization
- [UV](https://github.com/astral-sh/uv) for fast Python package management

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

1. **Report Bugs**

   - Open an issue with a clear title and description
   - Add `bug` label to the issue
   - Include steps to reproduce the bug

2. **Suggest Enhancements**

   - Open an issue with your suggestion
   - Add `enhancement` label to the issue
   - Explain why this enhancement would be useful

3. **Submit Pull Requests**
   - Fork the repository
   - Create a new branch for your feature
   - Add your changes
   - Submit a pull request with a clear description

### Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/opensubtitles_subtitle_downloader.git

# Create development branch
git checkout -b feature/your-feature-name

# Make your changes
# Test your changes manually
# Ensure documentation is updated

# Submit PR when ready
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⭐ Show Your Support

If you find this project useful, please consider giving it a star on GitHub!
