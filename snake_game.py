"""
NEON GRID SNAKE
A redesigned Tkinter Snake game: neon-on-navy visual identity, start screen,
pause / game-over overlays, levels, bonus stars, persistent high score and
optional sound (Windows only, standard library).

Run:  python snake_game.py        (no extra packages needed)
"""

import json
import math
import queue
import random
import threading
import time
import tkinter as tk
from pathlib import Path

try:  # Built into Python on Windows. On macOS/Linux the game is simply silent.
    import winsound
except ImportError:
    winsound = None


# =============================================================================
# CONFIGURATION
# =============================================================================
CELL = 30                 # size of one grid cell in pixels
COLS = 28                 # board is 28 x 17 cells = 840 x 510 px
ROWS = 17
PAD = 10                  # margin around the board inside the canvas
BOARD_W = COLS * CELL
BOARD_H = ROWS * CELL
CANVAS_W = BOARD_W + 2 * PAD
CANVAS_H = BOARD_H + 2 * PAD

START_LENGTH = 3
BASE_SPEED_MS = 120       # time between moves at level 1
SPEED_STEP_MS = 9         # faster by this much each level
MIN_SPEED_MS = 55         # speed cap
FOODS_PER_LEVEL = 5
FOOD_POINTS = 10
BONUS_POINTS = 30
BONUS_EVERY = 4           # a bonus star appears after every 4th orb
BONUS_LIFETIME_TICKS = 45
FRAME_MS = 33             # render loop (~30 FPS) - separate from the game tick
DEATH_ANIM_SECONDS = 0.8

DIRECTIONS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
KEYMAP = {
    "Left": "left", "a": "left", "A": "left",
    "Right": "right", "d": "right", "D": "right",
    "Up": "up", "w": "up", "W": "up",
    "Down": "down", "s": "down", "S": "down",
}

HIGH_SCORE_FILE = Path(__file__).with_name("snake_highscore.json")


# =============================================================================
# DESIGN SYSTEM  -  "Neon Grid": deep navy, electric teal, violet, hot pink
# =============================================================================
BG = "#070b1a"            # window background
BOARD_BG = "#0a1128"      # board base
BOARD_ALT = "#0d1631"     # checkerboard tint
PANEL = "#0f1833"         # cards / panels
PANEL_HI = "#17234a"      # buttons
BORDER = "#26366b"
PRIMARY = "#19f5d0"       # teal  - snake head, primary buttons, title
SECONDARY = "#7c5cff"     # violet - snake tail, glows
ACCENT = "#ff3d81"        # pink  - food
GOLD = "#ffd23f"          # bonus + high score
DANGER = "#ff4d6d"
TEXT = "#e8ecff"
TEXT_DIM = "#9aa6d1"
MUTED = "#6572a3"
SNAKE_HEAD = PRIMARY
SNAKE_TAIL = "#6a5cff"

UI_FONT = "Segoe UI"     # falls back automatically if missing
MONO_FONT = "Consolas"


