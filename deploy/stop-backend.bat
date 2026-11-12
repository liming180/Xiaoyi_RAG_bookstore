@echo off
chcp 65001 >nul 2>&1
title Stop Xiaoyi RAG Backend
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-backend.ps1"
timeout /t 3 /nobreak >nul
