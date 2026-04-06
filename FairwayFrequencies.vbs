Dim shell, http, status
Set shell = CreateObject("WScript.Shell")
Set http  = CreateObject("MSXML2.XMLHTTP")

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
    Dim pythonw, projectRoot
    pythonw = "C:\Users\riley\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
    projectRoot = "F:\Claude Code\LoFi Youtube Automation"
    shell.Run Chr(34) & pythonw & Chr(34) & " -X utf8 """ & projectRoot & "\server.py""", 0, False

    ' Wait 3 seconds for Flask to initialize
    WScript.Sleep 3000

    ' Open the browser
    shell.Run "http://localhost:5000", 1, False
End If
