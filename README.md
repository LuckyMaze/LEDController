# LEDController

This repo contains the CircuitPython controller for a 64x64 HUB75 LED panel.

## Serial protocol

The Pico reads commands from the USB serial console.

1. Send `INIT` once after boot.
2. Send `GRID`.
3. Send 64 rows of 64 cells each.
4. Send `MOVE x y` to move the yellow dot to a walkable coordinate.

### Grid format

Each row may be either:

1. A 64-character string using `1` for open and `0` for blocked.
2. 64 values separated by spaces or commas.

Examples of open cells: `1`, `true`, `t`, `yes`, `open`, `.`

Examples of blocked cells: `0`, `false`, `f`, `no`, `wall`, anything else

### Responses

The controller replies with simple status lines:

1. `OK INIT`
2. `OK GRID`
3. `OK MOVE x y`
4. `ERR ...` for invalid commands or unreachable targets

### Example session

```text
INIT
OK INIT
GRID
0000000000000000000000000000000000000000000000000000000000000000
... 63 more rows ...
OK GRID
MOVE 12 9
OK MOVE 12 9
```

## Notes

The controller uses `1`/`true` cells as walkable space and paints them black, blocked cells blue, the current dot yellow, and the target coordinate green.