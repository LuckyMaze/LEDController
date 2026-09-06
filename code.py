"""
LED controller for a 64x64 HUB75 panel.

Serial protocol over USB console:

1. Send `CLEAR` to reset the controller state.
2. Send `GRID` and then 64 lines with 64 cells each.
   - `1`, `true`, `t`, `yes`, `open` mean walkable.
   - `0`, `false`, `f`, `no`, `wall` mean blocked.
3. Send `MOVE x y [size]` to move the yellow dot to an open coordinate. `size` (default 1) is the
   side length of the square drawn around (x, y) - pass the maze's corridor width so the dot fills
   it, the same way a cell's own floor block does.
4. Send `EXIT x y width height` to mark a rectangle green and keep it marked - call once per exit,
   after `GRID`, with (x, y) as its top-left corner. Exits stay drawn (redrawn under the dot on
   every `MOVE`) until the next `CLEAR`.
5. Send `TEXT [x y] message` to show text on top of the grid.
6. Send `CLEAR` to blank the canvas, remove any text, and forget all exits.
7. Send `COLOR RRGGBB` to change the text color.

Example:

    GRID
    000000...
    ... 64 lines total
    EXIT 0 8 3 2
    MOVE 12 9 2
"""

import sys
import time

import board
import displayio
import framebufferio
import rgbmatrix
import terminalio
from adafruit_display_text.label import Label


SIZE = 64
BIT_DEPTH = 5
BRIGHTNESS = 0.5
MOVE_DELAY = 0.02

FLOOR = 0
WALL = 1
DOT = 2
EXIT = 3

DEFAULT_TEXT_COLOR = 0x00FF00


def dim(color):
    r = int(((color >> 16) & 0xFF) * BRIGHTNESS)
    g = int(((color >> 8) & 0xFF) * BRIGHTNESS)
    b = int((color & 0xFF) * BRIGHTNESS)
    return (r << 16) | (g << 8) | b


displayio.release_displays()

matrix = rgbmatrix.RGBMatrix(
    width=SIZE,
    bit_depth=BIT_DEPTH,
    rgb_pins=[board.GP0, board.GP1, board.GP2, board.GP3, board.GP4, board.GP5],
    addr_pins=[board.GP6, board.GP7, board.GP8, board.GP13, board.GP9],
    clock_pin=board.GP10,
    latch_pin=board.GP11,
    output_enable_pin=board.GP12,
)
display = framebufferio.FramebufferDisplay(matrix, auto_refresh=True)

palette = displayio.Palette(4)
palette[FLOOR] = 0x000000
palette[WALL] = dim(0x1030C0)
palette[DOT] = dim(0xFFFF00)
palette[EXIT] = dim(0x00FF00)

bitmap = displayio.Bitmap(SIZE, SIZE, 4)
group = displayio.Group()
group.append(displayio.TileGrid(bitmap, pixel_shader=palette))

text_label = Label(terminalio.FONT, text="", color=dim(DEFAULT_TEXT_COLOR))
text_label.x = 2
text_label.y = SIZE // 2
group.append(text_label)

display.root_group = group

grid = [[False] * SIZE for _ in range(SIZE)]
dot_x = 0
dot_y = 0
dot_size = 1
exits = []
grid_loaded = False
current_text_color = dim(DEFAULT_TEXT_COLOR)


def write_line(text):
    print(text)


def in_bounds(x, y):
    return 0 <= x < SIZE and 0 <= y < SIZE


def is_walkable(x, y):
    return in_bounds(x, y) and grid[y][x]


def first_open_cell():
    for y in range(SIZE):
        for x in range(SIZE):
            if grid[y][x]:
                return x, y
    return 0, 0


def paint_rect(x0, y0, width, height, val):
    """Paint a width x height rectangle with its top-left corner at (x0, y0), clipped to the panel."""
    for dy in range(height):
        y = y0 + dy
        if not 0 <= y < SIZE:
            continue
        for dx in range(width):
            x = x0 + dx
            if 0 <= x < SIZE:
                bitmap[x, y] = val


