@echo off
setlocal
cd /d "%~dp0"
if /I "%~1"=="--silent" set "SWOOSH_SILENT_START=1"

set "PORT=8081"
set "SWOOSH_HOST=127.0.0.1"
set "SWOOSH_ROOT=%CD%"
set "SWOOSH_JDBC_URL=jdbc:sqlserver://localhost:1433;databaseName=BeginnerRunningShoesDB;encrypt=true;trustServerCertificate=true;integratedSecurity=true;authenticationScheme=NativeAuthentication"
set "SWOOSH_COOKIE_SECURE=false"
set "TRUST_PROXY=false"
set "APP_JAR=%CD%\java-backend\target\swoosh-store-1.0.0.jar"
set "SQL_AUTH_DIR=%CD%\java-backend\target\native"

where java >nul 2>&1
if errorlevel 1 (
    echo Java was not found. Install JDK 25 or newer and try again.
    if not defined SWOOSH_SILENT_START pause
    exit /b 1
)

if not exist "%APP_JAR%" (
    where mvn >nul 2>&1
    if errorlevel 1 (
        echo The Java application JAR is missing and Maven was not found.
        echo Install Maven 3.9 or newer, then run this file again.
        if not defined SWOOSH_SILENT_START pause
        exit /b 1
    )
    call mvn -f "%CD%\java-backend\pom.xml" -DskipTests package
    if errorlevel 1 (
        echo Java build failed.
        if not defined SWOOSH_SILENT_START pause
        exit /b 1
    )
)

powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.IO.Compression.FileSystem; $native='%SQL_AUTH_DIR%'; New-Item -ItemType Directory -Force -Path $native | Out-Null; $dllPath=Join-Path $native 'mssql-jdbc_auth-12.8.1.x64.dll'; if (-not (Test-Path $dllPath)) { $archive=Join-Path $env:TEMP 'mssql-jdbc_auth-12.8.1.zip'; & curl.exe -L --fail --silent --show-error 'https://github.com/microsoft/mssql-jdbc/releases/download/v12.8.1/mssql-jdbc_auth.zip' -o $archive; if ($LASTEXITCODE -ne 0) { throw 'Unable to download Microsoft SQL Server Windows authentication.' }; $zip=[IO.Compression.ZipFile]::OpenRead($archive); try { $entry=$zip.GetEntry('x64/mssql-jdbc_auth-12.8.1.x64.dll'); if ($null -eq $entry) { throw 'Microsoft SQL Server authentication DLL was not found.' }; $source=$entry.Open(); try { $target=[IO.File]::Create($dllPath); try { $source.CopyTo($target) } finally { $target.Dispose() } } finally { $source.Dispose() } } finally { $zip.Dispose(); Remove-Item $archive -Force } }"
if errorlevel 1 (
    echo Could not prepare SQL Server Windows authentication.
    if not defined SWOOSH_SILENT_START pause
    exit /b 1
)
set "PATH=%SQL_AUTH_DIR%;%PATH%"

powershell -NoProfile -Command "try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8081/api/health' -TimeoutSec 2; if ($health.status -eq 'ok') { Start-Process 'http://127.0.0.1:8081/'; exit 0 } } catch {}; exit 1"
if not errorlevel 1 (
    echo Swoosh Store is already running. Opening the browser.
    exit /b 0
)

start "Swoosh Store Backend" /min java -Djava.library.path="%SQL_AUTH_DIR%" -jar "%APP_JAR%"
powershell -NoProfile -Command "$deadline = (Get-Date).AddSeconds(60); do { try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8081/api/health' -TimeoutSec 2; if ($health.status -eq 'ok') { Start-Process 'http://127.0.0.1:8081/'; exit 0 } } catch {}; Start-Sleep -Seconds 1 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
    echo The Java backend did not start. Check the minimized Swoosh Store Backend window.
    if not defined SWOOSH_SILENT_START pause
    exit /b 1
)

echo Swoosh Store is running at http://127.0.0.1:8081/
exit /b 0
