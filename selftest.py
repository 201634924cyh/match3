#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""消消乐 match3.py 的无窗口自检。

运行：
    python selftest.py

不需要显示器也不需要声卡（SDL 走 dummy 驱动）。覆盖范围：
    常量一致性、边界判断、匹配识别、棋盘生成、死局检测、计分公式、
    下落与补充、坐标换算、状态机全流程、渲染函数、性能基准。
"""

import os
import random
import sys
import time


def _relax_output_encoding():
    """输出被重定向时改用 UTF-8，避免非中文 locale 的 Windows 直接崩。

    Windows 上 stdout 接管道时默认走系统代码页（英文系统是 cp1252），
    一 println 中文就 UnicodeEncodeError。交互式控制台不动它 —— 那里
    Python 走的是控制台 API，改编码反而会乱码。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is None or stream.isatty():
                continue
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


_relax_output_encoding()

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame  # noqa: E402

import match3 as M  # noqa: E402

_checks = 0
_fails = []


def check(cond, msg):
    global _checks
    _checks += 1
    if not cond:
        _fails.append(msg)
    return bool(cond)


def section(name):
    print("\n== %s ==" % name)


def make_grid(pattern):
    """把字符串矩阵转成整数棋盘，'.' 表示 None。"""
    out = []
    for row in pattern:
        line = []
        for ch in row:
            line.append(None if ch == "." else int(ch))
        out.append(line)
    return out


# ---------------------------------------------------------------- 常量


def test_constants():
    section("常量")
    check(M.GRID == 8, "GRID 应为 8")
    check(M.TILE > 0, "TILE 应为正数")
    check(M.BOARD_W == M.GRID * M.TILE, "BOARD_W 与 GRID*TILE 不一致")
    check(M.WIDTH == M.BOARD_W + M.BOARD_X * 2, "WIDTH 与棋盘宽度不匹配")
    check(M.HEIGHT > M.BOARD_Y + M.BOARD_W, "HEIGHT 应大于棋盘底部")
    check(M.GEM_KINDS == 6, "宝石种类应为 6")
    check(len(M.GEM_COLORS) == M.GEM_KINDS, "颜色数量与宝石种类不一致")
    check(len(M.GEM_DARK) == M.GEM_KINDS, "暗色数量不一致")
    check(len(M.GEM_LIGHT) == M.GEM_KINDS, "亮色数量不一致")
    check(M.ROUND_TIME > 0, "单局时长应为正")
    check(M.FPS == 60, "帧率应为 60")
    check(M.SWAP_TIME > 0 and M.CLEAR_TIME > 0, "动画时长应为正")
    check(M.BOARD_X * 2 + M.BOARD_W == M.WIDTH, "棋盘未水平居中")
    for col in M.GEM_COLORS:
        check(len(col) == 3, "颜色应为三元组")
        check(all(0 <= v <= 255 for v in col), "颜色通道越界 %r" % (col,))


# ---------------------------------------------------------------- 基础工具


def test_bounds_and_adjacency():
    section("边界与邻接")
    check(M.in_bounds(0, 0), "左上角应在界内")
    check(M.in_bounds(7, 7), "右下角应在界内")
    check(M.in_bounds(3, 4), "中间格应在界内")
    check(not M.in_bounds(-1, 0), "负行应越界")
    check(not M.in_bounds(0, -1), "负列应越界")
    check(not M.in_bounds(8, 0), "行 8 应越界")
    check(not M.in_bounds(0, 8), "列 8 应越界")
    check(not M.in_bounds(8, 8), "双越界应返回 False")

    check(M.are_adjacent((0, 0), (0, 1)), "横向相邻")
    check(M.are_adjacent((0, 0), (1, 0)), "纵向相邻")
    check(M.are_adjacent((1, 1), (1, 0)), "反向横向相邻")
    check(not M.are_adjacent((0, 0), (1, 1)), "斜对角不算相邻")
    check(not M.are_adjacent((0, 0), (0, 2)), "隔一格不算相邻")
    check(not M.are_adjacent((0, 0), (0, 0)), "自身不算相邻")

    board = [[i * 10 + j for j in range(3)] for i in range(3)]
    M.swap_cells(board, (0, 0), (0, 1))
    check(board[0][0] == 1, "交换后 (0,0) 值错误")
    check(board[0][1] == 0, "交换后 (0,1) 值错误")
    check(board[1][1] == 11, "未参与交换的格子被改动")
    M.swap_cells(board, (0, 0), (0, 1))
    check(board[0][0] == 0 and board[0][1] == 1, "二次交换应还原")


