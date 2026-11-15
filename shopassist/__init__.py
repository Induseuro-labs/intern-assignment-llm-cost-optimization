"""ShopAssist core: the building blocks shared by both agents.

Modules
-------
schema      Typed domain objects (actions, resolutions, node payloads).
knowledge   Help-center index with deterministic lexical retrieval.
prompts     The single compact prompt sent to the model.
parsing     Tolerant extraction of the model's JSON answer.
nodes       The four pipeline stages: triage, retrieve, compose, audit.
reporting   Per-call token / points breakdowns.
"""
