"""The NeMo Guardrails configuration, written as plain text here so it ships with the package and
cannot go missing from a Docker image.

Every rail is a small Colang flow that calls one custom action (see engine.py). The action holds
the logic; the flow only says "if the action says block, refuse and stop". No language model is
configured, because the fast rules need none, and the judge call uses the student's own model
through our code rather than through NeMo."""

YAML = """
colang_version: "1.0"
rails:
  input:
    flows:
      - mindnest input rail
  output:
    flows:
      - mindnest output rail
  tool_output:
    flows:
      - mindnest tool call rail
  tool_input:
    flows:
      - mindnest tool result rail
"""

COLANG = """
define bot mindnest refuse
  "refused"

define flow mindnest input rail
  $mn_in = execute mn_input
  if $mn_in["action"] == "block"
    bot mindnest refuse
    stop

define flow mindnest output rail
  $mn_out = execute mn_output
  if $mn_out["action"] == "block"
    bot mindnest refuse
    stop

define flow mindnest tool call rail
  $mn_tc = execute mn_tool_call(calls=$tool_calls)
  if $mn_tc["action"] == "block"
    bot mindnest refuse
    stop

define flow mindnest tool result rail
  $mn_tr = execute mn_tool_result(text=$tool_message, name=$tool_name)
  if $mn_tr["action"] == "block"
    bot mindnest refuse
    stop
"""