# ---------------------------------------------------------------- 匹配识别


def test_find_matches():
    section("匹配识别")

    # 3 连横
    b = make_grid(["00012345",
                   "12345012",
                   "23450123",
                   "34501234",
                   "45012345",
                   "50123450",
                   "01234501",
                   "12345012"])
    hit = M.find_matches(b)
    check(len(hit) == 3, "横向三连应消除 3 格，实际 %d" % len(hit))
    check(hit == {(0, 0), (0, 1), (0, 2)}, "横向三连坐标不对: %r" % (hit,))

    # 3 连竖（只有第 0 列前三格同色，其余行列都不同色）
    b = make_grid(["01234501",
                   "02345012",
                   "03450123",
                   "14501234",
                   "25012345",
                   "30123450",
                   "41234501",
                   "52345012"])
    hit = M.find_matches(b)
    check(len(hit) == 3, "纵向三连应消除 3 格，实际 %d" % len(hit))
    check(hit == {(0, 0), (1, 0), (2, 0)}, "纵向三连坐标不对: %r" % (hit,))

    # 4 连
    b = make_grid(["00001234",
                   "12345012",
                   "23450123",
                   "34501234",
                   "45012345",
                   "50123450",
                   "01234501",
                   "12345012"])
    hit = M.find_matches(b)
    check(len(hit) == 4, "四连应消除 4 格，实际 %d" % len(hit))

    # 5 连
    b = make_grid(["00000123",
                   "12345012",
                   "23450123",
                   "34501234",
                   "45012345",
                   "50123450",
                   "01234501",
                   "12345012"])
    hit = M.find_matches(b)
    check(len(hit) == 5, "五连应消除 5 格，实际 %d" % len(hit))

    # 整行同色
    b = make_grid(["00000000",
                   "12345123",
                   "23450234",
                   "34501345",
                   "45012450",
                   "50123501",
                   "01234012",
                   "12345123"])
    hit = M.find_matches(b)
    check(len(hit) >= 8, "整行同色至少 8 格，实际 %d" % len(hit))

    # L 形：横竖交叉，交叉点只算一次
    b = make_grid(["00012345",
                   "01234501",
                   "01234501",
                   "12345012",
                   "23450123",
                   "34501234",
                   "45012345",
                   "50123450"])
    hit = M.find_matches(b)
    check((0, 0) in hit and (0, 1) in hit and (0, 2) in hit, "L 形缺横向部分")
    check((0, 0) in hit and (1, 0) in hit and (2, 0) in hit, "L 形缺纵向部分")
    check(hit == {(0, 0), (0, 1), (0, 2), (1, 0), (2, 0)}, "L 形坐标不对: %r" % (hit,))
    check(len(hit) == 5, "L 形去重后应为 5 格，实际 %d" % len(hit))

    # 无匹配
    b = make_grid(["01234501",
                   "12345012",
                   "23450123",
                   "34501234",
                   "45012345",
                   "50123450",
                   "01234501",
                   "12345012"])
    check(M.find_matches(b) == set(), "无匹配棋盘却返回了结果")

    # None 不参与匹配
    b = make_grid(["...12345",
                   "12345012",
                   "23450123",
                   "34501234",
                   "45012345",
                   "50123450",
                   "01234501",
                   "12345012"])
    check(M.find_matches(b) == set(), "空格不应参与匹配")

    # 两个独立的三连
    b = make_grid(["00012345",
                   "12345012",
                   "23450123",
                   "34501234",
                   "45012345",
                   "50123450",
                   "01234501",
                   "55512345"])
    hit = M.find_matches(b)
    check(len(hit) == 6, "两处独立三连应为 6 格，实际 %d" % len(hit))
    check((0, 0) in hit and (7, 0) in hit, "两处三连坐标缺失")

    # 只有两连不消除
    b = make_grid(["00123456",
                   "12345601",
                   "23456012",
                   "34560123",
                   "45601234",
                   "56012345",
                   "60123450",
                   "01234560"])
    b = [[v % 6 if v is not None else None for v in row] for row in b]
    check(M.find_matches(b) == set(), "两连不应消除")


