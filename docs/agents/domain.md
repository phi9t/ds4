# Domain Docs

How engineering skills should consume this repo's domain documentation when
exploring the codebase.

## Before exploring, read these

- `AGENTS.md` at the repo root for the active inference, safety, build, and
  verification rules.
- `docs/adr/` if it exists, selecting ADRs that touch the area you're about to
  work in.

If these files do not exist, proceed silently. Create new durable domain or ADR
material only when a task resolves vocabulary or decisions that future agents
will need.

## Use the repo vocabulary

When output names a domain concept, use the terms already present in
`AGENTS.md`, source comments, and public flags: CUDA graph inference, SSD
streaming, routed experts, tensor parallelism, disk KV checkpoints, CPU
reference, and build identity.

If a concept needs a new durable name, define it beside the implementation or
in an ADR before relying on it across files.

## Flag ADR conflicts

If an implementation or plan contradicts an existing ADR, surface the conflict
explicitly instead of silently overriding it.
