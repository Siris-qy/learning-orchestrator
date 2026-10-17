@echo off
setlocal
set "PLUGIN_ROOT=%~dp0.."
set "PYTHONPATH=%PLUGIN_ROOT%\src"
if exist "%PLUGIN_ROOT%\.venv\Scripts\python.exe" (
  "%PLUGIN_ROOT%\.venv\Scripts\python.exe" -m learning_orchestrator.dashboard %*
) else (
  python -m learning_orchestrator.dashboard %*
)
endlocal
