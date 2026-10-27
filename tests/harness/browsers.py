"""WebDriver sessions for the three test browsers, and the mechanisms the rig depends on.

Each mechanism here was verified on the test machine; tests/README.md ("Rig notes") has the record.

* Chrome Beta, headless. prefers-color-scheme through CDP Emulation.setEmulatedMedia, which also
  applies inside same-origin iframes. Focus emulation keeps :focus working in background tabs.
* Firefox beta, headless. prefers-color-scheme through the content override pref
  layout.css.prefers-color-scheme.content-override (0 dark, 1 light, 2 system, 3 browser theme),
  set at runtime from the chrome context. geckodriver needs --allow-system-access for that. The
  change reaches content asynchronously, so set_media() polls until the host page sees it.
* Safari, through /usr/bin/safaridriver, visible. No emulation: the OS appearance is detected and
  only that media leg runs; data-theme legs still run. Pointer and keyboard input need a visible,
  focused window (an unlocked screen); interactive() reports whether that holds.
"""
import os
import time

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

CHROME_BINARY = os.environ.get("FEMTO_CHROME_BINARY", "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta")
FIREFOX_BINARY = os.environ.get("FEMTO_FIREFOX_BINARY", "/Applications/Firefox.app/Contents/MacOS/firefox")
SAFARIDRIVER = os.environ.get("FEMTO_SAFARIDRIVER", "/usr/bin/safaridriver")
WINDOW = (1800, 1000)          # top-level window; the fixture iframe sets the tested width
FRAME_HEIGHT = 800             # fixture viewport height in every browser
PARK = (6, 6)                  # pointer parking spot on the host page strip, outside the iframe
BROWSERS = ("chrome", "firefox", "safari")
FF_SCHEME_PREF = "layout.css.prefers-color-scheme.content-override"
FF_SCHEME_VALUES = {"dark": 0, "light": 1}


class RigError(Exception):
    """A rig mechanism did not behave as verified; the cell cannot be trusted."""


def _chrome():
    o = webdriver.ChromeOptions()
    o.binary_location = CHROME_BINARY
    for a in ("--headless", f"--window-size={WINDOW[0]},{WINDOW[1]}", "--force-device-scale-factor=1",
              "--no-first-run", "--no-default-browser-check", "--disable-search-engine-choice-screen",
              "--force-color-profile=srgb", "--hide-scrollbars", "--disable-background-timer-throttling",
              "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows"):
        o.add_argument(a)
    return webdriver.Chrome(options=o)


def _firefox():
    from selenium.webdriver.firefox.service import Service
    o = webdriver.FirefoxOptions()
    o.binary_location = FIREFOX_BINARY
    o.add_argument("-headless")
    o.add_argument(f"--width={WINDOW[0]}")
    o.add_argument(f"--height={WINDOW[1]}")
    o.set_preference(FF_SCHEME_PREF, FF_SCHEME_VALUES["light"])
    o.set_preference("layout.css.devPixelsPerPx", "1.0")
    return webdriver.Firefox(options=o, service=Service(service_args=["--allow-system-access"]))


def _kill_automation_safari():
    """Terminate Safari instances that safaridriver launched (they run with --automation). A session
    that died without quitting leaves its instance paired, and every new session is refused with
    "The Safari instance is already paired with a different session". The user's own Safari never
    carries --automation."""
    import subprocess
    out = subprocess.run(["pgrep", "-f", "Safari.app/Contents/MacOS/Safari .*--automation"],
                         capture_output=True, text=True).stdout.split()
    for pid in out:
        subprocess.run(["kill", pid], capture_output=True)
    if out:
        time.sleep(3)
    return out


def _safari():
    from selenium.common.exceptions import SessionNotCreatedException
    from selenium.webdriver.safari.service import Service
    # The caller holds the machine-wide Safari lock, so no other harness session is live. An
    # automation instance left by a session that died (a killed run) keeps its windows, and a new
    # session reusing that instance opens its window behind them, without focus; start clean.
    _kill_automation_safari()
    try:
        d = webdriver.Safari(service=Service(executable_path=SAFARIDRIVER))
    except SessionNotCreatedException as e:
        if "already paired" not in str(e) or not _kill_automation_safari():
            raise
        d = webdriver.Safari(service=Service(executable_path=SAFARIDRIVER))
    try:
        d.set_window_rect(0, 0, WINDOW[0], WINDOW[1])
    except WebDriverException:
        pass
    return d


