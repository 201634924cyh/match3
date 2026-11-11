#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""消消乐 Match-3 —— pygame 单文件实现，零外部素材。

玩法
    交换相邻的两颗宝石，让三颗及以上同色宝石连成横线或竖线即可消除。
    消除后上方的宝石下落、顶部补充新宝石，如果又连成线就触发连锁，连锁越多倍率越高。
    限时 90 秒，时间到了按累计得分结算。

操作
    鼠标左键     点击选中，再点相邻格交换
    鼠标拖拽     按住一颗宝石往相邻方向拖，松手即交换
    空格         暂停 / 继续
    R            重新开始
    H            手动请求一次提示
    Esc          退出

依赖
    pygame      必需
    numpy       可选，用于合成音效；没装则自动静音

设计说明
    逻辑层（棋盘、匹配、下落、计分）全部写成不依赖渲染的纯函数，
    Game 类只维护状态机，所有绘制都在 draw_* 函数里。这样 selftest.py
    可以在无窗口（SDL_VIDEODRIVER=dummy）环境下跑完整对局。
"""

import math
import os
import random
import sys

import pygame

try:
    import numpy as np

    HAVE_NUMPY = True
except ImportError:  # 没装 numpy 就静音，不影响玩
    np = None
    HAVE_NUMPY = False


# ---------------------------------------------------------------- 布局常量

GRID = 8                       # 棋盘 8x8
TILE = 68                      # 单格边长
BOARD_W = GRID * TILE          # 544
BOARD_X = 56
BOARD_Y = 136
WIDTH = BOARD_W + BOARD_X * 2          # 656
HEIGHT = BOARD_Y + BOARD_W + 92        # 772

FPS = 60
ROUND_TIME = 90.0              # 单局时长（秒）
GEM_KINDS = 6                  # 宝石种类

SWAP_TIME = 0.16               # 交换动画时长
SWAP_BACK_TIME = 0.14          # 交换失败回退动画
CLEAR_TIME = 0.26              # 消除动画时长
FALL_TIME_PER_CELL = 0.055     # 每下落一格的耗时
FALL_TIME_MAX = 0.42           # 下落动画时长上限
FLOAT_TIME = 0.85              # 飘字存活时间
HINT_DELAY = 5.0               # 闲置多久后给提示

# 状态机
ST_IDLE = "idle"
ST_SWAP = "swap"
ST_SWAP_BACK = "swap_back"
ST_CLEAR = "clear"
ST_FALL = "fall"
ST_PAUSED = "paused"
ST_OVER = "over"


# ---------------------------------------------------------------- 配色

BG_TOP = (16, 18, 30)
BG_BOTTOM = (28, 24, 44)
PANEL = (38, 42, 64)
PANEL_EDGE = (58, 64, 96)
SLOT = (44, 49, 74)
SLOT_EDGE = (58, 64, 96)
TEXT_MAIN = (238, 240, 250)
TEXT_DIM = (148, 156, 184)
ACCENT = (255, 206, 92)

GEM_COLORS = [
    (232, 74, 88),      # 0 红
    (72, 148, 232),     # 1 蓝
    (78, 200, 130),     # 2 绿
    (245, 200, 72),     # 3 黄
    (168, 110, 232),    # 4 紫
    (245, 146, 70),     # 5 橙
]

GEM_DARK = [tuple(int(v * 0.55) for v in c) for c in GEM_COLORS]
GEM_LIGHT = [tuple(min(255, int(v * 1.35) + 40) for v in c) for c in GEM_COLORS]


# ---------------------------------------------------------------- 音效

SAMPLE_RATE = 44100


def _tone(freq, dur, volume=0.28, kind="sine", decay=6.0, freq_end=None):
    """合成一个短音，返回 numpy int16 立体声数组。freq_end 不为空时做滑音。"""
    n = int(SAMPLE_RATE * dur)
    if n <= 0:
        return None
    t = np.linspace(0.0, dur, n, endpoint=False)
    if freq_end is None:
        phase = 2.0 * math.pi * freq * t
    else:
        # 线性扫频，相位是频率的积分
        f = freq + (freq_end - freq) * (t / dur)
        phase = 2.0 * math.pi * np.cumsum(f) / SAMPLE_RATE
    if kind == "sine":
        wave = np.sin(phase)
    elif kind == "square":
        wave = np.sign(np.sin(phase)) * 0.55
    elif kind == "tri":
        wave = 2.0 * np.abs(2.0 * ((phase / (2 * math.pi)) % 1.0) - 1.0) - 1.0
    else:
        wave = np.sin(phase)

    env = np.exp(-decay * t)
    # 头尾各做一小段淡入淡出，避免爆音
    fade = max(1, int(SAMPLE_RATE * 0.004))
    env[:fade] *= np.linspace(0.0, 1.0, fade)
    env[-fade:] *= np.linspace(1.0, 0.0, fade)

    data = (wave * env * volume * 32767).astype(np.int16)
    return np.column_stack([data, data])


class SoundBank:
    """负责合成并缓存所有音效；任何一步失败都降级为静音，绝不中断游戏。"""

    def __init__(self):
        self.ok = False
        self.sounds = {}
        if not HAVE_NUMPY:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=2, buffer=512)
            self.ok = True
        except pygame.error:
            self.ok = False
            return
        try:
            self._build()
        except Exception:
            self.ok = False

    def _make(self, name, arr):
        if arr is None:
            return
        try:
            self.sounds[name] = pygame.sndarray.make_sound(arr)
        except (pygame.error, ValueError):
            pass

    def _build(self):
        self._make("select", _tone(660, 0.05, 0.16, "sine", decay=14))
        self._make("swap", _tone(880, 0.07, 0.20, "tri", decay=12))
        self._make("bad", _tone(190, 0.14, 0.22, "square", decay=9))
        # 连锁时逐级升调
        for i in range(1, 9):
            f = 523.25 * (1.1225 ** (i - 1))
            self._make("match%d" % i, _tone(f, 0.20, 0.24, "sine", decay=7))
        self._make("fall", _tone(320, 0.10, 0.13, "tri", decay=11))
        self._make("over", _tone(440, 0.75, 0.26, "sine", decay=2.4, freq_end=130))
        self._make("hint", _tone(1046, 0.09, 0.14, "sine", decay=13))
        self._make("shuffle", _tone(300, 0.30, 0.18, "tri", decay=4, freq_end=560))

    def play(self, name):
        if not self.ok:
            return
        snd = self.sounds.get(name)
        if snd is not None:
            try:
                snd.play()
            except pygame.error:
                pass

    def match(self, combo):
        idx = min(max(combo, 1), 8)
        self.play("match%d" % idx)


# ---------------------------------------------------------------- 纯逻辑层
# 这一层完全不知道 pygame 的存在，方便无窗口自检。


def in_bounds(r, c):
    return 0 <= r < GRID and 0 <= c < GRID


def are_adjacent(a, b):
    """判断两个格子是否四邻接。"""
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1


def swap_cells(board, a, b):
    """原地交换两个格子的内容。"""
    board[a[0]][a[1]], board[b[0]][b[1]] = board[b[0]][b[1]], board[a[0]][a[1]]


def find_matches(board):
    """扫描棋盘，返回所有应消除格子的坐标集合。空格（None）不参与匹配。"""
    hit = set()

    for r in range(GRID):
        run = 1
        for c in range(1, GRID):
            same = board[r][c] is not None and board[r][c] == board[r][c - 1]
            if same:
                run += 1
            else:
                if run >= 3:
                    for k in range(c - run, c):
                        hit.add((r, k))
                run = 1
        if run >= 3:
            for k in range(GRID - run, GRID):
                hit.add((r, k))

    for c in range(GRID):
        run = 1
        for r in range(1, GRID):
            same = board[r][c] is not None and board[r][c] == board[r - 1][c]
            if same:
                run += 1
            else:
                if run >= 3:
                    for k in range(r - run, r):
                        hit.add((k, c))
                run = 1
        if run >= 3:
            for k in range(GRID - run, GRID):
                hit.add((k, c))

    return hit


def find_hint(board):
    """找一个能形成消除的相邻交换，返回 (a, b)；没有可行交换时返回 None。"""
    for r in range(GRID):
        for c in range(GRID):
            for dr, dc in ((0, 1), (1, 0)):
                r2, c2 = r + dr, c + dc
                if not in_bounds(r2, c2):
                    continue
                swap_cells(board, (r, c), (r2, c2))
                ok = bool(find_matches(board))
                swap_cells(board, (r, c), (r2, c2))
                if ok:
                    return (r, c), (r2, c2)
    return None


def has_possible_move(board):
    """棋盘上是否还存在至少一步可消除的交换。"""
    return find_hint(board) is not None


def make_board(rng):
    """生成一个开局既没有现成三连、又保证有解可走的棋盘。"""
    for _ in range(400):
        board = [[rng.randrange(GEM_KINDS) for _ in range(GRID)] for _ in range(GRID)]
        if find_matches(board):
            continue
        if has_possible_move(board):
            return board
    # 极端情况下的兜底：先给个规则棋盘再洗
    board = [[(r * 2 + c) % GEM_KINDS for c in range(GRID)] for r in range(GRID)]
    return board


def score_for(count, combo):
    """计算一次消除的得分。count 为消除数量，combo 从 1 开始。"""
    base = count * 10
    if count >= 5:
        base += 50
    elif count == 4:
        base += 20
    mult = 1.0 + 0.5 * max(0, combo - 1)
    return int(round(base * mult))


def collapse(board, offsets, rng):
    """执行下落与补充。

    把每列的非空格子压到底部，顶部用新宝石填充；同时把每个被移动格子的
    offsets 设成一个负值（视觉上位于目标位置上方），由动画逐帧归零。
    返回本次最大下落格数，用于换算动画时长。
    """
    max_fall = 0

    for c in range(GRID):
        write = GRID - 1
        for r in range(GRID - 1, -1, -1):
            if board[r][c] is not None:
                if write != r:
                    board[write][c] = board[r][c]
                    board[r][c] = None
                    drop = write - r
                    offsets[write][c] = -drop * TILE
                    if drop > max_fall:
                        max_fall = drop
                write -= 1

        empty = write + 1
        if empty <= 0:
            continue
        for r in range(empty):
            board[r][c] = rng.randrange(GEM_KINDS)
            offsets[r][c] = -empty * TILE
        if empty > max_fall:
            max_fall = empty

    return max_fall


def cell_at_pixel(px, py):
    """把屏幕坐标换算成格子坐标，落在棋盘外返回 None。"""
    if px < BOARD_X or py < BOARD_Y:
        return None
    c = (px - BOARD_X) // TILE
    r = (py - BOARD_Y) // TILE
    if 0 <= r < GRID and 0 <= c < GRID:
        return int(r), int(c)
    return None


# ---------------------------------------------------------------- 游戏状态机


class Game:
    """只维护状态与数值，不持有任何 Surface，方便自检里跑整局模拟。"""

    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.sounds = None
        self.reset()

    def reset(self):
        self.board = make_board(self.rng)
        self.offsets = [[0] * GRID for _ in range(GRID)]
        self.score = 0
        self.combo = 0
        self.best_combo = 0
        self.time_left = ROUND_TIME
        self.state = ST_IDLE

        self.selected = None
        self.swap_pair = None
        self.swap_t = 0.0
        self.clear_set = set()
        self.clear_t = 0.0
        self.fall_t = 0.0
        self.fall_dur = 0.0

        self.floats = []          # 飘字 [{text,x,y,t,life,color,size}]
        self.hint = None
        self.hint_timer = 0.0
        self.shake = 0.0          # 无效交换时的轻微抖动
        self.moves = 0
        self.cleared_total = 0
        self.shuffles = 0
        self.over_reason = ""

    # -- 音效挂载 --------------------------------------------------

    def attach_sounds(self, bank):
        self.sounds = bank

    def _sfx(self, name):
        if self.sounds is not None:
            self.sounds.play(name)

    # -- 外部操作 --------------------------------------------------

    def try_select(self, cell):
        """点击某个格子。返回 True 表示触发了交换。"""
        if self.state != ST_IDLE or self.time_left <= 0 or cell is None:
            return False

        if self.selected is None:
            self.selected = cell
            self.hint = None
            self.hint_timer = 0.0
            self._sfx("select")
            return False

        if cell == self.selected:
            self.selected = None
            return False

        if are_adjacent(self.selected, cell):
            a, b = self.selected, cell
            self.selected = None
            return self.begin_swap(a, b)

        self.selected = cell
        self.hint = None
        self._sfx("select")
        return False

    def try_drag(self, start, target):
        """从 start 往相邻的 target 拖。"""
        if self.state != ST_IDLE or self.time_left <= 0:
            return False
        if start is None or target is None or not are_adjacent(start, target):
            return False
        self.selected = None
        return self.begin_swap(start, target)

    def begin_swap(self, a, b):
        """发起一次交换。非 IDLE 或时间已到会被拒绝，返回布尔值。

        try_select / try_drag 在外层已经拦了一道，这里再拦一道是防止
        有人绕过用户操作路径直接调用，把已经结束的局继续往下推。
        """
        if self.state != ST_IDLE or self.time_left <= 0.0:
            return False
        if not are_adjacent(a, b):
            return False
        self.swap_pair = (a, b)
        self.swap_t = 0.0
        self.state = ST_SWAP
        self.hint = None
        self.hint_timer = 0.0
        self._sfx("swap")
        return True

    def request_hint(self):
        if self.state in (ST_IDLE, ST_PAUSED):
            self.hint = find_hint(self.board)
            if self.hint:
                self._sfx("hint")
                return True
        return False

    def toggle_pause(self):
        if self.state == ST_PAUSED:
            self.state = ST_IDLE
        elif self.state == ST_IDLE:
            self.state = ST_PAUSED

    # -- 主循环 ----------------------------------------------------

    def update(self, dt):
        """推进状态机。dt 单位为秒。"""
        if self.state in (ST_PAUSED, ST_OVER):
            self._update_floats(dt)
            return

        # 计时器在所有进行中的状态里都走时。若只在 ST_IDLE 里扣，
        # 交换/消除/下落的动画时间就等于白送，连锁越长赚得越多。
        self.time_left = max(0.0, self.time_left - dt)

        if self.state == ST_IDLE:
            if self.time_left <= 0.0:
                # 到点就直接结算；动画不会被拦腰截断，因为只有 IDLE 才走到这里
                self.finish("时间到")
                self._update_floats(dt)
                return
            self.hint_timer += dt
            if self.hint_timer >= HINT_DELAY and self.hint is None:
                self.hint = find_hint(self.board)
            self._update_floats(dt)
            return

        if self.state == ST_SWAP:
            self.swap_t += dt
            if self.swap_t >= SWAP_TIME:
                a, b = self.swap_pair
                swap_cells(self.board, a, b)
                self.moves += 1
                hit = find_matches(self.board)
                if hit:
                    self.combo = 1
                    self.clear_set = hit
                    self.clear_t = 0.0
                    self.state = ST_CLEAR
                else:
                    self.state = ST_SWAP_BACK
                    self.swap_t = 0.0
                    self.shake = 0.18
                    self._sfx("bad")
            self._update_floats(dt)
            return

        if self.state == ST_SWAP_BACK:
            self.swap_t += dt
            if self.swap_t >= SWAP_BACK_TIME:
                a, b = self.swap_pair
                swap_cells(self.board, a, b)
                self.swap_pair = None
                self.state = ST_IDLE
                self.hint_timer = 0.0
            self._update_floats(dt)
            return

        if self.state == ST_CLEAR:
            self.clear_t += dt
            if self.clear_t >= CLEAR_TIME:
                self._resolve_clear()
            self._update_floats(dt)
            return

        if self.state == ST_FALL:
            self.fall_t += dt
            if self.fall_t >= self.fall_dur:
                self._settle_offsets()
                hit = find_matches(self.board)
                if hit:
                    self.combo += 1
                    if self.combo > self.best_combo:
                        self.best_combo = self.combo
                    self.clear_set = hit
                    self.clear_t = 0.0
                    self.state = ST_CLEAR
                    if self.sounds is not None:
                        self.sounds.match(self.combo)
                else:
                    self.combo = 0
                    self.state = ST_IDLE
                    self.hint_timer = 0.0
                    self._ensure_playable()
            self._update_floats(dt)
            return

    def _update_floats(self, dt):
        if not self.floats:
            return
        alive = []
        for f in self.floats:
            f["t"] += dt
            if f["t"] < f["life"]:
                alive.append(f)
        self.floats = alive
        if self.shake > 0:
            self.shake = max(0.0, self.shake - dt)

    def _resolve_clear(self):
        count = len(self.clear_set)
        gained = score_for(count, self.combo)
        self.score += gained
        self.cleared_total += count

        # 消除位置的中心点，用来放飘字
        if self.clear_set:
            rs = [p[0] for p in self.clear_set]
            cs = [p[1] for p in self.clear_set]
            cx = BOARD_X + (min(cs) + max(cs) + 1) * TILE / 2
            cy = BOARD_Y + (min(rs) + max(rs) + 1) * TILE / 2
            self.floats.append({
                "text": "+%d" % gained,
                "x": cx, "y": cy,
                "t": 0.0, "life": FLOAT_TIME,
                "color": ACCENT, "size": 26,
            })
            if self.combo >= 2:
                self.floats.append({
                    "text": "连击 x%d" % self.combo,
                    "x": cx, "y": cy - 34,
                    "t": 0.0, "life": FLOAT_TIME,
                    "color": (255, 150, 200), "size": 22,
                })

        if self.sounds is not None:
            self.sounds.match(self.combo)

        for (r, c) in self.clear_set:
            self.board[r][c] = None
        self.clear_set = set()

        fall = collapse(self.board, self.offsets, self.rng)
        self.fall_dur = min(FALL_TIME_MAX, max(0.06, fall * FALL_TIME_PER_CELL))
        self.fall_t = 0.0
        self.state = ST_FALL
        self._sfx("fall")

    def _settle_offsets(self):
        for r in range(GRID):
            for c in range(GRID):
                self.offsets[r][c] = 0

    def _ensure_playable(self):
        """如果棋盘死锁就重排，直到有解。"""
        guard = 0
        while not has_possible_move(self.board) and guard < 30:
            guard += 1
            self.shuffles += 1
            flat = []
            for r in range(GRID):
                for c in range(GRID):
                    flat.append(self.board[r][c])
            self.rng.shuffle(flat)
            i = 0
            for r in range(GRID):
                for c in range(GRID):
                    self.board[r][c] = flat[i]
                    i += 1
            if find_matches(self.board):
                # 洗出来的局面自带三连，先清掉再判断
                for (rr, cc) in find_matches(self.board):
                    self.board[rr][cc] = self.rng.randrange(GEM_KINDS)
        self._sfx("shuffle")

    def finish(self, reason="本局结束"):
        self.state = ST_OVER
        self.over_reason = reason
        self.selected = None
        self._sfx("over")

    # -- 供渲染层读取的派生数据 -------------------------------------

    def swap_progress(self):
        if self.state == ST_SWAP:
            return min(1.0, self.swap_t / SWAP_TIME)
        if self.state == ST_SWAP_BACK:
            return min(1.0, self.swap_t / SWAP_BACK_TIME)
        return 0.0

    def clear_progress(self):
        if self.state == ST_CLEAR:
            return min(1.0, self.clear_t / CLEAR_TIME)
        return 0.0

    def fall_progress(self):
        if self.state == ST_FALL and self.fall_dur > 0:
            return min(1.0, self.fall_t / self.fall_dur)
        return 1.0

    def time_ratio(self):
        return max(0.0, min(1.0, self.time_left / ROUND_TIME))


# ---------------------------------------------------------------- 绘制资源

_FONT_CACHE = {}
_GEM_CACHE = {}


def load_font(size, bold=False):
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    font = None
    for path in candidates:
        if path and os.path.exists(path):
            try:
                font = pygame.font.Font(path, size)
                break
            except (pygame.error, OSError):
                continue
    if font is None:
        try:
            font = pygame.font.SysFont("microsoftyaheui,simhei,notosanscjksc,arial", size, bold=bold)
        except Exception:
            font = pygame.font.Font(None, size)
    _FONT_CACHE[key] = font
    return font


def _polygon_points(cx, cy, radius, sides, rotation=-math.pi / 2):
    pts = []
    for i in range(sides):
        ang = rotation + 2 * math.pi * i / sides
        pts.append((cx + radius * math.cos(ang), cy + radius * math.sin(ang)))
    return pts


def _star_points(cx, cy, outer, inner, points=5, rotation=-math.pi / 2):
    pts = []
    for i in range(points * 2):
        rad = outer if i % 2 == 0 else inner
        ang = rotation + math.pi * i / points
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    return pts


def build_gem_surface(kind, size):
    """预渲染一颗宝石。用 2 倍超采样再缩小，得到平滑边缘。"""
    cache_key = (kind, size)
    if cache_key in _GEM_CACHE:
        return _GEM_CACHE[cache_key]

    ss = 2
    big = size * ss
    surf = pygame.Surface((big, big), pygame.SRCALPHA)
    cx = cy = big / 2.0
    radius = big * 0.42
    base = GEM_COLORS[kind % len(GEM_COLORS)]
    light = GEM_LIGHT[kind % len(GEM_LIGHT)]
    dark = GEM_DARK[kind % len(GEM_DARK)]

    # 落地阴影
    shadow = pygame.Surface((big, big), pygame.SRCALPHA)
    pygame.draw.circle(shadow, (0, 0, 0, 70), (int(cx), int(cy + big * 0.05)), int(radius * 0.98))
    surf.blit(shadow, (0, 0))

    if kind == 0:            # 圆
        pygame.draw.circle(surf, base, (int(cx), int(cy)), int(radius))
        pygame.draw.circle(surf, dark, (int(cx), int(cy)), int(radius), max(1, int(big * 0.035)))
    elif kind == 1:          # 圆角方
        rect = pygame.Rect(0, 0, int(radius * 1.72), int(radius * 1.72))
        rect.center = (int(cx), int(cy))
        pygame.draw.rect(surf, base, rect, border_radius=int(radius * 0.34))
        pygame.draw.rect(surf, dark, rect, max(1, int(big * 0.035)), border_radius=int(radius * 0.34))
    elif kind == 2:          # 正三角
        pts = _polygon_points(cx, cy + radius * 0.12, radius * 1.12, 3)
        pygame.draw.polygon(surf, base, pts)
        pygame.draw.polygon(surf, dark, pts, max(1, int(big * 0.035)))
    elif kind == 3:          # 菱形
        pts = [(cx, cy - radius * 1.08), (cx + radius * 0.92, cy),
               (cx, cy + radius * 1.08), (cx - radius * 0.92, cy)]
        pygame.draw.polygon(surf, base, pts)
        pygame.draw.polygon(surf, dark, pts, max(1, int(big * 0.035)))
    elif kind == 4:          # 六边形
        pts = _polygon_points(cx, cy, radius * 1.02, 6)
        pygame.draw.polygon(surf, base, pts)
        pygame.draw.polygon(surf, dark, pts, max(1, int(big * 0.035)))
    else:                    # 五角星
        pts = _star_points(cx, cy, radius * 1.12, radius * 0.50)
        pygame.draw.polygon(surf, base, pts)
        pygame.draw.polygon(surf, dark, pts, max(1, int(big * 0.03)))

    # 左上高光
    hl = pygame.Surface((big, big), pygame.SRCALPHA)
    pygame.draw.ellipse(hl, (255, 255, 255, 96),
                        (int(cx - radius * 0.62), int(cy - radius * 0.86),
                         int(radius * 0.66), int(radius * 0.44)))
    surf.blit(hl, (0, 0))

    # 右下压暗，增强立体感
    shade = pygame.Surface((big, big), pygame.SRCALPHA)
    pygame.draw.ellipse(shade, (*dark, 60),
                        (int(cx - radius * 0.30), int(cy + radius * 0.26),
                         int(radius * 0.80), int(radius * 0.50)))
    surf.blit(shade, (0, 0))

    if ss != 1:
        surf = pygame.transform.smoothscale(surf, (size, size))

    _GEM_CACHE[cache_key] = surf
    return surf


def make_background(size):
    """纵向渐变背景，只在启动时算一次。"""
    w, h = size
    surf = pygame.Surface((1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        col = (
            int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
            int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
            int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t),
        )
        surf.set_at((0, y), col)
    return pygame.transform.scale(surf, (w, h))


# ---------------------------------------------------------------- 绘制


def draw_board(surface, game, bg):
    surface.blit(bg, (0, 0))

    offset_x = 0
    offset_y = 0
    if game.shake > 0:
        amp = game.shake * 14
        offset_x = int(math.sin(game.shake * 90) * amp)
        offset_y = int(math.cos(game.shake * 77) * amp * 0.5)

    board_rect = pygame.Rect(BOARD_X - 8 + offset_x, BOARD_Y - 8 + offset_y, BOARD_W + 16, BOARD_W + 16)
    panel = pygame.Surface(board_rect.size, pygame.SRCALPHA)
    pygame.draw.rect(panel, (*PANEL, 220), panel.get_rect(), border_radius=18)
    pygame.draw.rect(panel, PANEL_EDGE, panel.get_rect(), 2, border_radius=18)
    surface.blit(panel, board_rect.topleft)

    # 格子槽位
    for r in range(GRID):
        for c in range(GRID):
            rect = pygame.Rect(
                BOARD_X + c * TILE + offset_x + 4,
                BOARD_Y + r * TILE + offset_y + 4,
                TILE - 8, TILE - 8,
            )
            shade = SLOT if (r + c) % 2 == 0 else (int(SLOT[0] * 0.92), int(SLOT[1] * 0.92), int(SLOT[2] * 0.92))
            pygame.draw.rect(surface, shade, rect, border_radius=12)

    # 提示
    if game.hint and game.state in (ST_IDLE, ST_PAUSED):
        for (r, c) in game.hint:
            rect = pygame.Rect(
                BOARD_X + c * TILE + offset_x + 3,
                BOARD_Y + r * TILE + offset_y + 3,
                TILE - 6, TILE - 6,
            )
            pygame.draw.rect(surface, ACCENT, rect, 3, border_radius=12)

    # 选中框
    if game.selected is not None:
        r, c = game.selected
        rect = pygame.Rect(
            BOARD_X + c * TILE + offset_x + 2,
            BOARD_Y + r * TILE + offset_y + 2,
            TILE - 4, TILE - 4,
        )
        pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 160.0)
        col = (int(255 * (0.7 + 0.3 * pulse)), int(214 * (0.7 + 0.3 * pulse)), int(120 * (0.7 + 0.3 * pulse)))
        pygame.draw.rect(surface, col, rect, 3, border_radius=12)

    # 宝石
    swap = game.swap_pair
    sp = game.swap_progress()
    clear_p = game.clear_progress()
    fall_p = game.fall_progress()

    for r in range(GRID):
        for c in range(GRID):
            kind = game.board[r][c]
            if kind is None:
                continue

            x = BOARD_X + c * TILE + offset_x
            y = BOARD_Y + r * TILE + offset_y

            # 交换动画：两块同时沿直线平移
            if swap is not None and game.state in (ST_SWAP, ST_SWAP_BACK):
                a, b = swap
                if (r, c) == a:
                    tr, tc = b
                    x += (tc - c) * TILE * sp
                    y += (tr - r) * TILE * sp
                elif (r, c) == b:
                    tr, tc = a
                    x += (tc - c) * TILE * sp
                    y += (tr - r) * TILE * sp

            # 下落动画
            if game.state == ST_FALL and game.offsets[r][c] != 0:
                y += game.offsets[r][c] * (1.0 - fall_p)

            scale = 1.0
            alpha = 255
            if game.state == ST_CLEAR and (r, c) in game.clear_set:
                # 先轻微放大再缩没
                if clear_p < 0.35:
                    scale = 1.0 + 0.30 * (clear_p / 0.35)
                else:
                    k = (clear_p - 0.35) / 0.65
                    scale = max(0.0, 1.30 * (1.0 - k))
                alpha = int(255 * max(0.0, 1.0 - clear_p ** 1.4))

            if scale <= 0.02:
                continue

            size = max(2, int(TILE * 0.94 * scale))
            gem = build_gem_surface(kind, size)
            if alpha < 255:
                gem = gem.copy()
                gem.set_alpha(alpha)
            gx = x + (TILE - size) / 2
            gy = y + (TILE - size) / 2
            surface.blit(gem, (int(gx), int(gy)))


def draw_ui(surface, game):
    font_big = load_font(34, bold=True)
    font_mid = load_font(20)
    font_small = load_font(16)

    title = font_big.render("消消乐", True, TEXT_MAIN)
    surface.blit(title, (BOARD_X, 20))

    score_txt = font_mid.render("得分", True, TEXT_DIM)
    score_val = font_big.render(str(game.score), True, ACCENT)
    surface.blit(score_txt, (BOARD_X + 150, 24))
    surface.blit(score_val, (BOARD_X + 150, 46))

    # 时间条
    bar_x = BOARD_X + 300
    bar_w = BOARD_W - 300
    bar_rect = pygame.Rect(bar_x, 52, bar_w, 16)
    pygame.draw.rect(surface, (52, 56, 80), bar_rect, border_radius=8)
    frac = game.time_ratio()
    if frac > 0:
        col = (78, 200, 130) if frac > 0.35 else ((245, 200, 72) if frac > 0.15 else (232, 74, 88))
        pygame.draw.rect(surface, col, pygame.Rect(bar_x, 52, max(4, int(bar_w * frac)), 16), border_radius=8)
    pygame.draw.rect(surface, PANEL_EDGE, bar_rect, 1, border_radius=8)

    time_txt = font_mid.render("%.1f s" % max(0.0, game.time_left), True, TEXT_MAIN)
    surface.blit(time_txt, (bar_x, 22))

    # 底部两行：统计一行、快捷键一行。合成一行需要 242 + 302 = 544 px，
    # 正好铺满棋盘宽度、中间不留缝，所以必须分行。
    info = font_small.render(
        "步数 %d   最高连锁 x%d   总消除 %d" % (game.moves, max(1, game.best_combo), game.cleared_total),
        True, TEXT_DIM)
    surface.blit(info, (BOARD_X, HEIGHT - 64))

    tip = font_small.render("点击或拖拽交换  ·  空格暂停  ·  R 重开  ·  H 提示", True, (110, 118, 146))
    surface.blit(tip, (BOARD_X, HEIGHT - 38))


def draw_floats(surface, game):
    for f in game.floats:
        k = f["t"] / f["life"]
        alpha = int(255 * max(0.0, 1.0 - k ** 1.6))
        if alpha <= 4:
            continue
        font = load_font(f["size"], bold=True)
        txt = font.render(f["text"], True, f["color"])
        txt = txt.copy()
        txt.set_alpha(alpha)
        y = f["y"] - 40 * k
        surface.blit(txt, (int(f["x"] - txt.get_width() / 2), int(y - txt.get_height() / 2)))


def draw_overlay(surface, game):
    if game.state == ST_PAUSED:
        shade = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        shade.fill((8, 10, 18, 175))
        surface.blit(shade, (0, 0))
        f1 = load_font(40, bold=True)
        f2 = load_font(20)
        t1 = f1.render("已暂停", True, TEXT_MAIN)
        t2 = f2.render("按空格继续", True, TEXT_DIM)
        surface.blit(t1, (WIDTH // 2 - t1.get_width() // 2, HEIGHT // 2 - 40))
        surface.blit(t2, (WIDTH // 2 - t2.get_width() // 2, HEIGHT // 2 + 20))

    if game.state == ST_OVER:
        shade = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        shade.fill((8, 10, 18, 200))
        surface.blit(shade, (0, 0))

        f1 = load_font(44, bold=True)
        f2 = load_font(22)
        f3 = load_font(18)
        f4 = load_font(20, bold=True)

        card = pygame.Rect(0, 0, 380, 260)
        card.center = (WIDTH // 2, HEIGHT // 2)
        pygame.draw.rect(surface, PANEL, card, border_radius=20)
        pygame.draw.rect(surface, PANEL_EDGE, card, 2, border_radius=20)

        t1 = f1.render("本局结束", True, TEXT_MAIN)
        surface.blit(t1, (card.centerx - t1.get_width() // 2, card.top + 26))

        t2 = f2.render(str(game.score), True, ACCENT)
        surface.blit(t2, (card.centerx - t2.get_width() // 2, card.top + 88))

        t3 = f3.render(
            "%s   步数 %d   最高连锁 x%d" % (game.over_reason, game.moves, max(1, game.best_combo)),
            True, TEXT_DIM)
        surface.blit(t3, (card.centerx - t3.get_width() // 2, card.top + 140))

        t4 = f4.render("按 R 再来一局", True, TEXT_MAIN)
        surface.blit(t4, (card.centerx - t4.get_width() // 2, card.top + 190))


def draw_all(surface, game, bg):
    draw_board(surface, game, bg)
    draw_ui(surface, game)
    draw_floats(surface, game)
    draw_overlay(surface, game)


# ---------------------------------------------------------------- 主循环


def run(seed=None):
    pygame.init()
    try:
        pygame.display.set_caption("消消乐 Match-3")
        screen = pygame.display.set_mode((WIDTH, HEIGHT))
    except pygame.error as exc:
        print("无法创建窗口: %s" % exc)
        return 1

    clock = pygame.time.Clock()
    bg = make_background((WIDTH, HEIGHT))

    bank = SoundBank()
    game = Game(seed=seed)
    game.attach_sounds(bank)

    press_cell = None
    press_pos = None
    dragging = False
    running = True

    while running:
        dt = clock.tick(FPS) / 1000.0
        if dt > 0.05:
            dt = 0.05          # 掉帧保护，避免一帧跳太远

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    game.toggle_pause()
                elif event.key == pygame.K_r:
                    game.reset()
                elif event.key == pygame.K_h:
                    game.request_hint()

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                cell = cell_at_pixel(*event.pos)
                if cell is not None and game.state in (ST_IDLE,):
                    press_cell = cell
                    press_pos = event.pos
                    dragging = False
                    game.try_select(cell)

            elif event.type == pygame.MOUSEMOTION:
                if press_cell is not None and not dragging and game.state == ST_IDLE:
                    dx = event.pos[0] - press_pos[0]
                    dy = event.pos[1] - press_pos[1]
                    if abs(dx) > TILE * 0.42 or abs(dy) > TILE * 0.42:
                        r, c = press_cell
                        if abs(dx) > abs(dy):
                            target = (r, c + (1 if dx > 0 else -1))
                        else:
                            target = (r + (1 if dy > 0 else -1), c)
                        if in_bounds(*target):
                            game.try_drag(press_cell, target)
                        dragging = True
                        press_cell = None

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                press_cell = None
                dragging = False

        game.update(dt)
        draw_all(screen, game, bg)
        pygame.display.flip()

    pygame.quit()
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    seed = None
    if "--seed" in argv:
        i = argv.index("--seed")
        if i + 1 < len(argv):
            try:
                seed = int(argv[i + 1])
            except ValueError:
                seed = None
    return run(seed=seed)


if __name__ == "__main__":
    sys.exit(main())
