@echo off
chcp 65001 >nul 2>&1
title Xiaoyi RAG Frontend
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\start-frontend.ps1"
timeout /t 2 /nobreak >nul
