"""The agent layer: a LangGraph orchestrator and specialist agents that act for one student.

Everything here runs as the signed-in student, under the same row-level security as the rest of
the app. Provider keys are passed in for one run and never stored in graph state, checkpoints or
traces.
"""

GRAPH_VERSION = "agents-2"
