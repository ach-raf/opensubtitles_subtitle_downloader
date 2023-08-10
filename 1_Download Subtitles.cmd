@echo off
cls
cmd /k "cd /d C:\programming\sync_subs\venv\Scripts & activate & cd /d    C:\programming\sync_subs & python sync_subs.py %*
pause