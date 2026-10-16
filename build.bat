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

rem --uac-admin: ゲームが管理者権限で動くので、タイマーも管理者権限で起動させる
rem (一般権限だとゲーム操作中のキーが読めない)。起動時に UAC の確認が出る。
rem --specpath build にすると相対パスは build\ 基準で解釈されるので、
rem アイコンとソースのパスは絶対パスで渡す。
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --windowed --uac-admin ^
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
