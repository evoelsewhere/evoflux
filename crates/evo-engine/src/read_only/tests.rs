use super::*;
use serde_json::json;

fn bash(command: &str) -> Result<(), String> {
    check_command(command, Shell::Bash)
}

fn pwsh(command: &str) -> Result<(), String> {
    check_command(command, Shell::PowerShell)
}

#[test]
fn bash_reading_commands_pass() {
    for command in [
        r#"rg -n "fn main" crates/ --type rust"#,
        "git log --oneline -20 -- crates/evo-engine",
        "git -C ../other diff HEAD~1 --stat",
        "git --no-pager show HEAD:Cargo.toml",
        "ls -la && cat Cargo.toml | head -50",
        r"find . -name '*.rs' -not -path './target/*' | wc -l",
        r#"grep -rn "TODO" src 2>/dev/null | sort | uniq -c | sort -rn | head"#,
        r#"for f in $(git ls-files '*.md'); do wc -l "$f"; done"#,
        "cd crates && rg --files | grep agent",
        "git branch -a --contains HEAD",
        "git branch",
        "git tag -l 'v*'",
        "git status --short 2>&1",
        r#"echo "a > b; rm -rf /""#,
        "rg 'x|y' src",
        "git config --get user.name",
        "X=1 rg foo",
        "git stash list",
        "echo ${HOME} && pwd",
        "if [ -f Cargo.toml ]; then head -5 Cargo.toml; fi",
        "command -v rg",
        "rg foo # a comment > here",
        "cat a.txt >/dev/null",
        "rg foo &>/dev/null",
        "",
    ] {
        assert_eq!(bash(command), Ok(()), "{command}");
    }
}

#[test]
fn bash_writing_commands_are_refused() {
    for command in [
        "echo hi > out.txt",
        "echo hi>out.txt",
        "cat a >> b",
        "rg foo &> log.txt",
        "rm -rf target",
        "sed -i 's/a/b/' f",
        "find . -name '*.tmp' -delete",
        r"find . -exec rm {} \;",
        "rg --pre ./script foo",
        "rg --pre=./script foo",
        "fd -x rm",
        "sort -o out in",
        "uniq in out",
        "git commit -m x",
        "git checkout -- .",
        "git stash",
        "git branch newbranch",
        "git branch -D old",
        "git tag v1",
        "git remote add origin url",
        "git config user.name x",
        "git -c core.pager=rm log",
        "git log --output=x",
        "git grep -O foo",
        "git reflog expire --all",
        "ls; touch x",
        "echo $(touch x)",
        r#"echo "$(touch x)""#,
        "echo `touch x`",
        "echo ${x:-$(touch y)}",
        "cat <<EOF > f",
        "xargs rm < list",
        "tee out < in",
        r#"python -c 'open("x","w")'"#,
        "env rm x",
        "npm install",
        "cargo build",
        "rg foo | tee out",
        "(cd x && rm y)",
        "true && { rm y; }",
        "eval rm y",
        "'unterminated",
    ] {
        assert!(bash(command).is_err(), "{command} was allowed");
    }
}

#[test]
fn powershell_reading_commands_pass() {
    for command in [
        "Get-ChildItem -Recurse -Filter *.rs | Select-Object -First 20",
        r"Get-Content .\Cargo.toml -TotalCount 40",
        r"Select-String -Path src\*.rs -Pattern 'fn main'",
        "gci -r | Where-Object { $_.Length -gt 1MB } | Sort-Object Length -Descending | Select-Object FullName, Length",
        "git log --oneline -5 2>$null",
        "git log --format=%H -3",
        "rg -n foo crates | Measure-Object -Line",
        "$files = Get-ChildItem *.md; $files.Count",
        "Get-ChildItem | ForEach-Object { $_.Name }",
        "Get-ChildItem | % { $_.FullName }",
        "(Get-Content a.txt).Length",
        r"if (Test-Path .\x) { Get-Item .\x }",
        "Get-ChildItem | Select-Object Name, @{n='Size'; e={$_.Length}}",
        "foreach ($f in Get-ChildItem) { $f.Name }",
        "-not (Test-Path x)",
        "Get-Content a.txt *>$null",
        "${env:PATH} -split ';'",
    ] {
        assert_eq!(pwsh(command), Ok(()), "{command}");
    }
}

#[test]
fn powershell_writing_commands_are_refused() {
    for command in [
        "Remove-Item x",
        "Set-Content a.txt 'x'",
        "'x' | Out-File a.txt",
        "Get-Content a > b.txt",
        "Get-Content a 2> err.txt",
        "[IO.File]::WriteAllText('a','b')",
        "[IO.File]::Delete",
        "(Get-Item a).Delete()",
        "$f.Delete()",
        "$f.IsReadOnly = $true",
        "(Get-Item a).IsReadOnly = $true",
        "& rm x",
        "& 'C:\\tools\\x.exe'",
        r". .\script.ps1",
        "iex 'rm x'",
        "Invoke-Expression x",
        "Start-Process notepad",
        r#""$(Remove-Item x)""#,
        "Get-ChildItem | ForEach-Object Delete",
        "Get-ChildItem | % { Remove-Item $_ }",
        "Copy-Item a b",
        "$x = Remove-Item a",
        "$x=New-Item a",
        "New-Item -ItemType File a",
        "git push",
    ] {
        assert!(pwsh(command).is_err(), "{command} was allowed");
    }
}

#[test]
fn guard_passes_reading_tools_and_refuses_the_rest() {
    assert!(guard("read", &json!({"path": "a"})).is_ok());
    assert!(guard("send_message", &json!({})).is_ok());
    assert!(guard("bash", &json!({"command": "rg foo"})).is_ok());
    assert!(guard("powershell", &json!({"command": "Get-ChildItem"})).is_ok());
    for (tool, args) in [
        ("write", json!({"path": "a", "content": "b"})),
        ("edit", json!({"path": "a"})),
        ("mcp__db__drop_table", json!({})),
        ("bash", json!({"command": "rm -rf ."})),
        ("powershell", json!({"command": "Remove-Item ."})),
    ] {
        let refusal = guard(tool, &args).unwrap_err();
        assert!(
            refusal.starts_with("Refused: this agent is read-only"),
            "{refusal}"
        );
    }
}
