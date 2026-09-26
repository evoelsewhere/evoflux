# A WinForms window whose button opens a modal dialog, which opens a second
# one: the live tests use it to check refs and dialog following. Each
# dialog is centred on its owner, so it opens wherever the owner is parked.
#
# Keys open windows that are not dialogs, each at a fixed spot on the
# primary monitor, the way apps open floating panes and palettes: F7 a
# captionless pane the form owns, F9 a tool window it does not own.
Add-Type -AssemblyName System.Windows.Forms
Add-Type -WarningAction SilentlyContinue -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @'
using System.Windows.Forms;
public class ProbePane : Form {
    // WS_POPUP | WS_BORDER: a captionless popup, like a floating task pane.
    protected override CreateParams CreateParams {
        get { var cp = base.CreateParams; cp.Style = unchecked((int)0x80800000); return cp; }
    }
    protected override bool ShowWithoutActivation { get { return true; } }
}
'@

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
$form.KeyPreview = $true
$open = New-Object Windows.Forms.Button
$open.Text = 'Open dialog 1'
$open.SetBounds(20, 20, 130, 30)
$open.add_Click({ Show-ProbeDialog $form 1 })
$form.Controls.Add($open)
$form.add_KeyDown({
    if ($_.KeyCode -eq 'F7') {
        $pane = New-Object ProbePane
        $pane.Text = 'probe pane'
        $pane.StartPosition = 'Manual'
        $pane.ShowInTaskbar = $false
        $pane.SetBounds(160, 160, 220, 300)
        $pane.Show($form)
    } elseif ($_.KeyCode -eq 'F9') {
        $palette = New-Object Windows.Forms.Form
        $palette.Text = 'probe palette'
        $palette.FormBorderStyle = 'FixedToolWindow'
        $palette.StartPosition = 'Manual'
        $palette.ShowInTaskbar = $false
        $palette.SetBounds(200, 200, 180, 240)
        $palette.Show()
    }
})
[void]$form.ShowDialog()