def test_deadlock():
    section("死局检测")
    # (r+c)%3 的对角线周期布局是真正的死局；(r+c)%2 则不是
    # —— 后者交换 (0,1) 与 (1,1) 就能凑出首行三个同色，实测 has_possible_move 为 True
    b = [[(r + c) % 3 for c in range(M.GRID)] for r in range(M.GRID)]
    check(not M.find_matches(b), "死局样本本身不应带三连")
    check(not M.has_possible_move(b), "周期 3 棋盘应为死局")
    check(M.find_hint(b) is None, "死局不应返回提示")

    alt = [[(r + c) % 2 for c in range(M.GRID)] for r in range(M.GRID)]
    check(M.has_possible_move(alt), "交替棋盘其实有解，不能当死局样本")

    b2 = [[(r + c) % 3 for c in range(M.GRID)] for r in range(M.GRID)]
    # 模 3 棋盘可能本身有解也可能有匹配，只验证函数不崩且返回类型正确
    hint = M.find_hint(b2)
    check(hint is None or (isinstance(hint, tuple) and len(hint) == 2),
          "find_hint 返回类型异常")

    rng = random.Random(7)
    b3 = M.make_board(rng)
    hint = M.find_hint(b3)
    check(hint is not None, "正常生成的棋盘应当有解")
    if hint is not None:
        a, bcell = hint
        check(M.are_adjacent(a, bcell), "提示给出的两格必须相邻")
        M.swap_cells(b3, a, bcell)
        check(bool(M.find_matches(b3)), "按提示交换后应产生消除")
        M.swap_cells(b3, a, bcell)


def test_make_board():
    section("棋盘生成")
    rng = random.Random(2026)
    for i in range(60):
        b = M.make_board(rng)
        check(len(b) == M.GRID, "第 %d 次生成行数不对" % i)
        if len(b) != M.GRID:
            break
        rowok = all(len(row) == M.GRID for row in b)
        check(rowok, "第 %d 次生成列数不对" % i)
        if not rowok:
            break
        vals = [v for row in b for v in row]
        check(all(isinstance(v, int) and 0 <= v < M.GEM_KINDS for v in vals),
              "第 %d 次生成出现非法宝石值" % i)
        check(not M.find_matches(b), "第 %d 次生成自带三连" % i)
        check(M.has_possible_move(b), "第 %d 次生成是死局" % i)

    # 用同一个随机种子应得到同一个棋盘
    b1 = M.make_board(random.Random(99))
    b2 = M.make_board(random.Random(99))
    check(b1 == b2, "相同种子应生成相同棋盘")
    b3 = M.make_board(random.Random(100))
    check(b1 != b3, "不同种子应生成不同棋盘")


# ---------------------------------------------------------------- 计分


def test_score():
    section("计分公式")
    check(M.score_for(3, 1) == 30, "3 连基础分应为 30")
    check(M.score_for(4, 1) == 60, "4 连应为 40+20=60")
    check(M.score_for(5, 1) == 100, "5 连应为 50+50=100")
    check(M.score_for(6, 1) == 110, "6 连应为 60+50=110")
    check(M.score_for(3, 2) == 45, "3 连 x2 连锁应为 45")
    check(M.score_for(3, 3) == 60, "3 连 x3 连锁应为 60")
    check(M.score_for(3, 1) < M.score_for(3, 2) < M.score_for(3, 3), "连锁倍率应递增")
    check(M.score_for(0, 1) == 0, "0 消除应为 0 分")
    check(M.score_for(5, 1) > M.score_for(4, 1) > M.score_for(3, 1), "越长分越高")
    prev = -1
    for c in range(1, 9):
        v = M.score_for(4, c)
        check(v > prev, "连锁 %d 的得分应高于上一级" % c)
        prev = v


