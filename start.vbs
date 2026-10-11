Option Explicit

Dim fso, shell, here, py, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)

Function FindPython()
  Dim list, i
  list = Array( _
    "C:\Program Files\Python312\pythonw.exe", _
    "C:\Program Files\Python311\pythonw.exe", _
    "C:\Program Files\Python310\pythonw.exe", _
    "C:\Program Files (x86)\Python312\pythonw.exe" _
  )
  For i = 0 To UBound(list)
    If fso.FileExists(list(i)) Then
      FindPython = list(i)
      Exit Function
    End If
  Next
  FindPython = "pythonw.exe"
End Function

py = FindPython()
cmd = """" & py & """ """ & here & "\run.pyw"""
shell.Run cmd, 0, False
