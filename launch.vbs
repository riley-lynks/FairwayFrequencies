' =============================================================================
' launch.vbs — Fairway Frequencies Silent Launcher
' =============================================================================
' HOW TO USE:
'   Double-click this file. It will:
'   1. Start the Python web server completely silently (no CMD window)
'   2. Wait 3 seconds for Flask to initialize
'   3. Open http://localhost:5000 in your default browser
'
' WHY .vbs instead of .bat?
'   A .bat file always flashes a CMD window for a split second when it runs.
'   A .vbs script uses Windows Script Host which runs entirely in the background
'   with zero visible windows — nothing interrupts your game.
'
' TO STOP THE SERVER:
'   Open Task Manager > Details tab > find pythonw.exe > End Task
' =============================================================================

Dim shell, http, status
Set shell = CreateObject("WScript.Shell")
Set http  = CreateObject("MSXML2.XMLHTTP")

' Project root — same folder as this script
Dim projectRoot
projectRoot = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))

' Check if server is already running
On Error Resume Next
http.Open "GET", "http://localhost:5000/api/status", False
http.Send
status = http.Status
On Error GoTo 0

If status = 200 Then
    ' Already running — just open the browser
    shell.Run "http://localhost:5000", 1, False
Else
    ' Start the server silently using pythonw.exe (0 = hidden window)
    Dim pythonw
    pythonw = "C:\Users\riley\AppData\Local\Programs\Python\Python311\pythonw.exe"
    shell.Run Chr(34) & pythonw & Chr(34) & " -X utf8 server.py", 0, False

    ' Wait 3 seconds for Flask to initialize
    WScript.Sleep 3000

    ' Open the browser
    shell.Run "http://localhost:5000", 1, False
End If