# ---------------------------------------------------------------- 下落与补充


def test_collapse():
    section("下落与补充")
    rng = random.Random(5)

    # 第 0 列留一个空洞
    b = [[None] * M.GRID for _ in range(M.GRID)]
    for r in range(M.GRID):
        for c in range(M.GRID):
            b[r][c] = (r + c) % M.GEM_KINDS
    b[3][0] = None
    b[6][0] = None
    offsets = [[0] * M.GRID for _ in range(M.GRID)]
    fall = M.collapse(b, offsets, rng)
    check(fall >= 2, "下落格数应至少 2，实际 %d" % fall)
    col0 = [b[r][0] for r in range(M.GRID)]
    check(all(v is not None for v in col0), "下落补充后不应有空格")
    check(all(0 <= v < M.GEM_KINDS for v in col0), "补充的宝石值非法")
    check(offsets[0][0] < 0, "新补充的宝石初始偏移应为负")
    check(offsets[M.GRID - 1][0] == 0, "底部未被移动的宝石偏移应为 0")

    # 整列清空
    b = [[0] * M.GRID for _ in range(M.GRID)]
    for r in range(M.GRID):
        for c in range(M.GRID):
            b[r][c] = (r * 3 + c) % M.GEM_KINDS
    for r in range(M.GRID):
        b[r][2] = None
    offsets = [[0] * M.GRID for _ in range(M.GRID)]
    fall = M.collapse(b, offsets, rng)
    check(fall == M.GRID, "整列清空应下落 8 格，实际 %d" % fall)
    check(all(b[r][2] is not None for r in range(M.GRID)), "整列补充后不应有空格")

    # 无空洞时不应改动
    b = [[0] * M.GRID for _ in range(M.GRID)]
    for r in range(M.GRID):
        for c in range(M.GRID):
            b[r][c] = (r + c * 2) % M.GEM_KINDS
    snapshot = [row[:] for row in b]
    offsets = [[0] * M.GRID for _ in range(M.GRID)]
    fall = M.collapse(b, offsets, rng)
    check(fall == 0, "无空洞时不应有下落，实际 %d" % fall)
    check(b == snapshot, "无空洞时棋盘不应被改动")
    check(all(offsets[r][c] == 0 for r in range(M.GRID) for c in range(M.GRID)),
          "无空洞时偏移应全为 0")


# ---------------------------------------------------------------- 坐标换算


def test_pixel_mapping():
    section("坐标换算")
    check(M.cell_at_pixel(M.BOARD_X, M.BOARD_Y) == (0, 0), "棋盘左上角应映射到 (0,0)")
    check(M.cell_at_pixel(M.BOARD_X + M.TILE - 1, M.BOARD_Y) == (0, 0), "同格右下角仍是 (0,0)")
    check(M.cell_at_pixel(M.BOARD_X + M.TILE, M.BOARD_Y) == (0, 1), "第二格起点应映射到 (0,1)")
    check(M.cell_at_pixel(M.BOARD_X, M.BOARD_Y + M.TILE) == (1, 0), "第二行起点应映射到 (1,0)")
    check(M.cell_at_pixel(M.BOARD_X - 1, M.BOARD_Y) is None, "左侧外应返回 None")
    check(M.cell_at_pixel(M.BOARD_X, M.BOARD_Y - 1) is None, "上方外应返回 None")
    check(M.cell_at_pixel(M.BOARD_X + M.BOARD_W, M.BOARD_Y) is None, "右侧外应返回 None")
    check(M.cell_at_pixel(M.BOARD_X, M.BOARD_Y + M.BOARD_W) is None, "下方外应返回 None")
    check(M.cell_at_pixel(M.BOARD_X + M.BOARD_W - 1, M.BOARD_Y + M.BOARD_W - 1) == (7, 7),
          "右下角应映射到 (7,7)")


# ---------------------------------------------------------------- 状态机


