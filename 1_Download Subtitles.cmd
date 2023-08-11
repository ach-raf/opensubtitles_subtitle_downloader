@echo off
cls
cmd /k "cd /d C:\programming\new_opensubtitles\venv\Scripts & activate & cd /d  C:\programming\new_opensubtitles & python download_subs.py %*
pause
