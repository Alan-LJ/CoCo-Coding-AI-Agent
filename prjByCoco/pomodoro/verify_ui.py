import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).parent
PAGE_URL = (BASE_DIR / "index.html").as_uri()
SHOT_DIR = BASE_DIR / "screenshots"


def main() -> None:
    SHOT_DIR.mkdir(exist_ok=True)
    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 480, "height": 900})
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: console_errors.append(str(err)))

        page.goto(PAGE_URL)

        # 1. 初始状态：25:00，专注中，红色主题
        assert page.locator("#time-display").inner_text() == "25:00", "初始时间不是 25:00"
        assert page.locator("#phase-label").inner_text() == "专注中"
        assert page.locator("body").get_attribute("data-phase") == "work"
        page.screenshot(path=str(SHOT_DIR / "1_initial.png"))

        # 2. 点击开始，计时器应走动
        page.click("#start-btn")
        assert page.locator("#start-btn").inner_text() == "暂停"
        time.sleep(2.5)
        elapsed_text = page.locator("#time-display").inner_text()
        assert elapsed_text in ("24:58", "24:57"), f"计时未走动: {elapsed_text}"
        # 圆环进度应有偏移
        offset = page.locator("#ring-progress").evaluate("el => el.style.strokeDashoffset")
        assert float(offset) > 0, "圆环进度未更新"
        page.screenshot(path=str(SHOT_DIR / "2_running.png"))

        # 3. 暂停后时间不再变化
        page.click("#start-btn")
        paused_text = page.locator("#time-display").inner_text()
        time.sleep(1.5)
        assert page.locator("#time-display").inner_text() == paused_text, "暂停后仍在计时"

        # 4. 重置恢复 25:00
        page.click("#reset-btn")
        assert page.locator("#time-display").inner_text() == "25:00"

        # 5. 输入任务
        page.fill("#task-input", "写设计文档")

        # 6. 跳过进入短休息：绿色主题 + 05:00 + 圆点亮 1 个
        page.click("#skip-btn")
        assert page.locator("body").get_attribute("data-phase") == "short"
        assert page.locator("#phase-label").inner_text() == "短休息"
        assert page.locator("#time-display").inner_text() == "05:00"
        assert page.locator("#cycle-dots .dot.filled").count() == 1
        page.screenshot(path=str(SHOT_DIR / "3_short_break.png"))

        # 7. 设置面板：修改时长并保存
        page.click("#settings-btn")
        page.fill("#set-work", "30")
        page.click("#settings-save")
        page.click("#skip-btn")  # 回到 work 阶段
        assert page.locator("#time-display").inner_text() == "30:00", "设置未生效"
        # 设置应持久化到 localStorage
        saved = page.evaluate("localStorage.getItem('pomodoro-settings')")
        assert '"work":30' in saved, f"设置未持久化: {saved}"
        page.screenshot(path=str(SHOT_DIR / "4_after_settings.png"))

        browser.close()

    if console_errors:
        raise AssertionError(f"浏览器控制台报错: {console_errors}")
    print(f"VERIFY_OK  截图保存在: {SHOT_DIR}")


if __name__ == "__main__":
    main()
