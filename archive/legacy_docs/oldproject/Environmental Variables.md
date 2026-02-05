# Environmental Variables

In PowerShell

**Setting per session**

```$env:TODOIST_TOKEN = "<your real token>"```

**Persist for user**

Won't reset on reboot or new terminal sessions. (variable, password, set to user)

```[Environment]::SetEnvironmentVariable("TODOIST_TOKEN","p_XXXX...","User")```

Verify the variable.

```[Environment]::GetEnvironmentVariable("TODOIST_TOKEN","User")```

Remove token.

```[Environment]::SetEnvironmentVariable("TODOIST_TOKEN",$null,"User")```

---
Check all environmental variables:

```Get-ChildItem Env:```

