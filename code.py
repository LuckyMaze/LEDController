"""
LED controller for a 64x64 HUB75 panel.

Serial protocol over USB console:

1. Send `INIT` to reset the controller state.
2. Send `GRID` and then 64 lines with 64 cells each.
   - `1`, `true`, `t`, `yes`, `open` mean walkable.
   - `0`, `false`, `f`, `no`, `wall` mean blocked.
3. Send `MOVE x y` to move the yellow dot to an open coordinate.

Example:

    INIT
    GRID
    000000...
    ... 64 lines total
    MOVE 12 9
"""

import sys
import time

import board
import displayio
import framebufferio
import rgbmatrix


SIZE = 64
BIT_DEPTH = 5
BRIGHTNESS = 0.5
MOVE_DELAY = 0.02

FLOOR = 0
WALL = 1
DOT = 2
TARGET = 3


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
palette[TARGET] = dim(0x00FF00)

bitmap = displayio.Bitmap(SIZE, SIZE, 4)
group = displayio.Group()
group.append(displayio.TileGrid(bitmap, pixel_shader=palette))
display.root_group = group

grid = [[False] * SIZE for _ in range(SIZE)]
dot_x = 0
dot_y = 0
target_x = 0
target_y = 0
initialized = False
grid_loaded = False


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


def render_map(highlight_target=True):
    for y in range(SIZE):
        row = grid[y]
        for x in range(SIZE):
            bitmap[x, y] = FLOOR if row[x] else WALL

    if highlight_target and is_walkable(target_x, target_y):
        bitmap[target_x, target_y] = TARGET

    if is_walkable(dot_x, dot_y):
        bitmap[dot_x, dot_y] = DOT


def reset_state():
    global grid, dot_x, dot_y, target_x, target_y, grid_loaded

    grid = [[False] * SIZE for _ in range(SIZE)]
    dot_x = 0
    dot_y = 0
    target_x = 0
    target_y = 0
    grid_loaded = False
    bitmap.fill(WALL)


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
    global grid, grid_loaded, dot_x, dot_y, target_x, target_y

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

    target_x, target_y = dot_x, dot_y
    render_map()


def neighbors(x, y):
    if y > 0:
        yield x, y - 1
    if y < SIZE - 1:
        yield x, y + 1
    if x > 0:
        yield x - 1, y
    if x < SIZE - 1:
        yield x + 1, y


def find_path(start_x, start_y, end_x, end_y):
    if (start_x, start_y) == (end_x, end_y):
        return [(start_x, start_y)]

    previous = [[None] * SIZE for _ in range(SIZE)]
    visited = [[False] * SIZE for _ in range(SIZE)]
    queue = [(start_x, start_y)]
    head = 0
    visited[start_y][start_x] = True

    while head < len(queue):
        x, y = queue[head]
        head += 1

        if (x, y) == (end_x, end_y):
            break

        for nx, ny in neighbors(x, y):
            if not visited[ny][nx] and grid[ny][nx]:
                visited[ny][nx] = True
                previous[ny][nx] = (x, y)
                queue.append((nx, ny))

    if not visited[end_y][end_x]:
        return None

    path = [(end_x, end_y)]
    current = previous[end_y][end_x]
    while current is not None:
        path.append(current)
        if current == (start_x, start_y):
            break
        current = previous[current[1]][current[0]]

    path.reverse()
    return path


def move_dot_to(x, y):
    global dot_x, dot_y, target_x, target_y

    if not grid_loaded:
        write_line("ERR NO_GRID")
        return

    if not is_walkable(x, y):
        write_line("ERR TARGET_BLOCKED")
        return

    if not is_walkable(dot_x, dot_y):
        dot_x, dot_y = first_open_cell()

    target_x = x
    target_y = y

    path = find_path(dot_x, dot_y, x, y)
    if path is None:
        write_line("ERR NO_PATH")
        return

    for step_x, step_y in path[1:]:
        dot_x = step_x
        dot_y = step_y
        render_map()
        time.sleep(MOVE_DELAY)

    render_map()
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

    if not initialized:
        if name != "INIT":
            write_line("ERR NEED_INIT")
            continue

        initialized = True
        reset_state()
        write_line("OK INIT")
        continue

    if name == "INIT":
        reset_state()
        write_line("OK INIT")
        continue

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
        if len(parts) != 3:
            write_line("ERR MOVE x y")
            continue
        try:
            move_dot_to(int(parts[1]), int(parts[2]))
        except ValueError:
            write_line("ERR MOVE x y")
        continue

    if name == "STATUS":
        write_line(
            "OK STATUS INIT={} GRID={} DOT={} {} TARGET={} {}".format(
                initialized,
                grid_loaded,
                dot_x,
                dot_y,
                target_x,
                target_y,
            )
        )
        continue

    if name == "CLEAR":
        reset_state()
        write_line("OK CLEAR")
        continue

    write_line("ERR UNKNOWN_CMD")