# =============================================================================
# SMALL HELPERS
# =============================================================================
def mix(color_a, color_b, t):
    """Blend two '#rrggbb' colours. t=0 -> a, t=1 -> b."""
    t = max(0.0, min(1.0, t))
    a = [int(color_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(color_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rounded_rect(canvas, x1, y1, x2, y2, r=12, **kwargs):
    """Draw a rounded rectangle (smoothed polygon) and return its item id."""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def draw_orb(canvas, x, y, r, tags):
    """Glowing energy orb (the food)."""
    canvas.create_oval(x - r * 2.1, y - r * 2.1, x + r * 2.1, y + r * 2.1,
                       fill=mix(ACCENT, BOARD_BG, 0.85), outline="", tags=tags)
    canvas.create_oval(x - r * 1.55, y - r * 1.55, x + r * 1.55, y + r * 1.55,
                       fill=mix(ACCENT, BOARD_BG, 0.62), outline="", tags=tags)
    canvas.create_oval(x - r, y - r, x + r, y + r,
                       fill=ACCENT, outline=mix(ACCENT, "#ffffff", 0.5), width=1, tags=tags)
    canvas.create_oval(x - r * 0.55, y - r * 0.6, x - r * 0.1, y - r * 0.15,
                       fill="#ffd6e6", outline="", tags=tags)


def draw_star(canvas, x, y, r, rotation, tags):
    """Rotating gold star (the bonus food)."""
    canvas.create_oval(x - r * 1.5, y - r * 1.5, x + r * 1.5, y + r * 1.5,
                       fill=mix(GOLD, BOARD_BG, 0.82), outline="", tags=tags)
    points = []
    for i in range(10):
        angle = rotation + i * math.pi / 5 - math.pi / 2
        radius = r if i % 2 == 0 else r * 0.45
        points += [x + math.cos(angle) * radius, y + math.sin(angle) * radius]
    canvas.create_polygon(points, fill=GOLD, outline=mix(GOLD, "#ffffff", 0.6),
                          width=1, tags=tags)


def load_high_score():
    try:
        return int(json.loads(HIGH_SCORE_FILE.read_text()).get("high_score", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def save_high_score(value):
    try:
        HIGH_SCORE_FILE.write_text(json.dumps({"high_score": value}))
    except OSError:
        pass  # saving is a nice-to-have, never crash the game for it


# =============================================================================
# GAME LOGIC  (no Tkinter in here - pure rules)
# =============================================================================
class GameLogic:
    """Snake rules: movement, food, bonus star, scoring, levels, collisions."""

    def __init__(self, cols, rows):
        self.cols = cols
        self.rows = rows
        self.reset()

    def reset(self):
        cx, cy = self.cols // 2, self.rows // 2
        # index 0 is the head
        self.snake = [(cx - i, cy) for i in range(START_LENGTH)]
        self.direction = DIRECTIONS["right"]
        self.pending = []            # buffered key presses (max 3)
        self.score = 0
        self.foods_eaten = 0
        self.level = 1
        self.alive = True
        self.won = False
        self.bonus = None
        self.bonus_ticks = 0
        self.food = None
        self.food = self._random_free_cell()

    def speed_ms(self):
        return max(MIN_SPEED_MS, BASE_SPEED_MS - (self.level - 1) * SPEED_STEP_MS)

    def queue_direction(self, name):
        """Queue a turn. Blocks instant 180-degree reversals (original rule)."""
        new = DIRECTIONS[name]
        reference = self.pending[-1] if self.pending else self.direction
        if new == reference:
            return
        if new[0] == -reference[0] and new[1] == -reference[1]:
            return
        if len(self.pending) < 3:
            self.pending.append(new)

    def _random_free_cell(self):
        occupied = set(self.snake)
        if self.food:
            occupied.add(self.food)
        if self.bonus:
            occupied.add(self.bonus)
        free = [(c, r) for c in range(self.cols) for r in range(self.rows)
                if (c, r) not in occupied]
        return random.choice(free) if free else None

    def step(self):
        """Advance one tick. Returns a list of (event_name, cell) tuples."""
        events = []
        if self.pending:
            self.direction = self.pending.pop(0)

        head_x, head_y = self.snake[0]
        new_head = (head_x + self.direction[0], head_y + self.direction[1])

        # Wall collision
        if not (0 <= new_head[0] < self.cols and 0 <= new_head[1] < self.rows):
            self.alive = False
            events.append(("die", None))
            return events

        eats_food = new_head == self.food
        eats_bonus = self.bonus is not None and new_head == self.bonus
        grows = eats_food or eats_bonus

        # Self collision. When not growing, the tail moves away this tick,
        # so stepping into the tail's current cell is legal.
        body = self.snake if grows else self.snake[:-1]
        if new_head in body:
            self.alive = False
            events.append(("die", None))
            return events

        self.snake.insert(0, new_head)
        if not grows:
            self.snake.pop()

        # Bonus star countdown
        if self.bonus is not None and not eats_bonus:
            self.bonus_ticks -= 1
            if self.bonus_ticks <= 0:
                self.bonus = None

        if eats_bonus:
            self.score += BONUS_POINTS
            self.bonus = None
            events.append(("bonus", new_head))

        if eats_food:
            self.score += FOOD_POINTS
            self.foods_eaten += 1
            self.food = self._random_free_cell()
            events.append(("eat", new_head))
            if self.bonus is None and self.foods_eaten % BONUS_EVERY == 0:
                cell = self._random_free_cell()
                if cell:
                    self.bonus = cell
                    self.bonus_ticks = BONUS_LIFETIME_TICKS
            new_level = self.foods_eaten // FOODS_PER_LEVEL + 1
            if new_level > self.level:
                self.level = new_level
                events.append(("level", new_head))

        if self.food is None:  # the board is completely full - perfect game
            self.alive = False
            self.won = True

        return events


# =============================================================================
# SOUND  (optional, never required)
# =============================================================================
class Sound:
    TONES = {
        "click": [(700, 30)],
        "start": [(523, 70), (659, 70), (784, 110)],
        "eat": [(880, 40), (1175, 50)],
        "bonus": [(988, 50), (1319, 50), (1568, 80)],
        "level": [(659, 60), (784, 60), (988, 60), (1319, 120)],
        "over": [(392, 140), (330, 140), (262, 300)],
    }

    def __init__(self):
        self.available = winsound is not None
        self.enabled = self.available
        self._queue = queue.Queue(maxsize=4)
        if self.available:
            threading.Thread(target=self._worker, daemon=True).start()

    def play(self, name):
        if not (self.available and self.enabled):
            return
        try:
            self._queue.put_nowait(self.TONES[name])
        except queue.Full:
            pass

    def _worker(self):
        # Beep() blocks, so it lives on its own thread to keep the game smooth.
        while True:
            sequence = self._queue.get()
            if sequence is None:
                return
            for frequency, duration in sequence:
                try:
                    winsound.Beep(frequency, duration)
                except Exception:
                    break

    def shutdown(self):
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass


# =============================================================================
# UI WIDGETS
# =============================================================================
class FlatButton(tk.Label):
    """Flat top-bar button with hover and disabled states."""

    def __init__(self, parent, text, command):
        super().__init__(parent, text=text, font=(UI_FONT, 11, "bold"), fg=TEXT,
                         bg=PANEL_HI, padx=16, pady=9, cursor="hand2",
                         highlightthickness=1, highlightbackground=BORDER)
        self.command = command
        self.enabled = True
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _on_enter(self, _event):
        if self.enabled:
            self.config(bg=mix(PANEL_HI, PRIMARY, 0.25), highlightbackground=PRIMARY)

    def _on_leave(self, _event):
        self.config(bg=PANEL_HI, highlightbackground=BORDER)

    def _on_click(self, _event):
        if self.enabled:
            self.command()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.config(fg=TEXT if enabled else MUTED,
                    cursor="hand2" if enabled else "arrow",
                    bg=PANEL_HI, highlightbackground=BORDER)


# =============================================================================
# THE APPLICATION  (UI + state machine)
# =============================================================================
class SnakeApp:
    """
    States:  menu -> howto -> menu
             menu -> playing <-> paused
             playing -> gameover -> (playing | menu)

    Two independent timers run on Tk's after():
      * the game tick  (self.tick_id)  - moves the snake, only while 'playing'
      * the render loop (self.frame_id) - animations, runs for the app lifetime
    Every code path cancels the old tick before scheduling a new one, so loops
    can never stack up or speed the game up after a restart.
    """

    def __init__(self, root):
        self.root = root
        root.title("SNAKE - Neon Grid")
        root.configure(bg=BG)
        root.resizable(False, False)

        self.logic = GameLogic(COLS, ROWS)
        self.sound = Sound()
        self.high_score = load_high_score()
        self.high_dirty = False
        self.session_start_best = self.high_score

        self.state = "menu"
        self.tick_id = None
        self.frame_id = None
        self.closing = False
        self.particles = []
        self.floaters = []
        self.death_time = 0.0
        self.new_best = False
        self.gameover_built = False
        self.btn_counter = 0
        self.last_frame = time.perf_counter()

        self._build_topbar()
        self._build_board()
        self._bind_keys()
        self._center_window()

        root.protocol("WM_DELETE_WINDOW", self.quit_game)
        root.focus_force()

        self._update_hud()
        self.show_menu()
        self._frame()

    # ------------------------------------------------------------------ layout
    def _build_topbar(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=PAD + 4, pady=(12, 8))
        bar.columnconfigure(1, weight=1)

        # Logo (left)
        logo = tk.Frame(bar, bg=BG)
        logo.grid(row=0, column=0, sticky="w")
        icon = tk.Canvas(logo, width=46, height=46, bg=BG, highlightthickness=0)
        icon.pack(side="left")
        rounded_rect(icon, 4, 4, 42, 42, r=13, fill=PRIMARY, outline="")
        for ex in (17, 30):
            icon.create_oval(ex - 5, 16, ex + 5, 28, fill="white", outline="")
            icon.create_oval(ex - 2, 19, ex + 3, 26, fill=BG, outline="")
        titles = tk.Frame(logo, bg=BG)
        titles.pack(side="left", padx=(10, 0))
        tk.Label(titles, text="SNAKE", font=(UI_FONT, 24, "bold"),
                 fg=PRIMARY, bg=BG).pack(anchor="w")
        tk.Label(titles, text="NEON GRID EDITION", font=(UI_FONT, 8, "bold"),
                 fg=MUTED, bg=BG).pack(anchor="w")

        # Stat cards (center)
        stats = tk.Frame(bar, bg=BG)
        stats.grid(row=0, column=1)
        self.score_label = self._make_stat(stats, "SCORE", "000000", TEXT)
        self.high_label = self._make_stat(stats, "HIGH SCORE", f"{self.high_score:06d}", GOLD)
        self.level_label = self._make_stat(stats, "LEVEL", "1", "#a58bff")

        # Buttons (right)
        buttons = tk.Frame(bar, bg=BG)
        buttons.grid(row=0, column=2, sticky="e")
        self.pause_button = FlatButton(buttons, "\u275a\u275a  PAUSE", self.toggle_pause)
        self.pause_button.pack(side="left", padx=(0, 8))
        self.sound_button = FlatButton(buttons, "\u266a  SOUND ON", self.toggle_sound)
        self.sound_button.pack(side="left")
        if not self.sound.available:
            self.sound_button.config(text="\u266a  NO AUDIO")
            self.sound_button.set_enabled(False)

    def _make_stat(self, parent, caption, value, color):
        card = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        card.pack(side="left", padx=6)
        tk.Label(card, text=caption, font=(UI_FONT, 8, "bold"), fg=MUTED,
                 bg=PANEL).pack(padx=20, pady=(6, 0))
        label = tk.Label(card, text=value, font=(MONO_FONT, 22, "bold"), fg=color, bg=PANEL)
        label.pack(padx=20, pady=(0, 6))
        label.base_color = color
        return label

    def _build_board(self):
        self.canvas = tk.Canvas(self.root, width=CANVAS_W, height=CANVAS_H,
                                bg=BG, highlightthickness=0)
        self.canvas.pack(padx=PAD, pady=(0, PAD + 4))
        c = self.canvas
        # Glowing frame
        rounded_rect(c, PAD - 5, PAD - 5, PAD + BOARD_W + 5, PAD + BOARD_H + 5, r=16,
                     fill=BOARD_BG, outline=mix(SECONDARY, BG, 0.7), width=6, tags="bg")
        # Subtle checkerboard instead of harsh grid lines
        for col in range(COLS):
            for row in range(ROWS):
                if (col + row) % 2 == 0:
                    x, y = PAD + col * CELL, PAD + row * CELL
                    c.create_rectangle(x, y, x + CELL, y + CELL, fill=BOARD_ALT,
                                       outline="", tags="bg")
        # Crisp border on top
        rounded_rect(c, PAD - 1, PAD - 1, PAD + BOARD_W + 1, PAD + BOARD_H + 1, r=10,
                     fill="", outline=mix(PRIMARY, BG, 0.4), width=3, tags="bg")

    def _center_window(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = max(0, (self.root.winfo_screenheight() - h) // 2 - 20)
        self.root.geometry(f"+{x}+{y}")

    def _bind_keys(self):
        self.root.bind("<KeyPress>", self._on_key)

    # --------------------------------------------------------------- keyboard
    def _on_key(self, event):
        key = event.keysym
        if key in KEYMAP:
            if self.state == "playing":
                self.logic.queue_direction(KEYMAP[key])
        elif key in ("space", "p", "P"):
            self.toggle_pause()
        elif key == "Escape":
            if self.state == "playing":
                self.pause_game()
            elif self.state == "howto":
                self.show_menu()
        elif key in ("m", "M"):
            self.toggle_sound()
        elif key == "Return":
            if self.state == "menu":
                self.start_game()
            elif self.state == "paused":
                self.resume_game()
            elif self.state == "gameover" and self.gameover_built:
                self.start_game()

    # ------------------------------------------------------------ state flow
    def _cancel_tick(self):
        if self.tick_id is not None:
            self.root.after_cancel(self.tick_id)
            self.tick_id = None

    def _schedule_tick(self, delay_ms):
        self._cancel_tick()  # guarantees only ONE tick loop exists
        self.tick_id = self.root.after(delay_ms, self._tick)

    def show_menu(self):
        self._cancel_tick()
        self.state = "menu"
        self.gameover_built = False
        self.particles.clear()
        self.floaters.clear()
        self._clear_overlay()
        self._build_menu_overlay()
        self._sync_buttons()

    def show_how_to_play(self):
        if self.state != "menu":
            return
        self.state = "howto"
        self._clear_overlay()
        self._build_how_overlay()
        self._sync_buttons()

    def start_game(self):
        self._cancel_tick()
        self.logic.reset()
        self.particles.clear()
        self.floaters.clear()
        self.new_best = False
        self.gameover_built = False
        self.session_start_best = self.high_score
        self._clear_overlay()
        self.state = "playing"
        self._update_hud()
        self._sync_buttons()
        self.sound.play("start")
        self._schedule_tick(450)  # short "get ready" beat

    def pause_game(self):
        if self.state != "playing":
            return
        self._cancel_tick()  # genuinely stops the loop
        self.state = "paused"
        self._clear_overlay()
        self._build_pause_overlay()
        self._sync_buttons()

    def resume_game(self):
        if self.state != "paused":
            return
        self._clear_overlay()
        self.state = "playing"
        self._sync_buttons()
        self._schedule_tick(300)

    def toggle_pause(self):
        if self.state == "playing":
            self.pause_game()
        elif self.state == "paused":
            self.resume_game()

    def restart_game(self):
        if self.state in ("paused", "gameover"):
            self.start_game()

    def _game_over(self):
        self._cancel_tick()
        self.state = "gameover"
        self.death_time = time.perf_counter()
        self.new_best = self.logic.score > self.session_start_best
        self._commit_high_score()
        self._burst(self.logic.snake[0], DANGER, 22)
        self.sound.play("over")
        self._update_hud()
        self._sync_buttons()
        # The overlay itself appears after the death animation (see _frame).

    def quit_game(self):
        if self.closing:
            return
        self.closing = True
        self._cancel_tick()
        if self.frame_id is not None:
            self.root.after_cancel(self.frame_id)
        self._commit_high_score()
        self.sound.shutdown()
        self.root.destroy()

    def toggle_sound(self):
        if not self.sound.available:
            return
        self.sound.enabled = not self.sound.enabled
        self.sound_button.config(
            text="\u266a  SOUND ON" if self.sound.enabled else "\u266a  SOUND OFF")
        self.sound.play("click")

    def _commit_high_score(self):
        if self.high_dirty:
            save_high_score(self.high_score)
            self.high_dirty = False

    # --------------------------------------------------------------- game tick
    def _tick(self):
        self.tick_id = None
        if self.state != "playing":
            return
        events = self.logic.step()
        names = {name for name, _cell in events}

        for name, cell in events:
            if name == "eat":
                self._burst(cell, ACCENT, 14)
                self._float_text(cell, f"+{FOOD_POINTS}", ACCENT)
                self._update_hud(pop=True)
            elif name == "bonus":
                self._burst(cell, GOLD, 20)
                self._float_text(cell, f"+{BONUS_POINTS}", GOLD)
                self._update_hud(pop=True)
            elif name == "level":
                self._float_center(f"LEVEL {self.logic.level}", "#a58bff")
                self._update_hud(level_pop=True)

        if "level" in names:
            self.sound.play("level")
        elif "bonus" in names:
            self.sound.play("bonus")
        elif "eat" in names:
            self.sound.play("eat")

        if self.logic.score > self.high_score:
            self.high_score = self.logic.score
            self.high_dirty = True
            self._update_hud()

        if not self.logic.alive:
            self._game_over()
            return
        self._schedule_tick(self.logic.speed_ms())

    # --------------------------------------------------------------------- HUD
    def _update_hud(self, pop=False, level_pop=False):
        self.score_label.config(text=f"{self.logic.score:06d}")
        self.high_label.config(text=f"{self.high_score:06d}")
        self.level_label.config(text=str(self.logic.level))
        if pop:
            self._pop(self.score_label, GOLD)
        if level_pop:
            self._pop(self.level_label, "#ffffff")

    def _pop(self, label, color):
        label.config(fg=color)
        self.root.after(180, lambda: label.config(fg=label.base_color))

    def _sync_buttons(self):
        if self.state == "playing":
            self.pause_button.config(text="\u275a\u275a  PAUSE")
            self.pause_button.set_enabled(True)
        elif self.state == "paused":
            self.pause_button.config(text="\u25b6  RESUME")
            self.pause_button.set_enabled(True)
        else:
            self.pause_button.config(text="\u275a\u275a  PAUSE")
            self.pause_button.set_enabled(False)

    # ----------------------------------------------------------------- effects
    def _cell_center(self, cell):
        return PAD + cell[0] * CELL + CELL / 2, PAD + cell[1] * CELL + CELL / 2

    def _burst(self, cell, color, count):
        x, y = self._cell_center(cell)
        now = time.perf_counter()
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(1.0, 4.2)
            self.particles.append({
                "x": x, "y": y, "vx": math.cos(angle) * speed, "vy": math.sin(angle) * speed,
                "t0": now, "life": random.uniform(0.4, 0.75),
                "size": random.uniform(2.0, 4.0), "color": color})

    def _float_text(self, cell, text, color):
        x, y = self._cell_center(cell)
        self.floaters.append({"x": x, "y": y - 12, "text": text, "color": color,
                              "font": (MONO_FONT, 16, "bold"), "t0": time.perf_counter(),
                              "dur": 0.8, "rise": 34})

    def _float_center(self, text, color):
        self.floaters.append({"x": CANVAS_W / 2, "y": CANVAS_H / 2, "text": text,
                              "color": color, "font": (UI_FONT, 34, "bold"),
                              "t0": time.perf_counter(), "dur": 1.2, "rise": 40})

    # ----------------------------------------------------------- render loop
    def _frame(self):
        now = time.perf_counter()
        dt = min(0.1, now - self.last_frame)
        self.last_frame = now
        c = self.canvas
        c.delete("dyn")

        if self.state in ("menu", "howto"):
            self._draw_demo_snake(now)
        else:
            self._draw_food(now)
            self._draw_snake(now)
        self._draw_particles(now, dt)
        self._draw_floaters(now)

        if self.state == "menu":  # pulsing title glow
            pulse = 0.5 + 0.5 * math.sin(now * 2.4)
            c.itemconfig("title_glow", fill=mix(SECONDARY, BG, 0.75 - 0.3 * pulse))

        if (self.state == "gameover" and not self.gameover_built
                and now - self.death_time > DEATH_ANIM_SECONDS):
            self.gameover_built = True
            self._build_gameover_overlay()

        c.tag_raise("ov")  # overlays always above the animated layer
        if not self.closing:
            self.frame_id = self.root.after(FRAME_MS, self._frame)

    def _draw_eyes(self, cx, cy, dx, dy, scale=1.0):
        c = self.canvas
        px, py = -dy, dx
        for side in (-1, 1):
            ex = cx + dx * CELL * 0.16 * scale + px * side * CELL * 0.2 * scale
            ey = cy + dy * CELL * 0.16 * scale + py * side * CELL * 0.2 * scale
            er = CELL * 0.15 * scale
            c.create_oval(ex - er, ey - er, ex + er, ey + er, fill="white", outline="", tags="dyn")
            pr = CELL * 0.075 * scale
            qx, qy = ex + dx * er * 0.35, ey + dy * er * 0.35
            c.create_oval(qx - pr, qy - pr, qx + pr, qy + pr, fill=BG, outline="", tags="dyn")

    def _draw_snake(self, now):
        c = self.canvas
        snake = self.logic.snake
        n = len(snake)
        dead = self.state == "gameover"
        since_death = now - self.death_time
        flash = dead and since_death < DEATH_ANIM_SECONDS and int(since_death / 0.1) % 2 == 0

        centers = [self._cell_center(cell) for cell in snake]
        colors = []
        for i in range(n):
            color = mix(SNAKE_HEAD, SNAKE_TAIL, i / max(1, n - 1))
            if dead:
                color = mix(color, DANGER, 0.85) if flash else mix(color, BOARD_BG, 0.5)
            colors.append(color)

        if not dead:  # glow pass
            for (x, y), color in zip(centers, colors):
                r = CELL / 2 + 4
                c.create_oval(x - r, y - r, x + r, y + r,
                              fill=mix(color, BOARD_BG, 0.84), outline="", tags="dyn")

        half_link = CELL * 0.30
        for i in range(n - 1, -1, -1):  # tail first so the head ends up on top
            x, y = centers[i]
            if i > 0:  # connector between this bead and the next one toward the tail-end
                px, py = centers[i - 1]
                c.create_rectangle(min(x, px) - half_link, min(y, py) - half_link,
                                   max(x, px) + half_link, max(y, py) + half_link,
                                   fill=colors[i], outline="", tags="dyn")
            taper = 1 - 0.25 * (i / max(1, n - 1))
            r = (CELL / 2 - 2) * taper if i else CELL / 2 - 1
            c.create_oval(x - r, y - r, x + r, y + r, fill=colors[i],
                          outline=mix(colors[i], "#ffffff", 0.45) if i == 0 else "",
                          width=1, tags="dyn")
        dx, dy = self.logic.direction
        self._draw_eyes(centers[0][0], centers[0][1], dx, dy)

    def _draw_food(self, now):
        c = self.canvas
        logic = self.logic
        if logic.food:
            x, y = self._cell_center(logic.food)
            r = CELL * 0.27 + math.sin(now * 5) * CELL * 0.04
            draw_orb(c, x, y, r, ("dyn",))
        if logic.bonus and (logic.bonus_ticks > 12 or int(now * 8) % 2 == 0):
            x, y = self._cell_center(logic.bonus)
            r = CELL * 0.4 + math.sin(now * 7) * CELL * 0.03
            draw_star(c, x, y, r, now * 1.5, ("dyn",))
            frac = logic.bonus_ticks / BONUS_LIFETIME_TICKS
            ring = CELL * 0.58
            c.create_arc(x - ring, y - ring, x + ring, y + ring, start=90,
                         extent=max(1.0, 359.9 * frac), style="arc",
                         outline=GOLD, width=2, tags="dyn")

    def _draw_demo_snake(self, now):
        """Decorative snake gliding across the menu background."""
        c = self.canvas
        cx, cy = PAD + BOARD_W / 2, PAD + BOARD_H / 2
        ax, ay = BOARD_W * 0.38, BOARD_H * 0.32
        beads = []
        for k in range(18):
            t = now * 0.8 - k * 0.11
            beads.append((cx + ax * math.cos(t), cy + ay * math.sin(t * 1.5), t))
        colors = [mix(SNAKE_HEAD, SNAKE_TAIL, k / 17) for k in range(18)]
        for (x, y, _t), color in zip(beads, colors):
            r = CELL * 0.62
            c.create_oval(x - r, y - r, x + r, y + r, fill=mix(color, BOARD_BG, 0.85),
                          outline="", tags="dyn")
        for k in range(17, -1, -1):
            x, y, _t = beads[k]
            r = CELL * 0.45 * (1 - 0.3 * k / 17)
            c.create_oval(x - r, y - r, x + r, y + r, fill=colors[k], outline="", tags="dyn")
        x, y, t = beads[0]
        vx, vy = -ax * math.sin(t), ay * 1.5 * math.cos(t * 1.5)
        length = math.hypot(vx, vy) or 1
        self._draw_eyes(x, y, vx / length, vy / length)

    def _draw_particles(self, now, dt):
        c = self.canvas
        alive = []
        for p in self.particles:
            age = (now - p["t0"]) / p["life"]
            if age >= 1:
                continue
            p["x"] += p["vx"] * dt * 60
            p["y"] += p["vy"] * dt * 60
            r = max(0.5, p["size"] * (1 - age))
            c.create_oval(p["x"] - r, p["y"] - r, p["x"] + r, p["y"] + r,
                          fill=mix(p["color"], BOARD_BG, age), outline="", tags="dyn")
            alive.append(p)
        self.particles = alive

    def _draw_floaters(self, now):
        c = self.canvas
        alive = []
        for f in self.floaters:
            age = (now - f["t0"]) / f["dur"]
            if age >= 1:
                continue
            c.create_text(f["x"], f["y"] - f["rise"] * age, text=f["text"], font=f["font"],
                          fill=mix(f["color"], BOARD_BG, age ** 2), tags="dyn")
            alive.append(f)
        self.floaters = alive

    # ----------------------------------------------------------------- overlays
    def _clear_overlay(self):
        self.canvas.delete("ov")
        self.canvas.config(cursor="")

    def _backdrop(self, stipple="gray50"):
        self.canvas.create_rectangle(PAD, PAD, PAD + BOARD_W, PAD + BOARD_H, fill=BG,
                                     stipple=stipple, outline="", tags="ov")

    def _panel(self, cx, cy, w, h):
        c = self.canvas
        rounded_rect(c, cx - w / 2 + 6, cy - h / 2 + 8, cx + w / 2 + 6, cy + h / 2 + 8,
                     r=24, fill="#03050d", outline="", tags="ov")
        rounded_rect(c, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, r=24,
                     fill=PANEL, outline=BORDER, width=2, tags="ov")
        rounded_rect(c, cx - w / 2 + 8, cy - h / 2 + 8, cx + w / 2 - 8, cy + h / 2 - 8, r=18,
                     fill="", outline=mix(PRIMARY, PANEL, 0.8), width=1, tags="ov")

    def _text(self, x, y, text, font, fill, anchor="center", **kwargs):
        return self.canvas.create_text(x, y, text=text, font=font, fill=fill,
                                       anchor=anchor, tags="ov", **kwargs)

    def _button(self, x, y, text, command, primary=False, w=250, h=50):
        c = self.canvas
        self.btn_counter += 1
        tag = f"btn{self.btn_counter}"
        base = PRIMARY if primary else PANEL_HI
        hover = mix(PRIMARY, "#ffffff", 0.3) if primary else mix(PANEL_HI, PRIMARY, 0.35)
        pressed = mix(base, "#ffffff", 0.55 if primary else 0.2)
        outline = mix(PRIMARY, "#ffffff", 0.4) if primary else mix(PRIMARY, PANEL_HI, 0.45)
        rounded_rect(c, x - w / 2, y - h / 2 + 4, x + w / 2, y + h / 2 + 4, r=14,
                     fill="#04060f", outline="", tags="ov")
        body = rounded_rect(c, x - w / 2, y - h / 2, x + w / 2, y + h / 2, r=14,
                            fill=base, outline=outline, width=2, tags=("ov", tag))
        c.create_text(x, y, text=text, font=(UI_FONT, 14, "bold"),
                      fill=BG if primary else TEXT, tags=("ov", tag))

        def on_enter(_e):
            c.itemconfig(body, fill=hover)
            c.config(cursor="hand2")

        def on_leave(_e):
            c.itemconfig(body, fill=base)
            c.config(cursor="")

        def on_click(_e):
            c.itemconfig(body, fill=pressed)
            self.sound.play("click")
            self.root.after(70, command)  # tiny delay so the press flash is visible

        c.tag_bind(tag, "<Enter>", on_enter)
        c.tag_bind(tag, "<Leave>", on_leave)
        c.tag_bind(tag, "<Button-1>", on_click)

    def _build_menu_overlay(self):
        cx, cy = CANVAS_W / 2, CANVAS_H / 2
        self._backdrop("gray50")
        title_font = (UI_FONT, 84, "bold")
        for ox, oy in ((-4, 0), (4, 0), (0, -4), (0, 4), (-3, -3), (3, 3), (-3, 3), (3, -3)):
            self.canvas.create_text(cx + ox, cy - 120 + oy, text="SNAKE", font=title_font,
                                    fill=mix(SECONDARY, BG, 0.6), tags=("ov", "title_glow"))
        self._text(cx, cy - 120, "SNAKE", title_font, PRIMARY)
        self._text(cx, cy - 55, "HOW LONG CAN YOU SURVIVE?", (UI_FONT, 14, "bold"), TEXT_DIM)
        self._text(cx, cy - 26, f"BEST  {self.high_score:06d}", (MONO_FONT, 13, "bold"), GOLD)
        self._button(cx, cy + 28, "PLAY", self.start_game, primary=True)
        self._button(cx, cy + 92, "HOW TO PLAY", self.show_how_to_play)
        self._button(cx, cy + 156, "QUIT", self.quit_game)
        self._text(cx, PAD + BOARD_H - 22,
                   "ARROWS / WASD  steer      SPACE  pause      M  sound",
                   (UI_FONT, 10, "bold"), MUTED)

    def _build_how_overlay(self):
        c = self.canvas
        cx, cy = CANVAS_W / 2, CANVAS_H / 2
        w, h = 640, 420
        top = cy - h / 2
        self._backdrop("gray75")
        self._panel(cx, cy, w, h)
        self._text(cx, top + 44, "HOW TO PLAY", (UI_FONT, 28, "bold"), PRIMARY)

        y = top + 104
        for keys, desc in (("ARROWS / WASD", "Steer the snake"),
                           ("SPACE / ESC", "Pause or resume"),
                           ("M", "Toggle sound")):
            self._text(cx - 280, y, keys, (MONO_FONT, 13, "bold"), GOLD, anchor="w")
            self._text(cx - 40, y, desc, (UI_FONT, 13), TEXT, anchor="w")
            y += 38
        draw_orb(c, cx - 262, y, 8, ("ov",))
        self._text(cx - 240, y, "ENERGY ORB", (MONO_FONT, 13, "bold"), ACCENT, anchor="w")
        self._text(cx - 40, y, f"+{FOOD_POINTS} points, snake grows", (UI_FONT, 13), TEXT, anchor="w")
        y += 38
        draw_star(c, cx - 262, y, 10, 0.3, ("ov",))
        self._text(cx - 240, y, "GOLD STAR", (MONO_FONT, 13, "bold"), GOLD, anchor="w")
        self._text(cx - 40, y, f"+{BONUS_POINTS} bonus - grab it before it fades", (UI_FONT, 13),
                   TEXT, anchor="w")
        self._text(cx, top + h - 105,
                   f"Speed climbs every {FOODS_PER_LEVEL} orbs.\nHitting a wall or your own tail ends the run.",
                   (UI_FONT, 11), TEXT_DIM, justify="center")
        self._button(cx, top + h - 48, "BACK", self.show_menu, primary=True, w=200, h=46)

    def _build_pause_overlay(self):
        cx, cy = CANVAS_W / 2, CANVAS_H / 2
        w, h = 380, 360
        top = cy - h / 2
        self._backdrop("gray50")
        self._panel(cx, cy, w, h)
        self._text(cx, top + 52, "PAUSED", (UI_FONT, 38, "bold"), PRIMARY)
        self._text(cx, top + 92, "TAKE A BREATH", (UI_FONT, 10, "bold"), MUTED)
        self._button(cx, top + 150, "RESUME", self.resume_game, primary=True)
        self._button(cx, top + 214, "RESTART", self.restart_game)
        self._button(cx, top + 278, "MAIN MENU", self.show_menu)

    def _build_gameover_overlay(self):
        cx, cy = CANVAS_W / 2, CANVAS_H / 2
        w, h = 420, 470
        top = cy - h / 2
        self._backdrop("gray50")
        self._panel(cx, cy, w, h)
        title = "YOU WIN!" if self.logic.won else "GAME OVER"
        self._text(cx, top + 52, title, (UI_FONT, 36, "bold"), ACCENT if not self.logic.won else PRIMARY)
        self._text(cx, top + 106, "YOUR SCORE", (UI_FONT, 10, "bold"), MUTED)
        self._text(cx, top + 146, f"{self.logic.score:06d}", (MONO_FONT, 46, "bold"), TEXT)
        self._text(cx, top + 200, "BEST SCORE", (UI_FONT, 10, "bold"), MUTED)
        self._text(cx, top + 230, f"{self.high_score:06d}", (MONO_FONT, 26, "bold"), GOLD)
        self._text(cx, top + 266, f"LEVEL REACHED  {self.logic.level}", (UI_FONT, 11, "bold"), TEXT_DIM)
        if self.new_best:
            self._text(cx, top + 294, "\u2605  NEW BEST!  \u2605", (UI_FONT, 14, "bold"), GOLD)
        self._button(cx, top + 350, "PLAY AGAIN", self.start_game, primary=True)
        self._button(cx, top + 414, "MAIN MENU", self.show_menu)


# =============================================================================
def main():
    root = tk.Tk()
    SnakeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
