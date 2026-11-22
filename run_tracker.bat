@echo off
REM Double-click to launch the Bug Solution Tracker (no console window).
cd /d "%~dp0"
where pythonw >nul 2>nul && (start "" pythonw app.py & exit /b)
where pyw >nul 2>nul && (start "" pyw app.py & exit /b)
where python >nul 2>nul && (python app.py & exit /b)
echo Python was not found. Install it from https://www.python.org/downloads/ (tick "Add to PATH").
pause
