# Server Types

Use live `hcloud server-type list` output as the source of truth.

Family primer:

- `cax*`: ARM shared CPU, often cheapest, region availability varies.
- `cx*`: x86 shared CPU, good default for most small agent boxes.
- `cpx*`: x86 shared CPU, broader regional availability.
- `ccx*`: dedicated CPU, more expensive.

Do not hardcode prices or availability in the skill. They change.