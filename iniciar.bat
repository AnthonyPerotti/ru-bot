@echo off
chcp 65001 > nul
title RU Bot UFSM - Servidor Local

echo ===================================================
echo               RU Bot UFSM - Local
echo ===================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERRO] Python nao foi encontrado no PATH do sistema.
    echo Por favor, instale o Python 3.10 ou superior e tente novamente.
    pause
    exit /b 1
)

echo [1/3] Verificando e instalando dependencias...
pip install -r requirements.txt >nul 2>&1
if %errorlevel% neq 0 (
    echo [AVISO] Falha ao executar pip install automaticamente. Continuando...
)

echo.
echo [2/3] Iniciando interface web local (http://localhost:3456)...
start "" http://localhost:3456
start /b python server.py

echo.
echo [3/3] Iniciando o agendador em segundo plano...
echo O bot esta ativo e monitorando os horarios de agendamento (BRT).
echo Para fechar tudo, basta fechar esta janela.
echo.
python scheduler.py
