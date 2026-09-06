# LEDController

This repo contains the CircuitPython controller for a 64x64 HUB75 LED panel.

## Installing on the Pico

1. Flash CircuitPython onto the Raspberry Pi Pico: hold BOOTSEL while plugging it in, then drag
   the `.uf2` from [circuitpython.org/board/raspberry_pi_pico](https://circuitpython.org/board/raspberry_pi_pico/)
   onto the `RPI-RP2` drive that appears. It reboots as a `CIRCUITPY` drive.
2. Copy `adafruit_display_text` from the
   [Adafruit CircuitPython bundle](https://circuitpython.org/libraries) (matching your CircuitPython
   version) into `CIRCUITPY/lib/`. It's the only dependency `code.py` needs.
3. Copy this repo's `code.py` to the root of `CIRCUITPY`, replacing the sample one CircuitPython
   ships with. It runs automatically on boot/reset - no `boot.py` is needed, the default single USB
   serial console is enough for both the REPL and this protocol.
4. Wire the HUB75 panel to the pins `code.py` expects:

   | Panel signal | Pico pin |
   |---|---|
   | R1, G1, B1, R2, G2, B2 | GP0-GP5 |
   | A, B, C, D, E (row address) | GP6, GP7, GP8, GP13, GP9 |
   | CLK | GP10 |
   | LAT | GP11 |
   | OE | GP12 |

   Power the panel from its own 5V supply, not the Pico's USB rail - HUB75 panels draw far more
   current than USB can provide.
5. Plug the Pico in over USB. It enumerates as a serial device; find its stable path with
   `ls /dev/serial/by-id/` on Linux (`/dev/ttyACM0` shifts if anything else is plugged in first).
6. Sanity check without any other software involved: open a serial terminal at 115200 baud and
   send `CLEAR` then `GRID` followed by 64 rows of `0`/`1` - you should get `OK CLEAR` / `OK GRID`
   back and see the panel light up.

## Serial protocol

The Pico reads commands from the USB serial console.

1. Send `CLEAR` to reset the controller state.
2. Send `GRID`.
3. Send 64 rows of 64 cells each.
4. Send `MOVE x y [size]` to place the yellow dot at a walkable coordinate. `size` (default 1) is
   the side length of the square drawn around it - pass the maze's corridor width so the dot fills
   it, matching a cell's own floor block.
5. Send `EXIT x y width height` to mark a rectangle green, once per exit, after `GRID`, with
   (x, y) as its top-left corner. Exits stay drawn - redrawn under the dot on every `MOVE` -
   until the next `CLEAR`.

### Grid format

Each row may be either:

1. A 64-character string using `1` for open and `0` for blocked.
2. 64 values separated by spaces or commas.

Examples of open cells: `1`, `true`, `t`, `yes`, `open`, `.`

Examples of blocked cells: `0`, `false`, `f`, `no`, `wall`, anything else

### Responses

The controller replies with simple status lines:

1. `OK CLEAR`
2. `OK GRID`
3. `OK MOVE x y` (echoes the coordinate, not the size)
4. `OK EXIT x y` (echoes the coordinate, not the size)
5. `ERR ...` for invalid commands or unreachable targets

### Example session

```text
CLEAR
OK CLEAR
GRID
0000000000000000000000000000000000000000000000000000000000000000
... 63 more rows ...
OK GRID
EXIT 0 8 3 2
OK EXIT 0 8
MOVE 12 9 2
OK MOVE 12 9
```

## Notes

The controller uses `1`/`true` cells as walkable space and paints them black, blocked cells blue, exits green, and the current dot yellow.

## Text overlay

`code.py` also supports a text overlay on top of the grid. It requires the `adafruit_display_text` library. It understands these commands:

1. `TEXT [x y] message` to place text at a coordinate.
2. `CLEAR` to blank the canvas and remove any text.
3. `COLOR RRGGBB` to change the text color.
4. `CENTER message` to center text.
5. `SCROLL message` to scroll text across the display.