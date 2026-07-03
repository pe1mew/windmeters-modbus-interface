# Firmware releases — version-byte registry (TDS FR-S32)

Register 30007 reports `(build_type << 8) | FW_VERSION`: build type 0x01 =
wind speed, 0x02 = wind direction; the low byte is the release counter
defined in `src/version.h`. This file is the **release record** FR-S32's
acceptance criterion refers to: every released version byte maps to exactly
one commit here.

## Release process

1. Finish and verify the work; both variants green in the acceptance suite.
2. Bump `FW_VERSION` in `src/version.h`.
3. Add a row below; commit; tag the commit `fw-v<N>`.
4. Build both variants from the clean tagged checkout (NFR-BLD01) and
   record the binary SHA-256s in the row.
5. `software/hil/version_check.py` against a flashed DUT must pass.

## Releases

| Version | Date | Commit / tag | Binaries (SHA-256 speed / direction) | Notes |
|---|---|---|---|---|
| 1 | — | *unreleased* | — | Integration in progress (stage A skeleton onward). Version 1 will be tagged at the first release. |
