# Challenging Decisions RED Baseline

## Purpose

Freeze the observed pre-skill behavior this package must correct.

## Set A — obvious bad decisions

Scenarios:
- over-scoped prelaunch enterprise bundle
- microservices for a tiny app
- building a therapist AI product for 6 weeks before talking to users

Observed pattern:
- the assistant usually challenged the decision
- the pushback mostly came through one lens
- the reply ended without a forcing question

## Set B — subtler weak decisions

Scenarios:
- adding SSO before launch because one pilot mentioned it
- moving to event-driven architecture after one failed background job
- polishing onboarding for a month before user conversations

Observed pattern:
- the assistant still pushed back
- the pushback was again mostly single-angle
- the reply still lacked a forcing question

## Set C — agree-first failure (critical)

Agreement-first phrases seen in baseline:
- `Yes, that makes sense.`
- `Yes, I'd keep the monolith for now.`

Scenarios:
1. narrowing launch scope to one core workflow and delaying AI features until after first five paying customers
2. keeping the monolith, adding better metrics, and only reconsidering microservices if real scaling or team-boundary problems appear

Observed pattern:
- the assistant validated first instead of pressure-testing first
- the answer skipped the strongest counterarguments
- the answer did not end with a forcing question

## Design implications

The package should:
- challenge before agreement, even when the decision is probably good
- use multiple named practical lenses instead of personas
- surface the strongest counterarguments
- end with a forcing question
- tell the model what to do after the user responds
