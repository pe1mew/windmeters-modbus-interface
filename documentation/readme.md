# WCH MCU documentation on the web

 - https://github.com/limingjie/WCH-MCU-Pinouts/tree/main


# Source downloaded PDF

 - https://www.olimex.com/Products/RISC-V/WCH/WCH-LinkE/resources/WCH-LinkUserManual.PDF
 
# Wiring WCH-Link 

## to nanoCH32V003


```
        nanoCH32V003             WCH-LinkE
      +--------------+    +----------------+
      |              |    |                |
      |          GND o----o GND            |
      |          DI0 o----o SWDIO/TMS      |
      |          VCC o----o 3V3            |
      |              |    |                |
      +--------------+    +----------------+
```

## CH32V003 J4M6 D03

You need a WCH-LinkE programmer to flash this MCU. You connect SWIO to PD1 (pin 8), VDD to pin 4 and VSS to pin 2.

```
     CH32V003J4M6D03             WCH-LinkE
   +-----------------+    +----------------+
   |                 |    |                |
   |         VSS (2) o----o GND            |
   |         PD1 (8) o----o SWDIO/TMS      |
   |         VDD (4) o----o 3V3            |
   |                 |    |                |
   +-----------------+    +----------------+
```

# Platformio an the WCH CH32V Platform

 - https://ch405labs.net/ch32v003_intro/