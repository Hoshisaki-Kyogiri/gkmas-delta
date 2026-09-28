@echo off
rem No arguments = the web console; any argument = the command-line tool as before.
if "%~1"=="" (
    call "%~dp0umegkmas.bat" --web
) else (
    call "%~dp0umegkmas.bat" %*
)
