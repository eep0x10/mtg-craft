@echo off
set PATH=%PATH%;C:\Program Files\Docker\Docker\resources\bin
echo Iniciando MTG Craft...
docker compose -f "%~dp0docker-compose.yml" up --build -d
echo.
echo Acesse: http://localhost:5001