class Session:
    """One browser, one host page, many fixture loads."""

    def __init__(self, browser: str, base: str, log):
        if browser not in BROWSERS:
            raise ValueError(f"unknown browser {browser}")
        self.browser, self.base, self.log = browser, base, log
        t0 = time.time()
        from .locks import driver_start
        with driver_start(f"{browser} session", log):
            self.driver = {"chrome": _chrome, "firefox": _firefox, "safari": _safari}[browser]()
        self.launch_s = round(time.time() - t0, 2)
        try:
            self._setup()
        except Exception:
            try:
                self.driver.quit()
            except Exception:
                pass
            raise

    def _setup(self):
        browser = self.browser
        caps = self.driver.capabilities
        self.version = caps.get("browserVersion")
        self.driver_version = ((caps.get("chrome") or {}).get("chromedriverVersion", "").split(" ")[0]
                               or caps.get("moz:geckodriverVersion") or "safaridriver")
        self.driver.set_script_timeout(60)
        self.driver.set_page_load_timeout(60)
        # Fail a hung command (a modal sheet in Safari, say) after 90 s instead of urllib3's 120 s.
        try:
            self.driver.command_executor.client_config.timeout = 90
        except AttributeError:
            pass
        self.media = None
        self.pseudos = None
        if browser == "chrome":
            self.driver.execute_cdp_cmd("Emulation.setFocusEmulationEnabled", {"enabled": True})
        self.open_host()
        st = self.host_status()
        self.os_scheme = "dark" if st["dark"] else "light"
        self.host = st

    # -- host page and scripts ------------------------------------------------------------
    def open_host(self):
        self.driver.get(self.base + "/tests/harness/host.html")
        if not self.driver.execute_script("return !!window.H"):
            raise RigError("host page did not load differ.js")
        self.frame_el = None

    def js(self, fn: str, *args):
        return self.driver.execute_script(f"return H.{fn}.apply(null, arguments)", *args)

    def ajs(self, fn: str, *args):
        script = (f"const done = arguments[arguments.length - 1];"
                  f"H.{fn}.apply(null, Array.prototype.slice.call(arguments, 0, -1))"
                  f".then(done, e => done({{errors: ['in-page exception: ' + (e && e.stack || e)]}}));")
        return self.driver.execute_async_script(script, *args)

    def host_status(self):
        return self.js("hostStatus")

    def interactive(self) -> tuple[bool, str]:
        """Whether pointer and keyboard input reach the page (Safari needs a visible, focused window)."""
        if self.browser != "safari":
            return True, ""
        st = self.host_status()
        if st["visibility"] == "visible" and not st["hasFocus"]:
            # Each fixture load replaces the iframe. When the old iframe held focus (after a focus
            # state), Safari leaves the host document without focus: document.hasFocus() is false
            # although the window is key and input still arrives. window.focus() gives focus back
            # to the host document; it cannot make a window key behind another app or a lock screen.
            self.driver.execute_script("window.focus()")
            st = self.host_status()
        if st["visibility"] != "visible" or not st["hasFocus"]:
            # Ask safaridriver once to bring the session's window forward (it may sit behind
            # another window), then check again.
            try:
                self.driver.switch_to.window(self.driver.current_window_handle)
                time.sleep(0.3)
                self.driver.execute_script("window.focus()")
                st = self.host_status()
            except WebDriverException:
                pass
        if st["visibility"] != "visible" or not st["hasFocus"]:
            return False, (f"Safari window is not visible and focused (visibilityState={st['visibility']}, "
                           f"hasFocus={st['hasFocus']}); the screen may be locked. Interactive states need an "
                           "unlocked screen with the Safari automation window in front.")
        return True, ""

    # -- color scheme ---------------------------------------------------------------------
    def set_media(self, media: str):
        """Make prefers-color-scheme report `media` inside the fixture iframe."""
        if media == self.media:
            return
        if self.browser == "chrome":
            self.driver.execute_cdp_cmd("Emulation.setEmulatedMedia",
                                        {"features": [{"name": "prefers-color-scheme", "value": media}]})
        elif self.browser == "firefox":
            with self.driver.context(self.driver.CONTEXT_CHROME):
                self.driver.execute_script(
                    f"Services.prefs.setIntPref('{FF_SCHEME_PREF}', {FF_SCHEME_VALUES[media]})")
            want = media == "dark"
            deadline = time.time() + 10
            while self.driver.execute_script("return matchMedia('(prefers-color-scheme: dark)').matches") != want:
                if time.time() > deadline:
                    raise RigError(f"Firefox did not apply {FF_SCHEME_PREF}={FF_SCHEME_VALUES[media]}")
                time.sleep(0.05)
        else:
            if media != self.os_scheme:
                raise RigError(f"Safari cannot emulate prefers-color-scheme: {media}; the OS scheme is {self.os_scheme}")
        self.media = media

    # -- input ----------------------------------------------------------------------------
    def _pointer(self, x, y, down=False, up=False):
        ab = ActionBuilder(self.driver, duration=0)
        ab.pointer_action.move_to_location(int(x), int(y))
        if down:
            ab.pointer_action.pointer_down()
        if up:
            ab.pointer_action.pointer_up()
        ab.perform()

    def move(self, x, y):
        self._pointer(x, y)

    def press(self, x, y):
        self._pointer(x, y, down=True)

    def release(self, x, y):
        self._pointer(x, y, up=True)

    def park(self):
        self._pointer(*PARK)

    def tab(self, shift=False):
        """A real Tab keypress. Safari moves to links and buttons only with Option held."""
        ac = ActionChains(self.driver, duration=0)
        mods = ([Keys.SHIFT] if shift else []) + ([Keys.ALT] if self.browser == "safari" else [])
        for m in mods:
            ac.key_down(m)
        ac.send_keys(Keys.TAB)
        for m in reversed(mods):
            ac.key_up(m)
        ac.perform()

    def reset_input(self):
        try:
            ActionBuilder(self.driver).clear_actions()
        except WebDriverException:
            pass

    # -- screenshots ----------------------------------------------------------------------
    def frame_png(self) -> bytes:
        return self.driver.find_element(By.ID, "frame").screenshot_as_png

    def quit(self):
        try:
            if self.browser == "firefox":
                with self.driver.context(self.driver.CONTEXT_CHROME):
                    self.driver.execute_script(f"Services.prefs.clearUserPref('{FF_SCHEME_PREF}')")
        except Exception:
            pass
        try:
            self.driver.quit()
        except Exception:
            pass
