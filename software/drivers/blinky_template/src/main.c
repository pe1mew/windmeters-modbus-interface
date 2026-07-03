#include "ch32fun.h"

// Bare CH32V003J4M6 (SOP-8): there is no on-board LED, so wire an LED (+ series
// resistor) between the chosen pin and GND. PD6 is a plain GPIO on this package
// and matches the sibling nanoCH32V003 blinky.
//
// Usable GPIO on the J4M6 SOP-8 package: PA1, PA2, PC1, PC2, PC4, PD4, PD6.
// PD1 is the SWIO programming line (WCH-LinkE) — leave it for the debugger.
#define PIN_LED PD6

int main()
{
	SystemInit();

	funGpioInitAll();                                          // Enable all GPIO ports
	funPinMode( PIN_LED, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP ); // LED pin as push-pull output

	while( 1 )
	{
		funDigitalWrite( PIN_LED, FUN_HIGH );
		Delay_Ms( 100 );
		funDigitalWrite( PIN_LED, FUN_LOW );
		Delay_Ms( 900 );
	}
}
