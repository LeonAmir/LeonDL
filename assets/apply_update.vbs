' LeonDL self-update applier.
' Launched by the app (detached wscript) after the user confirms an update.
' Reads apply_update.marker (hex-encoded KEY=VALUE lines), waits for the
' running EXEs to exit, replaces them with the staged build, copies the
' bundled docs/extension and relaunches the new EXE.
Option Explicit
On Error Resume Next

Dim fso, objShell
Set fso = CreateObject("Scripting.FileSystemObject")
Set objShell = CreateObject("WScript.Shell")

' ---------------------------------------------------------------- logging
Dim LOG_PATH
LOG_PATH = ""

Sub LogLine(text)
    Dim stream
    If LOG_PATH = "" Then Exit Sub
    Set stream = fso.OpenTextFile(LOG_PATH, 8, True)
    stream.WriteLine Now() & " " & text
    stream.Close
End Sub

' ------------------------------------------------------------ hex decode
Function HexDecode(value)
    Dim i, out
    out = ""
    For i = 1 To Len(value) Step 2
        out = out & Chr(CInt("&H" & Mid(value, i, 2)))
    Next
    HexDecode = out
End Function

' ------------------------------------------------------------- marker io
Dim RELEASE_DIR, STAGING_DIR
Dim MAIN_OLD, MAIN_NEW, NATIVE_OLD, NATIVE_NEW

Sub ReadMarker()
    Dim markerPath, stream, line, parts, key, value
    markerPath = fso.GetParentFolderName(WScript.ScriptFullName) & "\apply_update.marker"
    Set stream = fso.OpenTextFile(markerPath, 1, False)
    Do Until stream.AtEndOfStream
        line = stream.ReadLine
        parts = Split(line, "=", 2)
        If UBound(parts) = 1 Then
            key = parts(0)
            value = HexDecode(parts(1))
            Select Case key
                Case "RELEASE_DIR": RELEASE_DIR = value
                Case "STAGING_DIR": STAGING_DIR = value
                Case "MAIN_OLD":    MAIN_OLD = value
                Case "MAIN_NEW":    MAIN_NEW = value
                Case "NATIVE_OLD":  NATIVE_OLD = value
                Case "NATIVE_NEW":  NATIVE_NEW = value
            End Select
        End If
    Loop
    stream.Close
    LOG_PATH = RELEASE_DIR & "\_update_log.txt"
End Sub

' --------------------------------------------------------- process wait
Function ProcessRunning(exeName)
    Dim p, output
    Set p = objShell.Exec("tasklist /FI ""IMAGENAME eq " & exeName & """")
    output = p.StdOut.ReadAll
    If InStr(1, output, exeName, 1) > 0 Then
        ProcessRunning = True
    Else
        ProcessRunning = False
    End If
End Function

Sub WaitForExit(exeName, maxSeconds)
    Dim waited
    waited = 0
    Do While ProcessRunning(exeName) And waited < maxSeconds
        WScript.Sleep 500
        waited = waited + 1
    Loop
    If waited >= maxSeconds Then LogLine "WARN: " & exeName & " still running after " & maxSeconds & "s"
End Sub

' ---------------------------------------------------------------- apply
Sub Apply()
    Dim srcPath, dstPath
    RELEASE_DIR = fso.GetAbsolutePathName(RELEASE_DIR)
    STAGING_DIR = fso.GetAbsolutePathName(STAGING_DIR)

    ' 1. Wait for the running processes to exit.
    If MAIN_OLD <> "" Then WaitForExit MAIN_OLD, 120
    If NATIVE_OLD <> "" Then WaitForExit NATIVE_OLD, 30

    ' 2. Replace the main EXE (running EXE is unlocked once the process exits).
    srcPath = STAGING_DIR & "\" & MAIN_NEW
    dstPath = RELEASE_DIR & "\" & MAIN_OLD
    If fso.FileExists(STAGING_DIR & "\" & MAIN_OLD) Then
        fso.MoveFile STAGING_DIR & "\" & MAIN_OLD, dstPath & ".old"
        LogLine "renamed old main -> " & MAIN_OLD & ".old"
    End If
    If fso.FileExists(srcPath) Then
        fso.MoveFile srcPath, RELEASE_DIR & "\" & MAIN_NEW
        LogLine "installed " & MAIN_NEW
    End If

    ' 3. Replace the native host EXE.
    srcPath = STAGING_DIR & "\" & NATIVE_NEW
    If fso.FileExists(STAGING_DIR & "\" & NATIVE_OLD) Then
        fso.MoveFile STAGING_DIR & "\" & NATIVE_OLD, RELEASE_DIR & "\" & NATIVE_OLD & ".old"
        LogLine "renamed old native -> " & NATIVE_OLD & ".old"
    End If
    If fso.FileExists(srcPath) Then
        fso.MoveFile srcPath, RELEASE_DIR & "\" & NATIVE_NEW
        LogLine "installed " & NATIVE_NEW
    End If

    ' 4. Copy the bundled docs beside the EXE.
    Dim docName
    For Each docName In Array("README.md", "VERSION", "LICENSE")
        If fso.FileExists(STAGING_DIR & "\" & docName) Then
            fso.CopyFile STAGING_DIR & "\" & docName, RELEASE_DIR & "\" & docName, True
        End If
    Next

    ' 5. Replace the chrome extension bundle (release-dir copy).
    If fso.FolderExists(STAGING_DIR & "\chrome_extension") Then
        If fso.FolderExists(RELEASE_DIR & "\chrome_extension") Then
            fso.DeleteFolder RELEASE_DIR & "\chrome_extension", True
        End If
        fso.MoveFolder STAGING_DIR & "\chrome_extension", RELEASE_DIR & "\chrome_extension"
        LogLine "chrome_extension refreshed"
    End If

    ' 6. Cleanup: stale .old files and the staging directory.
    Dim cleanup
    For Each cleanup In Array(MAIN_OLD & ".old", NATIVE_OLD & ".old")
        If fso.FileExists(RELEASE_DIR & "\" & cleanup) Then
            fso.DeleteFile RELEASE_DIR & "\" & cleanup, True
        End If
    Next
    If fso.FolderExists(STAGING_DIR) Then
        fso.DeleteFolder STAGING_DIR, True
    End If

    LogLine "update applied, launching " & MAIN_NEW
End Sub

' ----------------------------------------------------------------- main
ReadMarker
If RELEASE_DIR = "" Or MAIN_NEW = "" Or STAGING_DIR = "" Then
    LogLine "FATAL: incomplete marker"
    WScript.Quit 1
End If
Apply
' Give the old process a moment to fully release the folder, then relaunch.
WScript.Sleep 1200
If fso.FileExists(RELEASE_DIR & "\" & MAIN_NEW) Then
    objShell.Run """" & RELEASE_DIR & "\" & MAIN_NEW & """", 1, False
End If
WScript.Quit 0