# hermes-vm: Claude Code Guidelines

## Core Philosophy: Code Over Agent Intelligence

**No gaps between what code can do and what the agent tries to do.**

When building a new skill or feature: mechanical work belongs in code. Agents should only handle irreducible intelligence.

### The Pattern

For every skill or feature that might require agent reasoning:

1. **Identify mechanical vs. intelligent work**
   - Mechanical: parsing, formatting, routing, API calls, fallback logic, state management, validation
   - Intelligent: reasoning about intent, extracting meaning from ambiguity, making decisions, prioritizing options

2. **Build code for all mechanical work**
   - Create a service/utility class or set of functions
   - Handle all the plumbing (parsing input, executing logic, formatting output, handling errors)
   - Test it deterministically without involving the agent

3. **Keep the skill interface minimal and structured**
   - Don't ask agents to do text parsing or natural language processing to extract parameters
   - Skill takes structured input (specific fields with clear types)
   - Skill returns structured output (success/failure, ID, relevant metadata)

4. **Agent uses the skill for intelligent decisions only**
   - Agent extracts semantic meaning from user input
   - Agent calls the skill with structured data
   - Agent receives structured response and reasons about next steps

### Examples

**Reminders Skill** ✅
- Backend (RemindersService): Parse intent → extract action/deadline → check channel routing → format Discord message → handle fallbacks → post and log
- Agent: Read user message → extract action/deadline → call `create_reminder(action, deadline)` → respond intelligently

**Cron Jobs Skill** ✅
- Backend (CronService): Validate cron syntax → create systemd timer → persist task → manage lifecycle
- Agent: Decide what to schedule → extract task description and timing → call `schedule_task(description, cron_expr)` → log the scheduled task

**Routing Messages** ✅ (if needed)
- Backend: Channel registry → check guild channels → maintain fallback map
- Agent: Decide which context is needed → call `route_message(content, context)` → receives channel ID

### Why This Matters

- **Efficiency:** Agents don't waste tokens on boilerplate; they focus on reasoning
- **Reliability:** Deterministic code beats language model reasoning for structured tasks
- **Maintainability:** Code is testable and easier to evolve than prompt engineering
- **Scaling:** Code scales predictably; agent reasoning becomes expensive at scale

### Creating an Issue for Work

When design work reveals mechanical work the agent currently handles:
- Create an issue to move that work to code
- Title: `feat: [service name] — backend for [what it does]`
- Description: clarify the mechanical vs. intelligent split
- Link to the agent-facing skill that will use this service
