# A WinForms grid that, like Excel, opens an editor control on the first
# character typed into a cell, and a Ctrl+G shortcut that opens a small
# modal dialog. The live tests read what arrived from the window title:
# "grid-probe <cells> goto:<text>", cells row by row ("a|b/c|d").
Add-Type -AssemblyName System.Windows.Forms

$script:goto = ''
$form = New-Object Windows.Forms.Form
$form.Text = 'grid-probe'
$form.StartPosition = 'Manual'
$form.SetBounds(120, 120, 460, 260)
$form.KeyPreview = $true

$grid = New-Object Windows.Forms.DataGridView
$grid.Dock = 'Fill'
$grid.AllowUserToAddRows = $false
$grid.RowHeadersVisible = $false
$grid.StandardTab = $false
# Excel's way rather than DataGridView's: the first character typed into a
# cell opens its editor, which takes the focus and every character after it.
# One sent to the grid while the editor is open is lost, as in Excel.
$grid.EditMode = 'EditProgrammatically'
$grid.add_KeyPress({
    if (-not $grid.IsCurrentCellInEditMode) {
        [void]$grid.BeginEdit($false)
        $grid.EditingControl.Text = [string]$_.KeyChar
        $grid.EditingControl.SelectionStart = 1
    }
    $_.Handled = $true
})
[void]$grid.Columns.Add('region', 'Region')
[void]$grid.Columns.Add('jul', 'Jul')
$grid.Columns[0].Width = 200
[void]$grid.Rows.Add(3)
$form.Controls.Add($grid)

function Update-Title {
    $rows = foreach ($row in $grid.Rows) {
        ($row.Cells | ForEach-Object { [string]$_.Value }) -join '|'
    }
    $form.Text = "grid-probe $($rows -join '/') goto:$script:goto"
}
$grid.add_CellValueChanged({ Update-Title })

$form.add_KeyDown({
    if ($_.Control -and $_.KeyCode -eq 'G') {
        $_.Handled = $true
        $dialog = New-Object Windows.Forms.Form
        $dialog.Text = 'goto'
        $dialog.StartPosition = 'CenterParent'
        $dialog.ShowInTaskbar = $false
        $dialog.ClientSize = New-Object Drawing.Size(260, 90)
        $box = New-Object Windows.Forms.TextBox
        $box.SetBounds(12, 12, 230, 24)
        $ok = New-Object Windows.Forms.Button
        $ok.Text = 'OK'
        $ok.SetBounds(12, 50, 80, 28)
        $ok.add_Click({ $script:goto = $box.Text; $this.FindForm().Close() })
        $dialog.Controls.AddRange(@($box, $ok))
        $dialog.AcceptButton = $ok
        [void]$dialog.ShowDialog($form)
        $dialog.Dispose()
        Update-Title
    }
})

# The grid holds the thread's focus from the start, as a sheet does.
$form.add_Shown({ $grid.CurrentCell = $grid.Rows[0].Cells[0]; [void]$grid.Focus() })
[void]$form.ShowDialog()
