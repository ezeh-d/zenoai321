# Permission candidates

- [OpenFGA](https://openfga.dev/docs/modeling/agents) models agents as principals,
  relationships, resource access and temporary task grants. It is appropriate
  when ZENO becomes multi-owner/multi-tenant; running its service now would add
  needless infrastructure.
- [Open Policy Agent](https://www.openpolicyagent.org/docs) evaluates structured
  context against policy-as-code. It fits environment/risk/confirmation rules,
  but a separate OPA process would duplicate the existing local Permission Engine.

Chosen: a lightweight compatible pipeline:

`identity/device trust → existing tool permission → consent/risk context → ALLOW/DENY/ASK`.

Financial execution is always DENY. Revoked/untrusted devices cannot create
side effects. Sensitive/admin actions ASK even on the owner laptop. External
FGA/OPA adapters can replace individual decision sources later without changing
callers.
