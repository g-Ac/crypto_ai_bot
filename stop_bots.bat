@echo off
echo Parando Crypto AI Bot...
taskkill /f /fi "WINDOWTITLE eq *supervisor*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq *main.py*" >nul 2>&1
taskkill /f /fi "WINDOWTITLE eq *pump_scanner*" >nul 2>&1
:: Mata todos os python rodando os scripts do bot
for /f "tokens=2" %%a in ('wmic process where "commandline like '%%supervisor.py%%'" get processid /value 2^>nul ^| find "="') do taskkill /f /pid %%a >nul 2>&1
for /f "tokens=2" %%a in ('wmic process where "commandline like '%%main.py%%'" get processid /value 2^>nul ^| find "="') do taskkill /f /pid %%a >nul 2>&1
for /f "tokens=2" %%a in ('wmic process where "commandline like '%%pump_scanner.py%%'" get processid /value 2^>nul ^| find "="') do taskkill /f /pid %%a >nul 2>&1
echo Bots parados.
pause
