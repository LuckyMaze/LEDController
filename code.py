"""
LED controller for a 64x64 HUB75 panel.

Serial protocol over USB console:

1. Send `CLEAR` to reset the controller state.
2. Send `GRID` and then 64 lines with 64 cells each.
   - `1`, `true`, `t`, `yes`, `open` mean walkable.
   - `0`, `false`, `f`, `no`, `wall` mean blocked.
3. Send `MOVE x y` to move the yellow dot to an open coordinate.
4. Send `TEXT [x y] message` to show text on top of the grid.
5. Send `CLEAR` to blank the canvas and remove any text.
6. Send `COLOR RRGGBB` to change the text color.

Example:

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
import terminalio
from adafruit_display_text.label import Label


SIZE = 64
BIT_DEPTH = 5
BRIGHTNESS = 0.5
MOVE_DELAY = 0.02

FLOOR = 0
WALL = 1
DOT = 2
TARGET = 3

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
palette[TARGET] = dim(0x00FF00)

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
target_x = 0
target_y = 0
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


def render_map(highlight_target=True):
    for y in range(SIZE):
        row = grid[y]
        for x in range(SIZE):
            bitmap[x, y] = FLOOR if row[x] else WALL

    if highlight_target and is_walkable(target_x, target_y):
        bitmap[target_x, target_y] = TARGET

    if is_walkable(dot_x, dot_y):
        bitmap[dot_x, dot_y] = DOT


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
    global grid, dot_x, dot_y, target_x, target_y, grid_loaded

    grid = [[False] * SIZE for _ in range(SIZE)]
    dot_x = 0
    dot_y = 0
    target_x = 0
    target_y = 0
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
            "OK STATUS GRID={} DOT={} {} TARGET={} {}".format(
                grid_loaded,
                dot_x,
                dot_y,
                target_x,
                target_y,
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
