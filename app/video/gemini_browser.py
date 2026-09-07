"""
Gemini Browser Automation — Generate images and media via gemini.google.com
Uses a single persistent Brave browser window and single chat conversation.
No multiple windows, no multiple chats.
"""

import os
import time
import atexit
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

BROWSER_PROFILE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "browser_profile")
BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
GEMINI_URL = "https://gemini.google.com/app"


def _ensure_dirs():
    os.makedirs(BROWSER_PROFILE_DIR, exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "..", "data", "temp"), exist_ok=True)


class GeminiBrowserController:
    """
    Singleton controller: exactly ONE window, ONE chat session.
    Reuses the existing tab and conversation thread without spawning new windows.
    """
    _instance = None

    def __init__(self):
        self.playwright = None
        self.context = None
        self.page = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_page(self, headless: bool = True):
        _ensure_dirs()
        if self.page and not self.page.is_closed():
            return self.page

        if self.playwright is None:
            self.playwright = sync_playwright().start()

        if self.context is None:
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=os.path.abspath(BROWSER_PROFILE_DIR),
                executable_path=BRAVE_PATH,
                headless=headless,
                viewport={"width": 1280, "height": 900},
                accept_downloads=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
                ignore_default_args=["--enable-automation"],
            )

        # Reuse the first page if already created by persistent context
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = self.context.new_page()

        # Close any extraneous tabs if Brave opened more than one
        while len(self.context.pages) > 1:
            try:
                self.context.pages[-1].close()
            except Exception:
                break

        current_url = self.page.url
        if not current_url or "gemini.google.com" not in current_url:
            self.page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=45_000)
            time.sleep(3)

        return self.page

    def close(self):
        try:
            if self.page and not self.page.is_closed():
                self.page.close()
        except Exception:
            pass
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
        self.page = None
        self.context = None
        self.playwright = None


_controller = GeminiBrowserController.get_instance()
atexit.register(_controller.close)


def _dismiss_overlays(page):
    """Dismiss popups/welcome cards/cookie banners without blocking input."""
    dismiss_selectors = [
        'button[aria-label*="Close"]',
        'button[aria-label*="Dismiss"]',
        'button[aria-label*="Got it"]',
        'button:has-text("Got it")',
        'button:has-text("OK")',
        'button:has-text("Skip")',
        'button:has-text("No thanks")',
        'button:has-text("Continue")',
        'button:has-text("Accept")',
    ]
    for sel in dismiss_selectors:
        try:
            els = page.query_selector_all(sel)
            for el in els:
                if el.is_visible():
                    el.evaluate('el => el.click()')
                    time.sleep(0.3)
        except Exception:
            pass

    try:
        page.evaluate('''() => {
            document.querySelectorAll('.cdk-overlay-container, .cdk-overlay-backdrop').forEach(el => {
                el.style.display = 'none';
            });
        }''')
    except Exception:
        pass


def _find_and_type_prompt(page, text: str) -> bool:
    """Finds the input field in the CURRENT chat and enters the prompt."""
    _dismiss_overlays(page)

    selectors = [
        'div[contenteditable="true"]',
        'rich-textarea div[contenteditable]',
        '.ql-editor',
        'textarea',
        'p[data-placeholder]',
    ]
    for sel in selectors:
        el = page.query_selector(sel)
        if el and el.is_visible():
            try:
                el.evaluate('el => { el.focus(); el.click(); }')
                time.sleep(0.3)
                if text:
                    page.keyboard.type(text, delay=6)
                return True
            except Exception:
                continue
    return False


def _click_send(page) -> bool:
    """Clicks send button in current chat."""
    send_selectors = [
        'button[aria-label*="Send message"]',
        'button[aria-label*="Send"]',
        'button[data-at="send"]',
        '.send-button',
    ]
    for sel in send_selectors:
        btn = page.query_selector(sel)
        if btn and btn.is_visible():
            try:
                btn.click(force=True)
                return True
            except Exception:
                try:
                    btn.evaluate('el => el.click()')
                    return True
                except Exception:
                    pass
    page.keyboard.press("Enter")
    return True


def _wait_for_response_complete(page, timeout_sec: int = 120) -> bool:
    """Waits for Gemini in the single chat to finish generating."""
    deadline = time.time() + timeout_sec
    time.sleep(2)
    while time.time() < deadline:
        time.sleep(2)
        stop_btn = page.query_selector(
            'button[aria-label*="Stop"], button[aria-label*="stop"], '
            'button[aria-label*="Cancel"], mat-icon:has-text("stop")'
        )
        if not stop_btn or not stop_btn.is_visible():
            time.sleep(2)
            stop_btn2 = page.query_selector('button[aria-label*="Stop"]')
            if not stop_btn2 or not stop_btn2.is_visible():
                return True
    return False


