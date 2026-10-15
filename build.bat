@echo off
chcp 65001 >nul
rem BPSRGimmickTimer.exe を作る (PyInstaller の onefile)。
rem 初回は .venv を作ってビルド用の道具を入れるので少し時間がかかる。
rem 出来た exe はこのフォルダの直下に置かれる。リポジトリには入れず、GitHub のリリースに添付する。
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3.11 -m venv .venv || goto :error
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements-build.txt || goto :error

rem --specpath build にすると相対パスは build\ 基準で解釈されるので、
rem アイコンとソースのパスは絶対パスで渡す。
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --windowed ^
    --name BPSRGimmickTimer ^
    --icon "%~dp0assets\icon.ico" ^
    --paths "%~dp0src" ^
    --distpath "%~dp0." ^
    --workpath "%~dp0build" ^
    --specpath "%~dp0build" ^
    "%~dp0run.py" || goto :error

echo.
echo 完了: %~dp0BPSRGimmickTimer.exe
exit /b 0

:error
echo.
echo ビルドに失敗しました。
exit /b 1
