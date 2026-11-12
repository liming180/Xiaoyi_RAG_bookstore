@echo off
chcp 65001 >nul 2>&1
title Xiaoyi RAG Backend
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\start-backend.ps1"
echo.
echo Backend is running in background. Press any key to close this window...
pause >nul
