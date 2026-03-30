param(
    [string]$TaskName = "Habit Tracker Daily Reminders",
    [string]$DailyTime = "20:00"
)

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runnerScript = Join-Path $projectRoot "send_reminders.ps1"

if (-not (Test-Path $runnerScript)) {
    throw "Reminder runner script was not found at $runnerScript"
}

$triggerTime = [datetime]::ParseExact($DailyTime, 'HH:mm', $null)
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File `"$runnerScript`""
$trigger = New-ScheduledTaskTrigger -Daily -At $triggerTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Sends Habit Tracker personalized daily reminder emails." `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
$taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName

[PSCustomObject]@{
    TaskName = $task.TaskName
    State = $task.State
    NextRunTime = $taskInfo.NextRunTime
    LastRunTime = $taskInfo.LastRunTime
}