def paint_block(cx, cy, size, val):
    """Paint a size x size square centered on (cx, cy), clipped to the panel."""
    half = size // 2
    paint_rect(cx - half, cy - half, size, size, val)


def draw_base():
    """Draw the static grid once - no exits, no dot. Callers layer those on top afterward."""
    for y in range(SIZE):
        row = grid[y]
        for x in range(SIZE):
            bitmap[x, y] = FLOOR if row[x] else WALL


def base_color_at(x, y):
    """What (x, y) should show with the dot removed: an exit if it's under one, else the grid."""
    for ex, ey, ew, eh in exits:
        if ex <= x < ex + ew and ey <= y < ey + eh:
            return EXIT
    return FLOOR if grid[y][x] else WALL


def restore_rect(x0, y0, width, height):
    """Repaint a rectangle from the grid/exits, e.g. to erase the dot without a full redraw."""
    for dy in range(height):
        y = y0 + dy
        if not 0 <= y < SIZE:
            continue
        for dx in range(width):
            x = x0 + dx
            if 0 <= x < SIZE:
                bitmap[x, y] = base_color_at(x, y)


def restore_block(cx, cy, size):
    half = size // 2
    restore_rect(cx - half, cy - half, size, size)


def mark_exit(x, y, width, height):
    if not grid_loaded:
        write_line("ERR NO_GRID")
        return

    width = max(1, width)
    height = max(1, height)
    exits.append((x, y, width, height))
    paint_rect(x, y, width, height, EXIT)
    write_line("OK EXIT {} {}".format(x, y))


def clear_text():
    text_label.text = ""


def show_text(message, x=2, y=None):
    text_label.color = current_text_color
    text_label.text = message
    text_label.x = x
    text_label.y = SIZE // 2 if y is None else y


