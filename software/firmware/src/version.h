#ifndef VERSION_H
#define VERSION_H

// Single source of truth for the firmware version byte (TDS FR-S32,
// register 30007 low byte). Rules:
//  - Bump ONLY at release, together with a new row in RELEASES.md and a
//    git tag fw-v<N> on the released commit.
//  - Both build variants share this number; a release is the PAIR of
//    binaries built from one commit. They differ only in the build-type
//    high byte of 30007 (0x01 wind speed, 0x02 wind direction).
//  - software/hil/version_check.py verifies this define, the RELEASES.md
//    row, and the value reported by a flashed DUT agree.
#define FW_VERSION 1

#endif
