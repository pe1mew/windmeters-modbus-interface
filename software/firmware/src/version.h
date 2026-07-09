/**
 * @file version.h
 * @brief Single source of truth for the firmware version byte (FR-S32).
 *
 * Defines @ref FW_VERSION, the low byte of Modbus input register 30007
 * ("firmware version / build type") owned by the @ref regs.h "register image".
 * 30007 pairs this per-release version with a per-build build-type high byte
 * (0x01 wind speed, 0x02 wind direction) so a master can identify exactly which
 * binary a device is running.
 *
 * Release invariant: both build variants share one @ref FW_VERSION. A release
 * is the @b pair of binaries built from a single commit; they differ only in
 * the build-type high byte of 30007, never in this number. Bump it @b only at
 * release, in lockstep with a new row in `software/firmware/RELEASES.md` and a
 * `git tag fw-v<N>` on the released commit — the RELEASES.md / register-30007
 * chain that ties source, changelog and flashed device together.
 *
 * @note `software/hil/version_check.py` is the guard on that chain: it asserts
 *       this define, the matching RELEASES.md row, and the value reported by a
 *       flashed DUT over RS-485 all agree.
 * @see regs.h  Register image that publishes 30007.
 */
#ifndef VERSION_H
#define VERSION_H

/**
 * @brief Firmware release version — low byte of input register 30007 (FR-S32).
 *
 * Shared by both build variants; bump only at release together with a
 * RELEASES.md row and a `fw-v<N>` git tag. @see the file-level chain above.
 */
#define FW_VERSION 1

#endif
