# RunSense two-minute demo script

This script is for the current deterministic planning demo. It assumes Sara is a blind runner training for a comfortable 5K and has guide availability on Tuesday and Saturday. Run the app locally with the seeded athlete fixture. Keep the browser on Overview and have the Evaluation panel ready.

The demo has two honest modes. In local mode, the screen shows the plan, trace, and checks produced by the local deterministic path; the app banner should say Demo mode / No apps connected. In verified live mode, replace the corresponding trace rows with completed Google Sheets, Google Calendar, and Notion calls and show their returned identifiers. Do not say that local rows are external app actions.

## Run of show (1:50 target)

| Time | Operator action | Words / audio | Judge evidence |
| --- | --- | --- | --- |
| 0:00–0:15 | Open Overview; point to Sara and the next workout. | “Sara wants a comfortable 5K. RunSense turns her own training log and guide availability into a week she can hear and inspect.” | Clear persona, accessibility need, and scope. |
| 0:15–0:35 | Click **Plan my week**. | “Plan my week. I can run with a guide Tuesday and Saturday.” | One request starts a multi-step flow. |
| 0:35–0:55 | Let the week list and trace settle. | “This local demo uses synthetic history and simulated Calendar and Notion actions. The proposed live workflow reads Sheets, validates the plan, schedules sessions, and updates its journal.” | Ordered tool calls, clearly separated from actual connectivity. |
| 0:55–1:15 | Click **Guide cancelled**. | “Tuesday’s guide cancelled. RunSense moves the same session to the treadmill, keeps its distance, and explains why.” | Adaptation, guide constraint, and spoken rationale. |
| 1:15–1:35 | Click **Run reliability checks**. | “Now I replay the same request and force a transient Calendar failure.” | Passing rule checks; one retry; one event key rather than duplicates. If live, show the Calendar event and Notion page only after verifying they exist. |
| 1:35–1:50 | Point to the status banner and evaluation result. | “This build proves planning and reliability. Obstacle alerts and headset playback are the next layer; they are not claimed by this demo.” | Honest boundary and reproducible result. |

## Exact spoken version

“Sara wants a comfortable 5K. This local demo uses synthetic history and simulated guide confirmations on Tuesday and Saturday. RunSense creates a constrained week and gives every decision a reason. When Tuesday's guide cancels, the session moves to the treadmill. The trace shows each simulated step, and the reliability checks replay the request, inject a Calendar failure, and check duplicate prevention. Three-app connectivity and the optional Claude planner still need a live rehearsal. Real-time obstacle awareness and headset delivery are future work, so we do not claim them here.”

## Live integration callouts

Use these lines only after a rehearsal has verified the corresponding response:

- “Sheets returned Sara’s athlete-authored log.”
- “Calendar returned this session event, and the read-back matched.”
- “Notion updated the weekly plan and rationale, verified by read-back.”

Live guide invitation and RSVP handling is not implemented: all current live-mode workouts stay indoors. Do not present the simulated cancellation as a live RSVP event.

The live path must use the athlete's own authorized data. Do not connect the planner to Strava API data. Strava's June 2026 API Policy prohibits using Strava data or derivatives in AI operation, grounding, evaluation, analytics, and retrieval, with a narrow personal-use exception through Strava's first-party MCP. [Strava API Policy](https://www.strava.com/legal/api_policy)

## Pre-demo checklist

- Start from a clean local database or reset fixture so the plan and trace are deterministic.
- Confirm the page shows the actual connection state. If any app is unverified, leave it marked pending.
- Run baseline once, then run **Guide cancelled** and **Run reliability checks** before the judges arrive.
- If an OAuth prompt, network error, or missing credential appears, switch to local mode and say the local-mode sentence above.
- Keep a 20–30 second screen recording of the local flow as the backup. The backup should show the same honesty labels.

## Answers to likely judge questions

**What are the three apps?** “When verified, Google Sheets is the athlete-authored log, Google Calendar holds commitments, and Notion is the plan journal. The current local run labels those connections as unavailable.”

**Does this replace a guide?** “No. A guide-confirmation constraint is part of the planning decision; RunSense is an assistive layer.”

**Where are obstacle alerts?** “They are a separate future perception module. This submission demonstrates the planning and adaptation loop and does not present unmeasured computer-vision results.”

**Why not Strava for the three-app path?** “RunSense includes an optional read-only preview for one operator's own account through Strava's official MCP. It is memory-only, cannot write to Calendar or Notion, and does not make a multi-user Strava service. For the hackathon's three connected apps we use the independently athlete-authored Sheets log, Calendar, and Notion workflow.” [Strava API Policy](https://www.strava.com/legal/api_policy)

**Is the 10% cap medically proven?** “It is an inspectable heuristic for conservative planning, not an injury-prevention claim; published trial evidence did not show that the rule prevented injuries.” [PubMed PMID 17940147](https://pubmed.ncbi.nlm.nih.gov/17940147/)
