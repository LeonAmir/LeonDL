Option Explicit
Dim shell, fso, root, launcher, venvPythonw, code, answer
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = root & "\launcher.pyw"
venvPythonw = root & "\.venv\Scripts\pythonw.exe"

If fso.FileExists(venvPythonw) Then
    shell.Run Chr(34) & venvPythonw & Chr(34) & " " & Chr(34) & launcher & Chr(34), 0, False
    WScript.Quit 0
End If

code = shell.Run("cmd /d /c where pyw.exe >nul 2>nul", 0, True)
If code = 0 Then
    shell.Run "pyw -3 " & Chr(34) & launcher & Chr(34), 0, False
    WScript.Quit 0
End If

code = shell.Run("cmd /d /c where pythonw.exe >nul 2>nul", 0, True)
If code = 0 Then
    shell.Run "pythonw " & Chr(34) & launcher & Chr(34), 0, False
    WScript.Quit 0
End If

answer = MsgBox("Python 3.10 or newer was not found. Run the Windows setup now?", vbYesNo + vbExclamation, "LeonDL")
If answer = vbYes Then
    shell.Run Chr(34) & root & "\setup_windows.bat" & Chr(34), 1, False
End If