def test_state_machine():
    section("状态机")

    g = M.Game(seed=1234)
    check(g.state == M.ST_IDLE, "初始应为 IDLE")
    check(g.score == 0, "初始分数应为 0")
    check(abs(g.time_left - M.ROUND_TIME) < 1e-9, "初始时间应为 ROUND_TIME")
    check(g.selected is None, "初始不应有选中格")
    check(g.combo == 0, "初始连锁应为 0")

    # 选中
    ok = g.try_select((0, 0))
    check(ok is False, "首次点击只是选中，不应触发交换")
    check(g.selected == (0, 0), "选中格记录错误")
    g.try_select((0, 0))
    check(g.selected is None, "再次点击同一格应取消选中")

    # 非相邻点击：改选中目标
    g.try_select((0, 0))
    g.try_select((5, 5))
    check(g.selected == (5, 5), "点非相邻格应改为选中新格")
    g.selected = None

    # 暂停
    g.toggle_pause()
    check(g.state == M.ST_PAUSED, "应进入暂停")
    g.toggle_pause()
    check(g.state == M.ST_IDLE, "应回到 IDLE")

    # 提示
    check(g.request_hint() is True, "存在可行走法时应能给出提示")
    check(g.hint is not None, "提示结果不应为空")
    if g.hint:
        a, b = g.hint
        check(M.are_adjacent(a, b), "提示的两格应相邻")

    # 走一步完整的交换 → 消除 → 下落 → 回到 IDLE
    g2 = M.Game(seed=2024)
    hint = M.find_hint(g2.board)
    check(hint is not None, "测试棋盘应有解")
    if hint:
        a, b = hint
        started = g2.begin_swap(a, b)
        check(started is None or started is True or started is False, "begin_swap 应无返回值")
        check(g2.state == M.ST_SWAP, "开始交换后应进入 SWAP")
        check(g2.swap_pair == (a, b), "交换对记录错误")

        steps = 0
        seen_states = set()
        while steps < 600:
            seen_states.add(g2.state)
            g2.update(1 / 60.0)
            steps += 1
            if g2.state == M.ST_IDLE and g2.moves > 0 and g2.score > 0:
                break
        check(g2.moves == 1, "应记录 1 步，实际 %d" % g2.moves)
        check(g2.score > 0, "消除后分数应大于 0")
        check(g2.cleared_total >= 3, "至少消除 3 颗，实际 %d" % g2.cleared_total)
        check(M.ST_CLEAR in seen_states, "整个流程应经过 CLEAR 状态")
        check(M.ST_FALL in seen_states, "整个流程应经过 FALL 状态")
        check(g2.state == M.ST_IDLE, "流程结束应回到 IDLE，实际 %s" % g2.state)
        check(g2.best_combo >= 1, "最高连锁至少为 1")
        check(all(v is not None for row in g2.board for v in row), "结束后棋盘不应有空格")

    # 无效交换：会先 SWAP 再 SWAP_BACK 回到 IDLE，分数不变
    g3 = M.Game(seed=777)
    dead = None
    for r in range(M.GRID):
        for c in range(M.GRID - 1):
            M.swap_cells(g3.board, (r, c), (r, c + 1))
            has = bool(M.find_matches(g3.board))
            M.swap_cells(g3.board, (r, c), (r, c + 1))
            if not has:
                dead = ((r, c), (r, c + 1))
                break
        if dead:
            break
    check(dead is not None, "应能找到一个不产生消除的交换")
    if dead:
        score_before = g3.score
        g3.begin_swap(*dead)
        seen = set()
        for _ in range(200):
            seen.add(g3.state)
            g3.update(1 / 60.0)
            if g3.state == M.ST_IDLE:
                break
        check(M.ST_SWAP_BACK in seen, "无效交换应经过 SWAP_BACK")
        check(g3.score == score_before, "无效交换不应加分")
        check(g3.moves == 1, "无效交换也应计入步数")

    # 计时结束
    g4 = M.Game(seed=1)
    g4.time_left = 0.05
    g4.update(0.1)
    check(g4.state == M.ST_OVER, "时间耗尽应进入 OVER")
    check(g4.time_left <= 0.05, "时间不应回涨")
    check(g4.over_reason != "", "结束原因应有文字")
    before = g4.score
    g4.update(0.5)
    check(g4.state == M.ST_OVER, "结束状态应保持")
    check(g4.score == before, "结束后不应继续计分")

    # 结束后点击无效
    check(g4.try_select((0, 0)) is False, "结束后点击应无效")
    check(g4.try_drag((0, 0), (0, 1)) is False, "结束后拖拽应无效")

    # drag 接口
    g5 = M.Game(seed=88)
    check(g5.try_drag((0, 0), (0, 1)) in (True, False), "拖拽应返回布尔")
    if g5.state == M.ST_SWAP:
        check(g5.swap_pair == ((0, 0), (0, 1)), "拖拽交换对错误")
    g6 = M.Game(seed=88)
    check(g6.try_drag((0, 0), (3, 3)) is False, "非相邻拖拽应被拒绝")

    # 重排保证有解
    g7 = M.Game(seed=321)
    g7.board = [[(r + c) % 3 for c in range(M.GRID)] for r in range(M.GRID)]
    check(not M.has_possible_move(g7.board), "构造的死局应无解")
    g7._ensure_playable()
    check(M.has_possible_move(g7.board), "重排后应恢复可玩")
    check(g7.shuffles >= 1, "应记录至少一次重排")