def center_text(message):
    show_text(message, 2, SIZE // 2)
    bounds = text_label.bounding_box
    text_label.x = max(0, (SIZE - bounds[2]) // 2)
    text_label.y = max(bounds[3], (SIZE + bounds[3]) // 2)


def scroll_text(message):
    show_text(message, SIZE, SIZE // 2)
    bounds = text_label.bounding_box
    for x in range(SIZE, -bounds[2], -1):
        text_label.x = x
        time.sleep(MOVE_DELAY)


def reset_state():
    global grid, dot_x, dot_y, dot_size, exits, grid_loaded

    grid = [[False] * SIZE for _ in range(SIZE)]
    dot_x = 0
    dot_y = 0
    dot_size = 1
    exits = []
    grid_loaded = False
    bitmap.fill(WALL)
    clear_text()


def clear_canvas():
    reset_state()


def parse_color(token):
    token = token.strip().lower()
    if token.startswith("#"):
        token = token[1:]
    if token.startswith("0x"):
        token = token[2:]
    if len(token) != 6:
        raise ValueError("color must be RRGGBB")
    return int(token, 16)


def parse_bool_token(token):
    token = token.strip().lower()
    return token in ("1", "true", "t", "yes", "y", "open")


def parse_grid_row(text):
    text = text.strip()
    if not text:
        raise ValueError("empty grid row")

    if "," in text or " " in text or "\t" in text:
        tokens = []
        for token in text.replace(",", " ").split():
            if token:
                tokens.append(token)
        if len(tokens) != SIZE:
            raise ValueError("grid row must contain 64 values")
        return [parse_bool_token(token) for token in tokens]

    if len(text) != SIZE:
        raise ValueError("grid row must be 64 characters long")

    return [char in ("1", "t", "T", "y", "Y", ".") for char in text]


def load_grid_from_serial():
    global grid, grid_loaded, dot_x, dot_y

    new_grid = []
    for _ in range(SIZE):
        row_text = sys.stdin.readline()
        if not row_text:
            raise EOFError("missing grid row")
        new_grid.append(parse_grid_row(row_text))

    grid = new_grid
    grid_loaded = True

    if not is_walkable(dot_x, dot_y):
        dot_x, dot_y = first_open_cell()

    draw_base()


def move_dot_to(x, y, size=1):
    global dot_x, dot_y, dot_size

    if not grid_loaded:
        write_line("ERR NO_GRID")
        return

    if not is_walkable(x, y):
        write_line("ERR TARGET_BLOCKED")
        return

    # No pathfinding here - the caller already knows the maze and steps the dot one cell at a
    # time, so this just places it. A prior version searched for a route and animated the dot
    # along it, which meant a full breadth-first search over the 64x64 grid on every MOVE - on a
    # Pico's ~264KB of RAM, alongside the RGB matrix's own buffers, that's a `MemoryError`,
    # confirmed against real hardware. That crash isn't just a dropped command either: it's
    # uncaught (only `ValueError` is handled around this call), so it can take the whole
    # supervisor down mid-frame and leave the panel dark.
    #
    # Only touch the two spots that actually change - erase the old dot back to its real color,
    # paint the new one - instead of redrawing all 4096 pixels on every step.
    restore_block(dot_x, dot_y, dot_size)
    dot_x, dot_y = x, y
    dot_size = max(1, size)
    paint_block(dot_x, dot_y, dot_size, DOT)
    write_line("OK MOVE {} {}".format(x, y))


def read_command():
    line = sys.stdin.readline()
    if not line:
        return None
    return line.strip()


reset_state()
write_line("BOOT READY")

while True:
    command = read_command()
    if command is None:
        continue
    if not command:
        continue

    parts = command.split()
    name = parts[0].upper()

    if name == "GRID":
        try:
            load_grid_from_serial()
        except Exception as exc:
            reset_state()
            write_line("ERR GRID {}".format(exc))
            continue
        write_line("OK GRID")
        continue

    if name == "MOVE":
        if len(parts) not in (3, 4):
            write_line("ERR MOVE x y [size]")
            continue
        try:
            move_x = int(parts[1])
            move_y = int(parts[2])
            move_size = int(parts[3]) if len(parts) == 4 else 1
            move_dot_to(move_x, move_y, move_size)
        except ValueError:
            write_line("ERR MOVE x y [size]")
        continue

    if name == "EXIT":
        if len(parts) != 5:
            write_line("ERR EXIT x y width height")
            continue
        try:
            exit_x = int(parts[1])
            exit_y = int(parts[2])
            exit_w = int(parts[3])
            exit_h = int(parts[4])
            mark_exit(exit_x, exit_y, exit_w, exit_h)
        except ValueError:
            write_line("ERR EXIT x y width height")
        continue

    if name == "STATUS":
        write_line(
            "OK STATUS GRID={} DOT={} {} SIZE={}".format(
                grid_loaded,
                dot_x,
                dot_y,
                dot_size,
            )
        )
        continue

    if name == "CLEAR":
        clear_canvas()
        write_line("OK CLEAR")
        continue

    if name == "COLOR":
        if len(parts) != 2:
            write_line("ERR COLOR RRGGBB")
            continue
        try:
            current_text_color = dim(parse_color(parts[1]))
        except ValueError as exc:
            write_line("ERR COLOR {}".format(exc))
            continue
        text_label.color = current_text_color
        write_line("OK COLOR")
        continue

    if name == "TEXT":
        if len(parts) >= 4:
            try:
                text_x = int(parts[1])
                text_y = int(parts[2])
                message = " ".join(parts[3:])
            except ValueError:
                text_x = 2
                text_y = SIZE // 2
                message = " ".join(parts[1:])
        else:
            text_x = 2
            text_y = SIZE // 2
            message = " ".join(parts[1:])

        if not message:
            write_line("ERR TEXT message")
            continue

        show_text(message, text_x, text_y)
        write_line("OK TEXT")
        continue

    if name == "CENTER":
        message = " ".join(parts[1:])
        if not message:
            write_line("ERR CENTER message")
            continue

        center_text(message)
        write_line("OK CENTER")
        continue

    if name == "SCROLL":
        message = " ".join(parts[1:])
        if not message:
            write_line("ERR SCROLL message")
            continue

        scroll_text(message)
        write_line("OK SCROLL")
        continue

    write_line("ERR UNKNOWN_CMD")
