/*
 * Windmeter Modbus interface — CH32V003J4M6 (SOIC-8)
 *
 * Hardware is identical for the wind-speed and wind-direction variants;
 * the sensor type is selected at compile time. See design/scratchBook.md
 * for the full pin assignment and Modbus register map.
 *
 * Pin assignment (SOIC-8):
 *   PD6  USART1 half-duplex (HDSEL) -> MAX3485 DI + RO   (Modbus data)
 *   PC2  RS-485 DE/RE                                    (driver enable)
 *   PA2  ADC A0  -> wind-direction potentiometer wiper   (wind direction)
 *   PC1  TIM2_CH1_ETR -> anemometer reed-relay pulses     (wind speed)
 *   PC4  GPIO in  -> Modbus address solder jumper
 *   PD1  SWIO     -> WCH-LinkE programming (keep free)
 */

#include "debug.h"

#if !defined(SENSOR_WIND_SPEED) && !defined(SENSOR_WIND_DIRECTION)
#error "Define SENSOR_WIND_SPEED or SENSOR_WIND_DIRECTION (select a PlatformIO env)"
#endif

#if defined(SENSOR_WIND_SPEED) && defined(SENSOR_WIND_DIRECTION)
#error "SENSOR_WIND_SPEED and SENSOR_WIND_DIRECTION are mutually exclusive"
#endif

int main(void)
{
    SystemCoreClockUpdate();
    Delay_Init();

    /* TODO: peripheral init
     *   - GPIO: PC2 (DE/RE), PC4 (address jumper)
     *   - USART1 half-duplex on PD6 for Modbus RTU
     *   - SysTick for the measurement window
     * #ifdef SENSOR_WIND_SPEED    -> TIM2 ETR pulse counter on PC1
     * #ifdef SENSOR_WIND_DIRECTION -> ADC on PA2
     */

    while (1)
    {
        /* TODO: Modbus frame handling / measurement update */
    }
}