def test_full_round_simulation():
    section("整局模拟")
    g = M.Game(seed=555)
    steps = 0
    acted = 0
    late_actions = 0
    while g.state != M.ST_OVER and steps < 20000:
        if g.state == M.ST_IDLE:
            hint = M.find_hint(g.board)
            if hint is None:
                g._ensure_playable()
                hint = M.find_hint(g.board)
            if hint is not None:
                # 走用户真实操作路径（try_drag），而不是直接调 begin_swap，
                # 否则会绕过"时间到就拒绝落子"的校验
                if g.try_drag(hint[0], hint[1]):
                    acted += 1
                    if g.time_left <= 0:
                        late_actions += 1
        g.update(1 / 60.0)
        steps += 1
    check(g.state == M.ST_OVER, "模拟应在时间耗尽后结束")
    check(steps < 20000, "整局应在步数上限内结束，实际 %d 步" % steps)
    check(late_actions == 0, "时间到之后不应再落子，违规 %d 次" % late_actions)
    check(g.time_left <= 0, "结束时剩余时间应归零")
    check(acted > 5, "整局至少应走 5 步，实际 %d" % acted)
    check(g.score > 0, "整局分数应大于 0")
    check(g.cleared_total >= acted * 3, "累计消除数应与步数匹配")
    check(all(v is not None for row in g.board for v in row), "结束时棋盘不应有空格")
    check(all(0 <= v < M.GEM_KINDS for v in (x for row in g.board for x in row)),
          "结束时棋盘值应合法")

    # 局终之后，任何操作入口都应保持关闭
    before = (g.score, g.moves, [row[:] for row in g.board])
    check(not g.try_drag((0, 0), (0, 1)), "结束后 try_drag 应被拒绝")
    check(not g.try_select((0, 0)), "结束后 try_select 应被拒绝")
    check(not g.begin_swap((0, 0), (0, 1)), "结束后 begin_swap 应被拒绝")
    after = (g.score, g.moves, [row[:] for row in g.board])
    check(before == after, "结束后棋盘与分数都不应变化")


# ---------------------------------------------------------------- 渲染


