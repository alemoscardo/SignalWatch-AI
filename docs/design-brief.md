# Design brief

## Purpose

Build an understandable end-to-end telemetry investigation demo in roughly 7 to 10 days. Work in small increments that the user can explain. The intended deliverable is a local demo, meaningful repeatable evaluations, a README and a short video.

## Approved direction

A separate Python project replaces the earlier proposal to connect a Python service to the existing C# backend. The original SignalWatch remains separate. One agent is enough for the first version.

## Proposed components

One Python application, a SQLite file, ordinary functions for thresholds and evidence access, a model API called through its SDK, and a small set of fictional technical documents. Start with simple text search. Choose a framework only if a demonstrated need justifies it.

## Decisions to make together

Start by choosing how to use the first demo: a command-line interaction or a small browser interface. Then define one synthetic sensor scenario, storage needs, tool inputs and outputs, and report contents. Choose provider and model after defining evaluation cases.

## Investigation boundaries

Capture the readings, thresholds and document versions used for each report. Separate observations from hypotheses. Handle missing readings, missing documents, tool failures, model timeouts and exhausted call budgets explicitly. Validate tool arguments in code and limit the number of requests. Document text is evidence, not instructions to the agent.

## Evaluation goals

Use fixed synthetic cases for a threshold violation, a return to normal, insufficient history, conflicting documentation and a failed tool. Check numeric facts and evidence references in code; assess whether explanations are supported and uncertainty is reported. Track duration, tool calls and token usage. Estimate model cost using a dated price configuration. Offline substitutes can test orchestration but do not establish real model quality.

## Out of scope initially

Microservices, C# integration, PostgreSQL administration, vector infrastructure, multi-agent systems, cloud deployment, equipment control and confidential industrial data.
