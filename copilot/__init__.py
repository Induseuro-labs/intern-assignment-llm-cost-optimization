"""Core building blocks shared by the Question 1 and Question 2 agents.

Modules
-------
model      Domain types: outcomes, decisions, policies, per-ticket context.
search     Help-center index with a deterministic lexical ranking.
prompting  The single compact prompt sent to the model.
extract    Tolerant extraction of the model's JSON answer.
stages     The four pipeline steps: context, lookup, decide, verify.
costs      Per-call token and points tables for cost reporting.
"""
