Attribute VB_Name = "TranslationDashboard"
Option Explicit

' -------------------------------------------------------------------------
' MAIN MACRO: Build the interactive dashboard
' Run this AFTER pasting your data into the "Raw Logs" sheet.
' -------------------------------------------------------------------------
Sub BuildReport()
    Dim wsRaw As Worksheet
    Dim wsDash As Worksheet
    Dim lastRow As Long
    Dim botCol As New Collection
    Dim dateCol As New Collection
    Dim i As Long
    Dim botName As Variant
    Dim dateVal As Variant
    Dim chartObj As ChartObject
    Dim itm As Variant
    
    Application.ScreenUpdating = False
    
    ' 1. Validate "Raw Logs" sheet exists
    On Error Resume Next
    Set wsRaw = ThisWorkbook.Sheets("Raw Logs")
    On Error GoTo 0
    
    If wsRaw Is Nothing Then
        MsgBox "Error: Could not find a sheet named 'Raw Logs'. Please create it and paste your data there.", vbCritical
        Exit Sub
    End If
    
    ' Find last row of Raw Logs
    lastRow = wsRaw.Cells(wsRaw.Rows.Count, "A").End(xlUp).Row
    If lastRow < 2 Then
        MsgBox "No data found in 'Raw Logs' sheet. Please paste your data first.", vbExclamation
        Exit Sub
    End If
    
    ' 2. Setup "Dashboard" sheet
    On Error Resume Next
    Set wsDash = ThisWorkbook.Sheets("Dashboard")
    On Error GoTo 0
    
    If wsDash Is Nothing Then
        Set wsDash = ThisWorkbook.Sheets.Add(Before:=wsRaw)
        wsDash.Name = "Dashboard"
    End If
    
    ' Clear existing Dashboard to start fresh
    ClearDashboard wsDash
    wsDash.Activate
    ActiveWindow.DisplayGridlines = False
    
    ' 3. Get Unique Bots and Dates (Mac Compatible)
    For i = 2 To lastRow
        botName = wsRaw.Cells(i, 6).Value ' Column F is Bot
        dateVal = wsRaw.Cells(i, 2).Value ' Column B is Date
        
        If Trim(CStr(botName)) <> "" Then
            On Error Resume Next
            botCol.Add CStr(botName), CStr(botName)
            On Error GoTo 0
        End If
        
        If Trim(CStr(dateVal)) <> "" Then
            On Error Resume Next
            dateCol.Add CStr(dateVal), CStr(dateVal)
            On Error GoTo 0
        End If
    Next i
    
    ' Fallbacks if empty
    If botCol.Count = 0 Then botCol.Add "System", "System"
    If dateCol.Count = 0 Then dateCol.Add Date, CStr(Date)
    
    ' 4. Write Unique Lists to Hidden Columns (Y & Z) for Dropdown Sources
    ' This is much more robust than comma-separated strings!
    wsDash.Range("Y1").Value = "Bots"
    For i = 1 To botCol.Count
        wsDash.Cells(i + 1, 25).Value = botCol(i) ' Col Y
    Next i
    
    wsDash.Range("Z1").Value = "Dates"
    For i = 1 To dateCol.Count
        wsDash.Cells(i + 1, 26).Value = dateCol(i) ' Col Z
        wsDash.Cells(i + 1, 26).NumberFormat = "m/d/yyyy"
    Next i
    
    ' Hide helper columns
    wsDash.Columns("Y:Z").EntireColumn.Hidden = True
    
    ' 5. Build Dashboard UI (Title & KPIs)
    With wsDash.Range("B2:G3")
        .Merge
        .Value = "Course Translation Hub Analytics"
        .Font.Size = 22
        .Font.Bold = True
        .Font.Color = RGB(44, 62, 80)
        .Interior.Color = RGB(236, 240, 241)
        .HorizontalAlignment = xlCenter
        .VerticalAlignment = xlCenter
    End With
    
    ' ADD COURSE INFO
    Dim courseName As String
    Dim courseCode As String
    Dim rawMsg As String
    courseName = "Unknown Course"
    courseCode = "UNKNOWN"
    For i = 2 To lastRow
        If wsRaw.Cells(i, 5).Value = "Course Info" Then
            rawMsg = wsRaw.Cells(i, 10).Value
            If InStr(rawMsg, "|") > 0 Then
                courseName = Split(rawMsg, "|")(0)
                courseCode = Split(rawMsg, "|")(1)
            End If
        End If
    Next i
    
    With wsDash.Range("B4:G4")
        .Merge
        .Value = "Course: " & courseName & " (" & courseCode & ")"
        .Font.Size = 14
        .Font.Bold = True
        .HorizontalAlignment = xlCenter
        .VerticalAlignment = xlCenter
    End With
    
    wsDash.Range("B5").Value = "Total Events"
    wsDash.Range("B6").Formula = "=COUNTA('Raw Logs'!A:A)-1"
    
    wsDash.Range("D5").Value = "Successful Operations"
    wsDash.Range("D6").Formula = "=COUNTIF('Raw Logs'!I:I, ""Success"")"
    
    wsDash.Range("F5").Value = "Errors / Warnings"
    wsDash.Range("F6").Formula = "=COUNTIF('Raw Logs'!I:I, ""Error"") + COUNTIF('Raw Logs'!I:I, ""Warning"")"
    
    With wsDash.Range("B5,D5,F5")
        .Font.Bold = True
        .Font.Color = vbWhite
        .Interior.Color = RGB(41, 128, 185)
        .HorizontalAlignment = xlCenter
        .Borders.LineStyle = xlContinuous
    End With
    With wsDash.Range("B6,D6,F6")
        .Font.Size = 18
        .Font.Bold = True
        .Interior.Color = RGB(214, 234, 248)
        .HorizontalAlignment = xlCenter
        .Borders.LineStyle = xlContinuous
    End With
    
    ' 6. Create Interactive Dropdowns
    
    ' Bot Dropdown (C8)
    wsDash.Range("B8").Value = "Filter Bot Activity:"
    wsDash.Range("B8").Font.Bold = True
    wsDash.Range("B8").Font.Size = 12
    
    With wsDash.Range("C8").Validation
        .Delete
        .Add Type:=xlValidateList, AlertStyle:=xlValidAlertStop, Operator:=xlBetween, Formula1:="=$Y$2:$Y$" & (botCol.Count + 1)
        .IgnoreBlank = True
        .InCellDropdown = True
    End With
    wsDash.Range("C8").Value = botCol(1)
    
    ' Date Dropdown (C9)
    wsDash.Range("B9").Value = "Filter Date:"
    wsDash.Range("B9").Font.Bold = True
    wsDash.Range("B9").Font.Size = 12
    
    With wsDash.Range("C9").Validation
        .Delete
        .Add Type:=xlValidateList, AlertStyle:=xlValidAlertStop, Operator:=xlBetween, Formula1:="=$Z$2:$Z$" & (dateCol.Count + 1)
        .IgnoreBlank = True
        .InCellDropdown = True
    End With
    wsDash.Range("C9").Value = dateCol(1)
    wsDash.Range("C9").NumberFormat = "m/d/yyyy"
    
    ' Style Dropdowns
    With wsDash.Range("C8:C9")
        .Interior.Color = RGB(255, 255, 224)
        .Borders.LineStyle = xlContinuous
        .Font.Bold = True
    End With
    
    ' Dynamic Summary
    wsDash.Range("B10").Value = "Events for Selection:"
    wsDash.Range("C10").Formula = "=COUNTIFS('Raw Logs'!F:F, $C$8, 'Raw Logs'!B:B, $C$9)"
    wsDash.Range("C10").Font.Bold = True
    wsDash.Range("C10").Font.Color = RGB(41, 128, 185)
    wsDash.Range("C10").Font.Size = 12
    
    ' 7. Build Visible Timeline Table (Hour only)
    wsDash.Range("B12").Value = "Hourly Activity Timeline"
    wsDash.Range("B12").Font.Bold = True
    wsDash.Range("B12").Font.Size = 14
    
    wsDash.Range("B13").Value = "Hour"
    wsDash.Range("C13").Value = "Event Count"
    
    With wsDash.Range("B13:C13")
        .Font.Bold = True
        .Font.Color = vbWhite
        .Interior.Color = RGB(52, 73, 94)
        .HorizontalAlignment = xlCenter
        .Borders.LineStyle = xlContinuous
    End With
    
    ' 0 to 23 Hours
    For i = 0 To 23
        wsDash.Cells(i + 14, 2).Value = i ' Hour
        ' Formula counts based on Bot (C8) AND Date (C9)
        wsDash.Cells(i + 14, 3).Formula = "=COUNTIFS('Raw Logs'!C:C, B" & (i + 14) & ", 'Raw Logs'!F:F, $C$8, 'Raw Logs'!B:B, $C$9)"
        
        With wsDash.Range(wsDash.Cells(i + 14, 2), wsDash.Cells(i + 14, 3))
            .Borders.LineStyle = xlContinuous
            .HorizontalAlignment = xlCenter
        End With
    Next i
    
    ' 8. Create Dynamic Area Chart
    Set chartObj = wsDash.ChartObjects.Add(Left:=wsDash.Range("E8").Left, Top:=wsDash.Range("E8").Top, Width:=480, Height:=300)
    With chartObj.Chart
        .ChartType = xlArea
        
        ' Clear auto-generated series guesses
        Do While .SeriesCollection.Count > 0
            .SeriesCollection(1).Delete
        Loop
        
        ' Add the correct series manually
        With .SeriesCollection.NewSeries
            .Name = "=""Event Count"""
            .XValues = wsDash.Range("B14:B37") ' Hour (0-23)
            .Values = wsDash.Range("C14:C37")  ' Count
        End With
        
        .PlotVisibleOnly = False ' Ensure data plots
        
        ' Chart Styling
        .HasTitle = True
        .ChartTitle.Text = "Hourly Activity Trend (Dynamically Linked to Dropdowns)"
        .ChartTitle.Font.Size = 14
        
        ' Axes
        .Axes(xlCategory, xlPrimary).HasTitle = True
        .Axes(xlCategory, xlPrimary).AxisTitle.Text = "Hour of Day (0-23)"
        .Axes(xlValue, xlPrimary).HasTitle = True
        .Axes(xlValue, xlPrimary).AxisTitle.Text = "Event Count"
        
        ' Remove Legend
        .HasLegend = False
        
        ' Make area transparent blue (Safely for Mac)
        On Error Resume Next
        If .SeriesCollection.Count > 0 Then
            .SeriesCollection(1).Format.Fill.ForeColor.RGB = RGB(93, 173, 226)
            .SeriesCollection(1).Format.Fill.Transparency = 0.3
        End If
        On Error GoTo 0
    End With
    
    ' ADD SKIPPED FILES
    wsDash.Range("I5").Value = "Skipped Files"
    With wsDash.Range("I5")
        .Font.Bold = True
        .Font.Color = vbWhite
        .Interior.Color = RGB(52, 73, 94)
        .HorizontalAlignment = xlCenter
        .Borders.LineStyle = xlContinuous
    End With
    wsDash.Columns("I:I").ColumnWidth = 40
    
    Dim skipRow As Long
    skipRow = 6
    For i = 2 To lastRow
        If InStr(wsRaw.Cells(i, 5).Value, "Skipped") > 0 Then
            wsDash.Cells(skipRow, 9).Value = wsRaw.Cells(i, 8).Value
            wsDash.Cells(skipRow, 9).Borders.LineStyle = xlContinuous
            skipRow = skipRow + 1
        End If
    Next i

    ' ADD EXTERNAL LINKS LOG
    Dim linkRow As Long
    linkRow = 40
    wsDash.Range("B" & linkRow).Value = "External Links Log"
    wsDash.Range("B" & linkRow).Font.Bold = True
    wsDash.Range("B" & linkRow).Font.Size = 14
    
    wsDash.Range("B" & (linkRow + 1)).Value = "Location (Page Name)"
    wsDash.Range("C" & (linkRow + 1)).Value = "Link Text"
    wsDash.Range("D" & (linkRow + 1)).Value = "Link"
    
    With wsDash.Range("B" & (linkRow + 1) & ":D" & (linkRow + 1))
        .Font.Bold = True
        .Font.Color = vbWhite
        .Interior.Color = RGB(52, 73, 94)
        .HorizontalAlignment = xlCenter
        .Borders.LineStyle = xlContinuous
    End With
    
    linkRow = linkRow + 2
    Dim linkParts() As String
    For i = 2 To lastRow
        If wsRaw.Cells(i, 5).Value = "External Link" Then
            wsDash.Cells(linkRow, 2).Value = wsRaw.Cells(i, 8).Value ' File Name
            rawMsg = wsRaw.Cells(i, 10).Value
            If InStr(rawMsg, " | ") > 0 Then
                linkParts = Split(rawMsg, " | ", 2)
                wsDash.Cells(linkRow, 3).Value = linkParts(0)
                If UBound(linkParts) >= 1 Then
                    wsDash.Cells(linkRow, 4).Value = linkParts(1)
                End If
            End If
            
            With wsDash.Range("B" & linkRow & ":D" & linkRow)
                .Borders.LineStyle = xlContinuous
            End With
            
            linkRow = linkRow + 1
        End If
    Next i
    
    ' Final touch: adjust column widths
    wsDash.Columns("A:A").ColumnWidth = 2
    wsDash.Columns("B:D").EntireColumn.AutoFit
    
    Application.ScreenUpdating = True
    MsgBox "Interactive Report successfully built!" & vbCrLf & vbCrLf & _
           "You can now filter by both BOT and DATE using the dropdowns.", vbInformation
