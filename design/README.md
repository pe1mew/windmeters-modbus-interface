# Design documentation

This directory holds the design record for the Windmeters Modbus Interface
firmware — the chain from first idea to a validated, requirement-traced
implementation. The documents build on each other in this order:

```
scratchBook  →  TDS  →  softwareArchitecture  →  driverDevelopment  →  integrationPlan
(brainstorm)   (what)   (how + diagrams)         (drivers + results)   (product fw + results)
```

## The documents

| Document | Purpose | Status |
|---|---|---|
| [`TDS.md`](TDS.md) | **Technical Design Specification** — the requirements contract (FR-MB…, FR-S…, NFR-…) with measurable pass/fail criteria. The single source of truth for behaviour. | **v0.8** — 69 active requirements; hardened by a multi-agent audit + verification passes |
| [`softwareArchitecture.md`](softwareArchitecture.md) | **How** the requirements are met: the zero-ISR cooperative super-loop, the module split, and the sizing rationale. §7 embeds the UML diagrams. | Agreed baseline; diagrams added |
| [`driverDevelopment.md`](driverDevelopment.md) | Plan + results for the three standalone drivers (pulse counting, ADC/circular-mean, Modbus RTU), each HIL-verified before integration. | Phases 0–3 complete, HIL-verified on silicon |
| [`integrationPlan.md`](integrationPlan.md) | The product-firmware plan: six integration stages (A–F) and the §9 hardware-gated test set (MAX3485 rig + real PCB). Carries per-stage results. | Stages A–F done; §9.1 complete on all three variants; §9.2 (real PCB) pending |
| [`scratchBook.md`](scratchBook.md) | The brainstorm and working notes that seeded the TDS — components, power chain, ADC strategy, calibration derivation. Superseded by the docs above where they overlap. | Working notes (historical) |
| [`diagrams/`](diagrams/) | UML diagrams as PlantUML sources + rendered PNGs (see below). | — |

## Diagrams

Three UML views of the shipped design live in [`diagrams/`](diagrams/) and
are embedded in [`softwareArchitecture.md`](softwareArchitecture.md) §7:

- **[`component.puml`](diagrams/component.puml)** — module structure & data
  flow (sensor → driver → measurement → `regs` hub → Modbus).
- **[`superloop_sequence.puml`](diagrams/superloop_sequence.puml)** — one
  zero-ISR super-loop iteration.
- **[`modbus_state.puml`](diagrams/modbus_state.puml)** — the Modbus RTU
  line-discipline state machine.

Regenerate the PNGs with the local PlantUML:

```sh
"C:/apps/plantuml/plantuml.exe" -tpng -o . design/diagrams/*.puml
```

## Build variants

The firmware compiles into three variants from one source tree (FR-S01),
selected by a `-D SENSOR_WIND_*` define and addressed by a PC4 solder jumper:

| Variant | Build type | Address (open / bridged) |
|---|---|---|
| `wind_speed` | 0x01 | 30 / 35 |
| `wind_direction` | 0x02 | 31 / 36 |
| `wind_combined` | 0x03 | 32 / 37 |

## How this connects to the rest of the repo

- The **API reference** ([`Doxyfile`](../Doxyfile) at the repo root) folds
  these design documents in as pages alongside the header/source
  documentation — run `doxygen Doxyfile` for a single browsable site with
  the project [`README.md`](../README.md) as its landing page.
- The requirements here are verified by the scripted bench in
  [`software/hil/`](../software/hil/); every executed test with its
  setup/expected/verdict is consolidated in
  [`software/hil/testReport.md`](../software/hil/testReport.md).
- Contribution workflow (requirements-first, build all variants, run the
  host + acceptance tests) is in [`contributing.md`](../contributing.md).
