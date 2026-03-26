Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d ""F:\Claude Code\LoFi Youtube Automation"" && python server.py", 0, False
WScript.Sleep 2500
WshShell.Run "http://localhost:5000"
