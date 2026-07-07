---
name: cron
description: Use this skill only for scheduled or recurring tasks. Manage jobs with coapis cron list/create/get/state/pause/resume/delete/run, and always pass --agent-id explicitly.
metadata:
  builtin_skill_version: "1.4"
  coapis:
    emoji: "⏰"
---

# Cron (Scheduled Task Management)

## When to Use

Use this skill only when you need to **automatically execute something at a future time** or **repeat execution on a schedule**.

### Should Use
- User asks to do something "daily / weekly / hourly"
- User asks for automatic reminders or execution "tomorrow at 9 AM / next Monday / at a specific time"
- Long-term periodic notifications, checks, or reports are needed

### Should Not Use
- The task only needs to be **executed once right now**
- It is just a normal reply within the current session
- The user has not specified an execution time or schedule
- The target channel / user / session is still unclear

## Decision Rules

1. **Only use cron for future scheduled or periodic execution**
2. **If it only needs to be done once immediately, do not create a cron job**
3. **Before creating, confirm execution time/schedule, target channel, target-user, and target-session**
4. **All cron commands must explicitly include `--agent-id`**
5. **Do not rely on the default agent, or the task may end up in the default workspace**

---

## Hard Rules

### Must Explicitly Specify `--agent-id`

All `coapis cron` commands **must** include:

```bash
--agent-id <your_agent_id>
```

Your agent_id is found in the Agent Identity section of the system prompt (Your agent id is ...).
Do not omit it, or the task may be incorrectly created in the default agent's workspace.

---

## Common Commands

```bash
# List tasks
coapis cron list --agent-id <agent_id>

# View task details
coapis cron get <job_id> --agent-id <agent_id>

# View task status
coapis cron state <job_id> --agent-id <agent_id>

# Create a task
coapis cron create --agent-id <agent_id> ...

# Delete a task
coapis cron delete <job_id> --agent-id <agent_id>

# Pause / Resume a task
coapis cron pause <job_id> --agent-id <agent_id>
coapis cron resume <job_id> --agent-id <agent_id>

# Run an existing task once immediately
coapis cron run <job_id> --agent-id <agent_id>
```

---

## Creating Tasks

Two types are supported:
- **text**: Send a fixed message on a schedule
- **agent**: Ask an agent a question on a schedule and send the reply to the target channel

### Minimum Information Required Before Creating
- `--type`
- `--name`
- `--cron`
- `--channel`
- `--target-user`
- `--target-session`
- `--text`
- `--agent-id`

If any of this information is missing, confirm with the user before creating the task.

### Creation Examples

```bash
coapis cron create \
  --agent-id <agent_id> \
  --type text \
  --name "Daily Greeting" \
  --cron "0 9 * * *" \
  --channel imessage \
  --target-user "CHANGEME" \
  --target-session "CHANGEME" \
  --text "Good morning!"
```

```bash
coapis cron create \
  --agent-id <agent_id> \
  --type agent \
  --name "Check Todos" \
  --cron "0 */2 * * *" \
  --channel dingtalk \
  --target-user "CHANGEME" \
  --target-session "CHANGEME" \
  --text "What are my pending tasks?"
```

### Create from JSON

```bash
coapis cron create --agent-id <agent_id> -f job_spec.json
```

---

## Minimal Workflow

```
1. Determine whether this truly requires "future scheduling" or "periodic execution"
2. Confirm execution time/schedule
3. Confirm channel, target-user, target-session
4. Explicitly include --agent-id
5. Create the task with coapis cron create
6. Manage tasks afterwards with list / state / pause / resume / delete
```

---

## Cron Expression Examples

```
0 9 * * *      Every day at 9:00
0 */2 * * *    Every 2 hours
30 8 * * 1-5   Weekdays at 8:30
0 0 * * 0      Every Sunday at midnight
*/15 * * * *   Every 15 minutes
```

---

## Common Mistakes

### Mistake 1: Creating a cron job for a one-time immediate execution

If the task only needs to be done once right now, do not create a cron job.

### Mistake 2: Not passing --agent-id

This causes the task to be assigned to the wrong agent / workspace. All cron commands must explicitly include `--agent-id`.

### Mistake 3: Creating a task without complete information

If the user has not specified the time, schedule, target channel, or target session, ask for clarification first.

### Mistake 4: Modifying existing tasks without checking first

Before pausing, resuming, or deleting, first run:

```bash
coapis cron list --agent-id <agent_id>
```

to find the correct `job_id`.

---

## Usage Tips

- When parameters are missing, ask the user before creating
- Before modifying/pausing/deleting, run `coapis cron list --agent-id <agent_id>` first
- To troubleshoot issues, use `coapis cron state <job_id> --agent-id <agent_id>`
- When showing commands to the user, provide complete, copy-pasteable versions

---

## Help Information

```bash
coapis cron -h
coapis cron list -h
coapis cron create -h
coapis cron get -h
coapis cron state -h
coapis cron pause -h
coapis cron resume -h
coapis cron delete -h
coapis cron run -h
```