def _try_download_image(page, output_path: str) -> bool:
    """Finds the most recently generated image in the chat and saves it."""
    from PIL import Image

    # Check for generated image elements
    img_els = page.query_selector_all('img')
    valid_imgs = []
    for img in img_els:
        try:
            w = img.evaluate('el => el.naturalWidth')
            h = img.evaluate('el => el.naturalHeight')
            if w and int(w) >= 300 and h and int(h) >= 300:
                valid_imgs.append(img)
        except Exception:
            continue

    if valid_imgs:
        latest_img = valid_imgs[-1]
        try:
            # Scroll image into view so it's not behind the bottom bar
            latest_img.scroll_into_view_if_needed()
            time.sleep(0.5)

            # Try download button first if available
            dl_btns = page.query_selector_all('button[aria-label*="Download"], button[aria-label*="download"]')
            if dl_btns:
                try:
                    with page.expect_download(timeout=5_000) as dl_info:
                        dl_btns[-1].click(force=True)
                    download = dl_info.value
                    download.save_as(output_path)
                    print(f"[GEMINI BROWSER] Image downloaded via button: {output_path}")
                    return True
                except Exception:
                    pass

            # Hide bottom input bar and overlays so they don't cover the image
            try:
                page.evaluate('''() => {
                    document.querySelectorAll('.input-area-container, rich-textarea, .bottom-container, .chat-window-bottom, .conversation-footer').forEach(e => {
                        e.style.visibility = 'hidden';
                    });
                }''')
                time.sleep(0.3)
            except Exception:
                pass

            # Fallback: screenshot element cleanly
            latest_img.screenshot(path=output_path)

            # Restore bottom bar
            try:
                page.evaluate('''() => {
                    document.querySelectorAll('.input-area-container, rich-textarea, .bottom-container, .chat-window-bottom, .conversation-footer').forEach(e => {
                        e.style.visibility = 'visible';
                    });
                }''')
            except Exception:
                pass

            # Clean any top icons or bottom overlap using PIL to guarantee clean 576x1024 portrait
            with Image.open(output_path) as im:
                w, h = im.size
                # If top action icons are present, crop top 40px
                top_crop = 45 if h > 800 else 0
                bottom_crop = h - 20 if h > 800 else h
                im_cropped = im.crop((0, top_crop, w, bottom_crop))
                im_final = im_cropped.resize((576, 1024), Image.LANCZOS)
                im_final.save(output_path, "PNG")

            print(f"[GEMINI BROWSER] Image captured and saved: {output_path} (576x1024)")
            return True
        except Exception as e:
            print(f"[GEMINI BROWSER] Screenshot save error: {e}")
            pass

    return False


def generate_image_via_browser(
    prompt: str,
    output_path: str,
    timeout_sec: int = 120,
) -> str:
    """
    Generates an image using Gemini Pro in the single, persistent chat.
    Does NOT open multiple windows or multiple chats.
    """
    _ensure_dirs()
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    try:
        page = _controller.get_page(headless=True)
        time.sleep(2)

        image_prompt = f"Generate an image: {prompt}. Vertical 9:16 portrait orientation, Pixar 3D animation style."

        if not _find_and_type_prompt(page, image_prompt):
            print("[GEMINI BROWSER] Could not find chat input.")
            return None

        time.sleep(0.5)
        _click_send(page)
        print(f"[GEMINI BROWSER] Prompt sent in active chat. Waiting up to {timeout_sec}s for generation...")

        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            time.sleep(3)
            try:
                if _try_download_image(page, output_path):
                    return output_path
            except Exception:
                time.sleep(1)
                continue

        debug_path = os.path.join("data", "temp", "gemini_image_debug.png")
        try:
            page.screenshot(path=debug_path, full_page=True)
            print(f"[GEMINI BROWSER] Could not capture image. Saved debug: {debug_path}")
        except Exception:
            pass
        return None

    except Exception as e:
        print(f"[GEMINI BROWSER] Error: {e}")
        return None

    except Exception as e:
        print(f"[GEMINI BROWSER] Error: {e}")
        return None


def check_login_status() -> bool:
    """Verifies login in the single browser session."""
    try:
        page = _controller.get_page(headless=True)
        time.sleep(2)
        found = _find_and_type_prompt(page, "")
        if found:
            print("[GEMINI BROWSER] Session active. Single chat ready.")
            return True
        print("[GEMINI BROWSER] Not logged in.")
        return False
    except Exception as e:
        print(f"[GEMINI BROWSER] Check failed: {e}")
        return False
