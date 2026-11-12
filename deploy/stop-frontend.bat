@echo off
chcp 65001 >nul 2>&1
title Stop Xiaoyi RAG Frontend
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\stop-frontend.ps1"
timeout /t 3 /nobreak >nul