def test_render():
    section("渲染")
    pygame.init()
    try:
        screen = pygame.display.set_mode((M.WIDTH, M.HEIGHT))
    except pygame.error as exc:
        check(False, "无法创建离屏表面: %s" % exc)
        return

    bg = M.make_background((M.WIDTH, M.HEIGHT))
    check(bg.get_size() == (M.WIDTH, M.HEIGHT), "背景尺寸错误")
    top = bg.get_at((5, 0))[:3]
    bottom = bg.get_at((5, M.HEIGHT - 1))[:3]
    check(top != bottom, "背景应为渐变")
    check(sum(bottom) > sum(top), "背景应由暗到亮")

    # 六种宝石都能预渲染且尺寸正确
    for kind in range(M.GEM_KINDS):
        gem = M.build_gem_surface(kind, 64)
        check(gem.get_size() == (64, 64), "宝石 %d 尺寸错误" % kind)
        check(gem.get_at((32, 32))[3] > 0, "宝石 %d 中心应不透明" % kind)
        check(gem.get_at((1, 1))[3] == 0, "宝石 %d 四角应透明" % kind)

    # 各种状态下都能完整绘制
    g = M.Game(seed=42)
    states = [M.ST_IDLE, M.ST_SWAP, M.ST_SWAP_BACK, M.ST_CLEAR, M.ST_FALL, M.ST_PAUSED, M.ST_OVER]
    for st in states:
        g.state = st
        g.selected = (2, 3)
        g.hint = ((1, 1), (1, 2))
        g.clear_set = {(2, 2), (2, 3), (2, 4)}
        g.swap_pair = ((0, 0), (0, 1))
        g.swap_t = 0.05
        g.clear_t = 0.1
        try:
            M.draw_all(screen, g, bg)
            ok = True
        except Exception as exc:  # noqa: BLE001
            ok = False
            print("   绘制异常 @%s: %s" % (st, exc))
        check(ok, "状态 %s 下绘制不应抛异常" % st)

    # 飘字
    g.floats = [{"text": "+120", "x": 300, "y": 400, "t": 0.1, "life": 0.8,
                 "color": M.ACCENT, "size": 26}]
    g.state = M.ST_IDLE
    try:
        M.draw_floats(screen, g)
        ok = True
    except Exception as exc:  # noqa: BLE001
        ok = False
        print("   飘字异常: %s" % exc)
    check(ok, "飘字绘制不应抛异常")

    # 未初始化 mixer 时 SoundBank 必须安全降级
    bank = M.SoundBank()
    check(isinstance(bank.ok, bool), "SoundBank.ok 应为布尔")
    bank.play("select")
    bank.match(3)
    check(True, "静音降级不应抛异常")

    pygame.quit()


# ---------------------------------------------------------------- 性能


def test_performance():
    section("性能")
    g = M.Game(seed=9)
    t0 = time.perf_counter()
    for _ in range(2000):
        g.update(1 / 60.0)
        if g.state == M.ST_IDLE:
            hint = M.find_hint(g.board)
            if hint:
                g.begin_swap(*hint)
    dt = time.perf_counter() - t0
    per = dt / 2000 * 1000
    print("    2000 次 update 耗时 %.1f ms，单次 %.3f ms" % (dt * 1000, per))
    check(per < 8.0, "单次 update 应快于 8ms，实际 %.3f ms" % per)

    t0 = time.perf_counter()
    rng = random.Random(1)
    n = 0
    while time.perf_counter() - t0 < 0.5:
        M.find_hint(g.board)
        n += 1
    print("    0.5 秒内 find_hint 调用 %d 次" % n)
    check(n > 200, "find_hint 太慢，仅 %d 次/0.5s" % n)


# ---------------------------------------------------------------- 入口


def main():
    print("消消乐 match3.py 自检")
    print("pygame %s / SDL %s" % (pygame.version.ver, pygame.version.SDL))
    try:
        import numpy as _np
        print("numpy %s" % _np.__version__)
    except ImportError:
        print("numpy 未安装（音效将静音）")

    test_constants()
    test_bounds_and_adjacency()
    test_find_matches()
    test_deadlock()
    test_make_board()
    test_score()
    test_collapse()
    test_pixel_mapping()
    test_state_machine()
    test_full_round_simulation()
    test_render()
    test_performance()

    print("\n" + "=" * 46)
    if _fails:
        print("失败 %d / %d 项" % (len(_fails), _checks))
        for f in _fails[:40]:
            print("  x %s" % f)
        print("=" * 46)
        return 1
    print("全部通过：%d 项检查" % _checks)
    print("=" * 46)
    return 0


if __name__ == "__main__":
    sys.exit(main())
