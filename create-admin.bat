@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo ==========================================
echo  SWOOSH STORE - CREATE LOCAL SQLITE ADMIN
echo ==========================================
echo  Username: admin
echo  Enter a private password (at least 12 characters).
echo.

if not exist "store_server.py" (
    echo ERROR: Missing store_server.py.
    pause
    exit /b 1
)
where py >nul 2>&1
if not errorlevel 1 goto use_py
where python >nul 2>&1
if not errorlevel 1 goto use_python
echo ERROR: Python not found. Install Python 3.10 or newer.
pause
exit /b 1

:use_py
py -3 store_server.py create-admin --username admin
set "CREATE_RESULT=%errorlevel%"
goto check_result

:use_python
python store_server.py create-admin --username admin
set "CREATE_RESULT=%errorlevel%"
goto check_result

:check_result
if not "%CREATE_RESULT%"=="0" (
    echo.
    echo Admin creation failed. Review the error above.
    pause
    exit /b 1
)
echo.
echo Local admin created. To start the site: python store_server.py
echo Log in: http://127.0.0.1:8000/#login?role=admin
echo.
echo For Render: add SWOOSH_ADMIN_PASSWORD in Render Environment.
echo Do NOT push the local SQLite database to GitHub.
pause
