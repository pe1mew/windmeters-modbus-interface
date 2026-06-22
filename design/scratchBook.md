# General

# Sensors

## Wind-direction-meter

The wind direction meter has a potentiometer where the full 360 degrees range is covered by the resistance of the potentiometer.
 
## Windspeed-meter

The wind speed meter is a cup-anemometer which gives pulses through a reed-relais.

# Software

 - The interface is addressable over modbus.
 - The interface can read both wind-direction-meter and cup-anemo-meter. 

# Hardware

## Microporcessor options

In order of preference:
 
 1. CH32V003J4M6, SOIC-8
 2. CH32V003A4M6, SOIC-16
 3. CH32V003F4P6, SOIC-20
 
## Modbus transceiver

 - MAX3485, SOIC-8

## CH32V003J4M6 pin assignment (SOIC-8)

The SOP-8 bonds out only 6 GPIO. Note: none of the USART1 remap combos place both TX and RX on this package, so Modbus uses the USART in **single-wire half-duplex** mode (HDSEL) on PD6, with a separate GPIO for the RS-485 driver-enable.

| Pin | Name | Assignment | Function used |
|-----|------|------------|---------------|
| 1 | PD6 | RS-485 data | USART1 half-duplex (HDSEL); tie to MAX3485 DI + RO |
| 2 | VSS | Ground | — |
| 3 | PA2 | Wind-direction (analog) | ADC A0 (also OPP0 op-amp input) |
| 4 | VDD | Power | — |
| 5 | PC1 | Anemometer (pulse) | TIM2_CH1_ETR external-clock counter (remap) |
| 6 | PC2 | RS-485 DE//RE | GPIO direction control for MAX3485 |
| 7 | PC4 | Status LED / spare | GPIO out (also ADC A2 / TIM1_CH4 if needed) |
| 8 | PD1 | Programming | SWIO (WCH-LinkE) — keep free for flashing |

Notes:
 - **Wind-direction-meter** (potentiometer) -> PA2 / ADC A0. PA2 is also the op-amp positive input (OPP0) if signal conditioning is wanted.
 - **Anemometer** (reed-relay pulses) -> PC1 / TIM2 external clock, hardware pulse counting (no CPU per pulse). PC1 has no ADC, so no analog capability is wasted. Needs AFIO remap (trailing `_` function).
 - **Status LED** on PC4 is fine at a few mA, but PC4 is an analog-input pin so it lacks the "high current" drive of the digital-only pins (abs. max on any I/O is 20 mA per the datasheet) — size the series resistor for low LED current and drive the LED active-low (sink) if extra margin is wanted.
 - PD1 is the single-wire debug/flash pin (SWIO); do not use it for I/O.
 
## Design directives

 - a 3-pin header on the pcb shall make it possible to program the microprocessor
 - 2 RJ45 connectors shall enable "daisy chain" type interconnect of modbus.
 - The interface uses 24V passive PoE where power is carried on the spare pairs of 10/100 Ethernet:
   - Pins 4 & 5 -> +24V (positive)
   - Pins 7 & 8 -> return (negative/ground)
 - on pcb is a 120 ohm terminator resistor for modbus termination that is disconnected by default by a PCB-jumper.
 - The modbus interface is protected by diodes for overvoltage
 - a 2 screwterminal interface connects to the anemometer
 - a 3 screwterminal interface connects to the wind-direction-meter
 