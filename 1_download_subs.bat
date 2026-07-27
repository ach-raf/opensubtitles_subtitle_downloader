@echo off
if not defined WT_SESSION (
    start "" wt.exe -d "D:\PycharmProjects\new_opensubtitles" cmd.exe /d /k call "%~f0" %*
    exit /b
)

cls
"D:\PycharmProjects\new_opensubtitles\venv\Scripts\python.exe" "D:\PycharmProjects\new_opensubtitles\download_subs.py" %*
