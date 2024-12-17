@echo off
cls
cmd /k "cd /d D:\PycharmProjects\new_opensubtitles\venv\Scripts & activate & cd /d  D:\PycharmProjects\new_opensubtitles & python download_subs.py %*
pause