@echo off
cd /d "%~dp0"
python -m PyInstaller --onefile --windowed --name KierunkiKontrahentow app.py
copy /Y dist\KierunkiKontrahentow.exe .
rmdir /S /Q build
rmdir /S /Q dist
echo.
echo Gotowe - nowy KierunkiKontrahentow.exe w tym folderze.
pause