End Sub

' -------------------------------------------------------------------------
' Helper Macro: Clears just the dashboard sheet
' -------------------------------------------------------------------------
Sub ClearDashboard(wsDash As Worksheet)
    Dim chrt As ChartObject
    
    ' Delete all charts
    For Each chrt In wsDash.ChartObjects
        chrt.Delete
    Next chrt
    
    ' Clear all cells, validation, and formats
    wsDash.Cells.Clear
    wsDash.Cells.Validation.Delete
    wsDash.Columns.EntireColumn.Hidden = False
End Sub

' -------------------------------------------------------------------------
' UTILITY MACRO: Clear the dashboard report (keeps raw data intact)
' -------------------------------------------------------------------------
Sub ClearDashboardData()
    Dim wsDash As Worksheet
    Dim ans As VbMsgBoxResult
    
    ans = MsgBox("Are you sure you want to clear the dashboard report? Your Raw Logs will NOT be affected.", vbYesNo + vbQuestion, "Confirm Clear Dashboard")
    If ans = vbNo Then Exit Sub
    
    Application.ScreenUpdating = False
    
    On Error Resume Next
    Set wsDash = ThisWorkbook.Sheets("Dashboard")
    On Error GoTo 0
    
    ' Clear Dashboard completely
    If Not wsDash Is Nothing Then
        ClearDashboard wsDash
    End If
    
    Application.ScreenUpdating = True
    MsgBox "Dashboard report has been cleared. Your raw data is untouched.", vbInformation
End Sub
