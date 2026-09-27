# -*- coding: utf-8 -*-
"""Agent capability evaluation (benchmark + telemetry + evolution loop).

Modules:
* ``dataset``  – YAML task definitions (5 categories × 8 tasks)
* ``runner``   – in-process evaluator driving the real agent entry point
* ``checker``  – deterministic checkers + LLM-judge orchestration
* ``judge``    – LLM-as-a-Judge (structured rubric scoring)
* ``telemetry``– POST_EXECUTE hooks capturing trajectories
* ``report``   – weekly mining / weak-point report
* ``mocks``    – mock tools injected into the eval agent's toolkit
"""
