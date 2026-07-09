# Contributing Guidelines

Thank you for considering contributing to this project! Please follow the guidelines below to ensure a smooth contribution process.

## Getting Started
1. **Fork the Repository**: Click the "Fork" button on the repository's page.
2. **Clone Your Fork** (with submodules — the KiCad libraries are submodules):
   ```sh
   git clone --recurse-submodules https://github.com/pe1mew/windmeters-modbus-interface.git
   ```
3. **Create a Branch**: Use a descriptive branch name for your changes:
   ```sh
   git checkout -b feature/your-feature-name
   ```

## Making Changes
- **Requirements first**: firmware behavior is specified in
  [`design/TDS.md`](design/TDS.md) with numbered requirements (FR-MB…,
  FR-S…, NFR-…). Behavior changes start with a TDS change; code and tests
  reference the requirement IDs they implement. Start from the design index
  [`design/README.md`](design/README.md).
- **Firmware changes**: all three variants must build —
  `pio run -e wind_speed`, `pio run -e wind_direction` and
  `pio run -e wind_combined` from `software/firmware/` (resource ceilings
  are enforced by the build). Host-testable logic (e.g. the circular-mean
  math) keeps its host tests green:
  `python software/drivers/common/circmean/test_circmean.py`.
- **Hardware-verified changes**: if you have the bench (WCH-LinkE, Saleae
  Logic 2, ADALM2000 — see [`software/hil/README.md`](software/hil/README.md)),
  run the acceptance suite per flashed variant:
  `pytest software/hil/acceptance --build speed|direction|combined`.
  Never release `*_test` build binaries (they contain bench-only hooks).
- Keep commits focused and meaningful; write clear commit messages.
- **Update documentation** — the design documents in `design/` are part of
  the deliverable, not an afterthought. Public headers carry Doxygen; keep
  it current and regenerate the site (`doxygen Doxyfile`) when APIs change.

## Submitting a Pull Request
1. **Push to Your Fork**:
   ```sh
   git push origin feature/your-feature-name
   ```
2. **Open a Pull Request**:
   - Navigate to the original repository.
   - Click on "New Pull Request".
   - Select your branch and provide a clear description of your changes.

## Code Review Process
- PRs will be reviewed by maintainers.
- Be open to feedback and make necessary changes.
- Ensure your branch is up to date with the latest main branch before merging.

## Reporting Issues
- Check if the issue has already been reported.
- Provide detailed information, including steps to reproduce the issue.
- Use clear and concise language.

## Community Standards
- Follow the [Code of Conduct](code_of_conduct.md).
- Be respectful and collaborative.

Happy Coding! 🚀
