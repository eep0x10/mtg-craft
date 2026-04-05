@echo off
echo Iniciando MTG Craft em http://localhost:5001
wsl -e bash -c "cd /mnt/c/Users/eep0x10/Projects/dev/card-pdf-gen && python3 app.py"
pause
