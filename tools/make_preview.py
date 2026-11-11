# -*- coding: utf-8 -*-
"""生成 preview/ 下的预览图。

不弹窗口：走 SDL 的 dummy 驱动，纯离屏渲染。这样在 CI 或没有显示器的机器上
也能出图。

用法：
    python tools/make_preview.py
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import pygame  # noqa: E402

import match3 as M  # noqa: E402

OUT_DIR = os.path.join(ROOT, "preview")


def shot(surface, name):
    path = os.path.join(OUT_DIR, name)
    pygame.image.save(surface, path)
    print("已保存", path)


def play_a_few_moves(game, moves=14):
    """让 AI 自己走几步，把棋盘推到有分数、有连击、有飘字的状态。"""
    steps = 0
    acted = 0
    while acted < moves and steps < 8000:
        if game.state == M.ST_IDLE:
            hint = M.find_hint(game.board)
            if hint is None:
                game._ensure_playable()
                hint = M.find_hint(game.board)
            if hint is not None and game.try_drag(hint[0], hint[1]):
                acted += 1
        game.update(1 / 60.0)
        steps += 1


def main():
    pygame.init()
    os.makedirs(OUT_DIR, exist_ok=True)
    surface = pygame.Surface((M.WIDTH, M.HEIGHT))
    bg = M.make_background((M.WIDTH, M.HEIGHT))

    # 1) 开局，带提示高亮
    g = M.Game(seed=20261111)
    g.request_hint()
    M.draw_all(surface, g, bg)
    shot(surface, "01_start.png")

    # 2) 走了一段，有分数、有选中格
    g = M.Game(seed=20261111)
    play_a_few_moves(g, moves=14)
    hint = M.find_hint(g.board)
    if hint:
        g.selected = hint[0]
        g.hint = hint
    M.draw_all(surface, g, bg)
    shot(surface, "02_playing.png")

    # 3) 连击飘字：强行制造一次 L 形多连消除后、宝石正在发亮膨胀的瞬间
    g = M.Game(seed=777)
    play_a_few_moves(g, moves=8)
    g.combo = 3
    g.best_combo = max(g.best_combo, 3)
    g.clear_set = {(3, 2), (3, 3), (3, 4), (4, 3), (5, 3)}
    g.state = M.ST_CLEAR
    g.clear_t = M.CLEAR_TIME * 0.30  # 取"先放大"那一段，缩没还没开始
    g.floats = []
    cx = M.BOARD_X + 4 * M.TILE
    cy = M.BOARD_Y + 4 * M.TILE
    g.floats.append({
        "text": "+180", "x": cx, "y": cy, "t": 0.0, "life": M.FLOAT_TIME,
        "color": M.ACCENT, "size": 26,
    })
    g.floats.append({
        "text": "连击 x3", "x": cx, "y": cy - 46, "t": 0.0, "life": M.FLOAT_TIME,
        "color": (255, 150, 200), "size": 22,
    })
    M.draw_all(surface, g, bg)
    shot(surface, "03_combo.png")

    # 4) 结算界面
    g = M.Game(seed=20261111)
    play_a_few_moves(g, moves=18)
    g.finish("时间到")
    M.draw_all(surface, g, bg)
    shot(surface, "04_gameover.png")

    pygame.quit()
    print("预览图生成完毕，共 4 张。")


if __name__ == "__main__":
    main()
