import json
import subprocess
import sys


def test_tui_entry_import_does_not_load_legacy_providers():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, sys; import download_subs; "
                "print(json.dumps(sorted(name for name in sys.modules "
                "if name in {'library.OpenSubtitles', 'library.SubDL', "
                "'library.SubSource', 'library.subtitle_utils', 'thefuzz'})))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == []
