# A WinForms window whose button opens a modal dialog, which opens a second
# one: the live tests use it to check refs and dialog following. Each
# dialog is centred on its owner, so it opens wherever the owner is parked.
Add-Type -AssemblyName System.Windows.Forms

function Show-ProbeDialog($owner, [int]$level) {
    $dialog = New-Object Windows.Forms.Form
    $dialog.Text = "probe dialog $level"
    $dialog.StartPosition = 'CenterParent'
    $dialog.ShowInTaskbar = $false
    $dialog.ClientSize = New-Object Drawing.Size(320, 140)
    $close = New-Object Windows.Forms.Button
    $close.Text = "Close dialog $level"
    $close.SetBounds(20, 20, 130, 30)
    $close.add_Click({ $this.FindForm().Close() })
    $dialog.Controls.Add($close)
    if ($level -lt 2) {
        $nested = New-Object Windows.Forms.Button
        $nested.Text = "Open dialog 2"
        $nested.SetBounds(170, 20, 130, 30)
        $nested.add_Click({ Show-ProbeDialog $this.FindForm() 2 })
        $dialog.Controls.Add($nested)
    }
    [void]$dialog.ShowDialog($owner)
    $dialog.Dispose()
}

$form = New-Object Windows.Forms.Form
$form.Text = 'dialog-probe'
$form.StartPosition = 'Manual'
$form.SetBounds(120, 120, 420, 220)
$open = New-Object Windows.Forms.Button
$open.Text = 'Open dialog 1'
$open.SetBounds(20, 20, 130, 30)
$open.add_Click({ Show-ProbeDialog $form 1 })
$form.Controls.Add($open)
[void]$form.ShowDialog()
