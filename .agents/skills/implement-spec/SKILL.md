---
name: implement-spec
description: "Implement the result of /to-spec and /to-tickets in code."
disable-model-invocation: true
---

You have been provided a spec. This spec should have tickets associated with it, describing how to implement the spec.

The issue tracker should have been provided to you. If not, tell the user to run `/setup-matt-pocock-skills`.

The goal is the entire spec implemented on a single **integration branch**, with every ticket resolved the way the issue tracker closes work.

The tickets are not a list of steps. They are a **task graph** with blocking relationships between them. This means there is always a **frontier** of tickets which are ready to be grabbed.

Start every subagent with a fresh context window.

Communication to and from subagents should be sparse. Communicate primarily through **context pointers**: to the spec, tickets, research notes, and previous commits. Don't duplicate information already available via pointers.

**Implementer subagents** should be run in the background where possible for maximum concurrency.

## Steps

1. Read the spec and tickets to understand the task graph.

2. (optional) Use an **exploration subagent** to conduct any exploration required by the tickets - relevant codebase files or external documentation. Ensure the exploration subagent can save files - it should save its markdown notes in a directory outside the repo, accessible by all future subagents. This lets **implementer subagents** focus on implementation rather than exploration.

3. Create the integration branch. If the issue tracker closes work through PRs, or the user asks for one, open a draft PR after the first merge in step 5 (a branch with no commits ahead of main can't open one). Link it to close only tickets implemented by this PR; never close the parent issue or intentionally deferred tickets.

4. Use a fresh **implementer subagent** for each ticket, each in its own worktree on its own branch. Each implementer subagent:
   - confirms its worktree is based on the integration branch before starting, and resets onto it if not;
   - calls the Skill tool with `tdd` to build the ticket;
   - merges the integration branch tip into its own branch before reporting done
   - **Worktree failure:** If isolated worktree creation fails, stop ticket dispatch and fix the cause. Keep ticket agents out of the shared integration checkout. Resume in isolated worktrees; if isolation cannot be restored, pause and report the blocker rather than silently changing the execution model.

5. Once an **implementer subagent** completes, merge its work to the integration branch with a **merger subagent**.

6. If this changes the **frontier** of available tickets, kick off more **implementer subagents** to work on the new tickets. This allows for maximum concurrency.

7. Once all non-deferred tickets are complete, call the Skill tool with `code-review` on the integration branch. Fix all issues raised by the code review in a single fresh **implementer subagent**. Report any intentionally deferred tickets.

8. Before treating CI results as current or merging, verify the PR head SHA matches the integration branch HEAD (`gh pr view <number> --json headRefOid` and `git rev-parse HEAD`). If they differ, reconcile the branches and wait for checks on the resulting PR SHA; never transfer a green result from one SHA to another.
   - If all tickets are complete, mark the draft PR ready for review. If the user explicitly defers tickets, leave them open and record in the PR body whether each deferral blocks merge. A user-authorized merge with non-blocking deferrals may proceed without keeping the PR in draft solely for those deferrals; report that the full spec remains incomplete and leave the parent issue open.
   - Resolve only completed tickets the way the issue tracker closes work, and report the integration branch and any outstanding deferrals.

9. Clean up all **implementer subagent** worktrees.
