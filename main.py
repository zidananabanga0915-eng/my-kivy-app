from kivymd.app import MDApp
from kivy.properties import StringProperty, ListProperty, NumericProperty, BooleanProperty
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition, NoTransition
from kivy.animation import Animation
from kivy.core.window import Window
from kivymd.uix.pickers import MDDatePicker
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel, MDIcon
from kivymd.uix.selectioncontrol import MDCheckbox
from kivy.uix.widget import Widget
from kivy.metrics import dp
from datetime import date, datetime, timedelta
from kivy.uix.behaviors import ButtonBehavior
import calendar as cal
from kivy.factory import Factory
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Rectangle, RoundedRectangle, Line
from kivy.graphics.texture import Texture
from kivy.core.text import Label as CoreLabel
from kivy.core.audio import SoundLoader
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.modalview import ModalView
import os
import struct
import math
import wave
import tempfile


# ── PriorityItem ──────────────────────────────────────────────────────────────
class PriorityItem(ButtonBehavior, MDBoxLayout):
    icon = StringProperty()
    icon_color = ListProperty([0, 0, 0, 1])
    text = StringProperty()


# ── TaskCard ──────────────────────────────────────────────────────────────────
class TaskCard(ButtonBehavior, MDBoxLayout):
    """Fires on_long_press after 0.4 s hold. Touch handling is minimal."""
    task_id = StringProperty("")
    __events__ = ('on_long_press',)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._lp_ev = None
        self._held = False

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._held = True
            self._lp_ev = Clock.schedule_once(
                lambda dt: self._fire_lp(touch), 0.4)
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        self._held = False
        if self._lp_ev:
            self._lp_ev.cancel()
            self._lp_ev = None
        return super().on_touch_up(touch)

    def _fire_lp(self, touch):
        if self._held:
            self.dispatch('on_long_press', touch)

    def on_long_press(self, *args):
        pass


# ── Main App ──────────────────────────────────────────────────────────────────
class MainApp(MDApp):
    current_screen   = StringProperty("Task Screen")
    active_tab       = StringProperty("Personal")
    selected_date    = StringProperty("")
    selected_priority = StringProperty("No priority")
    selected_repeat  = StringProperty("Do not repeat")
    current_month_label = StringProperty("")
    cal_year         = NumericProperty(0)
    cal_month        = NumericProperty(0)
    selected_day     = NumericProperty(0)
    calendar_view    = StringProperty("month")
    week_offset      = NumericProperty(0)
    stats_week_offset = NumericProperty(0)
    drawer_open      = BooleanProperty(False)
    category_expanded = BooleanProperty(False)

    # Settings
    dark_mode        = BooleanProperty(False)
    swipe_gesture    = BooleanProperty(True)
    completion_tone  = BooleanProperty(True)

    # Drawer category counts
    count_all      = NumericProperty(0)
    count_personal = NumericProperty(0)
    count_work     = NumericProperty(0)
    count_school   = NumericProperty(0)
    count_other    = NumericProperty(0)

    # Theme
    bg_color        = ListProperty([0.96, 0.97, 0.98, 1])
    surface_color   = ListProperty([1, 1, 1, 1])
    text_primary    = ListProperty([0.1, 0.1, 0.1, 1])
    text_secondary  = ListProperty([0.5, 0.5, 0.5, 1])
    task_card_color = ListProperty([0.93, 0.96, 1, 1])
    header_bg       = ListProperty([0.96, 0.97, 0.98, 1])
    primary_color       = ListProperty([0.16, 0.55, 0.87, 1])
    primary_tint        = ListProperty([0.83, 0.91, 0.97, 1])
    theme_preview_color = ListProperty([0.16, 0.55, 0.87, 1])
    theme_preview_tint  = ListProperty([0.83, 0.91, 0.97, 1])

    # ── Priority colour/icon lookup tables (avoid repeated dict creation) ──
    _PRIORITY_COLORS = {
        "Important": (0.2, 0.6, 1, 1),
        "Urgent":    (1, 0.2, 0.2, 1),
        "Long-term": (0.2, 0.8, 0.2, 1),
        "No priority": (0.5, 0.5, 0.5, 1),
    }
    _PRIORITY_ICONS = {
        "Important": "flag", "Urgent": "flag",
        "Long-term": "flag", "No priority": "flag-outline",
    }
    _CAT_COLORS = {
        "Personal": (0.2, 0.4, 0.9, 1),
        "Work":     (0.4, 0.6, 1, 1),
        "School":   (0.6, 0.8, 1, 1),
        "Other":    (0.8, 0.9, 1, 1),
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calendar_tasks     = {}   # date_key -> list of task dicts
        self.daily_completions  = {}   # date_key -> int
        self.completion_sound   = None
        self._touch_start_x     = None
        self._swipe_threshold   = 80
        self.task_registry      = {}   # task_id -> state dict
        self._task_id_counter   = 0
        self.favorites_list     = []
        self.trash_list         = []
        # Deferred stats update handle so rapid changes collapse into one call
        self._stats_pending     = None
        # Cache CoreLabel textures for bar-chart y-axis labels
        self._bar_label_cache   = {}

    def _new_task_id(self):
        self._task_id_counter += 1
        return f"t{self._task_id_counter}"   # shorter string

    # ── on_start ──────────────────────────────────────────────────
    def on_start(self):
        tm = self.root.ids.tab_manager
        # Build task_lists dict once; access via self.task_lists[tab]
        self.task_lists = {
            tab: tm.get_screen(tab).children[0].children[0]
            for tab in ("Personal", "Work", "School", "Other")
        }
        today = date.today()
        self.cal_year  = today.year
        self.cal_month = today.month
        # Defer heavy startup work so the first frame renders fast
        Clock.schedule_once(self._deferred_start, 0)

    def _deferred_start(self, dt):
        self.build_calendar()
        self._generate_completion_sound()
        Window.bind(on_touch_down=self._on_window_touch_down,
                    on_touch_up=self._on_window_touch_up)

    # ── Swipe navigation ──────────────────────────────────────────
    _MAIN_SCREENS = ("Task Screen", "Calendar Screen", "Statistics")

    def _on_window_touch_down(self, window, touch):
        self._touch_start_x = touch.x

    def _on_window_touch_up(self, window, touch):
        if not self.swipe_gesture or self.drawer_open:
            return
        if self._touch_start_x is None:
            return
        delta = touch.x - self._touch_start_x
        if abs(delta) < self._swipe_threshold:
            return
        screens = self._MAIN_SCREENS
        if self.current_screen not in screens:
            return
        idx = screens.index(self.current_screen)
        sm = self.root.ids.screen_manager
        if delta < 0 and idx < len(screens) - 1:
            sm.transition = SlideTransition(direction="left", duration=0.22)
            self.change_screen(screens[idx + 1])
        elif delta > 0 and idx > 0:
            sm.transition = SlideTransition(direction="right", duration=0.22)
            self.change_screen(screens[idx - 1])

    # ── Completion sound (generated once, reused) ─────────────────
    def _generate_completion_sound(self):
        try:
            freq        = 880
            duration    = 0.15
            sample_rate = 44100
            n_samples   = int(sample_rate * duration)
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            with wave.open(tmp.name, "w") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                TWO_PI = 2 * math.pi
                frames = bytearray(n_samples * 2)
                for i in range(n_samples):
                    t        = i / sample_rate
                    envelope = min(1.0, (n_samples - i) / (n_samples * 0.3))
                    val      = int(32767 * envelope * math.sin(TWO_PI * freq * t))
                    struct.pack_into('<h', frames, i * 2, val)
                wf.writeframes(bytes(frames))
            self.completion_sound = SoundLoader.load(tmp.name)
        except Exception as e:
            print("Sound error:", e)

    def play_completion_tone(self):
        if self.completion_tone and self.completion_sound:
            self.completion_sound.seek(0)
            self.completion_sound.play()

    # ── Dark mode ─────────────────────────────────────────────────
    def toggle_dark_mode(self, value):
        self.dark_mode = value
        if value:
            self.theme_cls.theme_style = "Dark"
            self.bg_color       = [0.1,  0.1,  0.12, 1]
            self.surface_color  = [0.18, 0.18, 0.22, 1]
            self.text_primary   = [1,    1,    1,    1]
            self.text_secondary = [0.7,  0.7,  0.7,  1]
            self.task_card_color = [0.2, 0.22, 0.28, 1]
            self.header_bg      = [0.1,  0.1,  0.12, 1]
        else:
            self.theme_cls.theme_style = "Light"
            self.bg_color       = [0.96, 0.97, 0.98, 1]
            self.surface_color  = [1,    1,    1,    1]
            self.text_primary   = [0.1,  0.1,  0.1,  1]
            self.text_secondary = [0.5,  0.5,  0.5,  1]
            self.task_card_color = [0.93, 0.96, 1,   1]
            self.header_bg      = [0.96, 0.97, 0.98, 1]

    def toggle_swipe(self, value):          self.swipe_gesture = value
    def toggle_completion_tone(self, value): self.completion_tone = value

    # ── Drawer ────────────────────────────────────────────────────
    def open_drawer(self):
        drawer  = self.root.ids.nav_drawer
        overlay = self.root.ids.drawer_overlay
        Animation(x=0, duration=0.22).start(drawer)
        overlay.opacity = 1
        self.drawer_open = True

    def close_drawer(self):
        drawer  = self.root.ids.nav_drawer
        overlay = self.root.ids.drawer_overlay
        Animation(x=-dp(280), duration=0.22).start(drawer)
        overlay.opacity = 0
        self.drawer_open = False

    def toggle_category(self):
        self.category_expanded = not self.category_expanded

    # ── Screen navigation ─────────────────────────────────────────
    def change_screen(self, name):
        self.root.ids.screen_manager.current = name
        self.current_screen = name
        if name == "Calendar Screen":
            self.build_calendar()
        elif name == "Statistics":
            self._schedule_stats()
        elif name == "Favorites Screen":
            self.refresh_favorites_screen()
        elif name == "Trash Screen":
            self.refresh_trash_screen()

    def _go_to(self, name):
        sm = self.root.ids.screen_manager
        sm.current = name
        self.current_screen = name

    def open_faq(self):
        self.close_drawer()
        Clock.schedule_once(lambda dt: self._go_to("FAQ Screen"), 0.28)

    def close_faq(self):
        self._go_to("Task Screen")

    def open_settings(self):
        self.close_drawer()
        Clock.schedule_once(lambda dt: self._go_to("Settings Screen"), 0.28)

    def close_settings(self):
        self._go_to("Task Screen")

    def open_theme(self):
        self.close_drawer()
        self.theme_preview_color = list(self.primary_color)
        self.theme_preview_tint  = self._make_tint(self.primary_color, 0.15)
        Clock.schedule_once(lambda dt: self._go_to("Theme Screen"), 0.32)

    def close_theme(self):
        self._go_to("Task Screen")

    def _make_tint(self, color, strength=0.2):
        r, g, b = color[0], color[1], color[2]
        s = strength
        return [min(1, r * s + (1 - s)),
                min(1, g * s + (1 - s)),
                min(1, b * s + (1 - s)), 1]

    def set_preview_color(self, color):
        self.theme_preview_color = list(color)
        self.theme_preview_tint  = self._make_tint(color, 0.2)

    def apply_theme(self):
        self.primary_color      = list(self.theme_preview_color)
        tint                    = self._make_tint(self.primary_color, 0.15)
        self.primary_tint       = tint
        self.task_card_color    = tint
        self.theme_preview_tint = tint
        self.bg_color           = self._make_tint(self.primary_color, 0.08)
        self.close_theme()

    def navigate_to_tab(self, tab_name):
        self.close_drawer()
        self._go_to("Task Screen")
        Clock.schedule_once(lambda dt: self._switch_tab_by_name(tab_name), 0.28)

    def _switch_tab_by_name(self, tab_name):
        tab_ids = {
            "Personal": self.root.ids.tab_personal,
            "Work":     self.root.ids.tab_work,
            "School":   self.root.ids.tab_school,
            "Other":    self.root.ids.tab_other,
        }
        if tab_name in tab_ids:
            self.switch_tab(tab_name, tab_ids[tab_name])

    def open_favorites(self):
        self.close_drawer()
        Clock.schedule_once(lambda dt: (
            self._go_to("Favorites Screen"),
            self.refresh_favorites_screen()), 0.28)

    def open_trash(self):
        self.close_drawer()
        Clock.schedule_once(lambda dt: (
            self._go_to("Trash Screen"),
            self.refresh_trash_screen()), 0.28)

    def go_back(self):
        self._go_to("Task Screen")

    # ── Task bottom sheet ─────────────────────────────────────────
    def add_task(self):
        sheet = self.root.ids.task_bottom_sheet
        Animation(pos_hint={"center_x": 0.5, "y": 0}, duration=0.25).start(sheet)

    def close_task_sheet(self):
        sheet = self.root.ids.task_bottom_sheet
        Animation(pos_hint={"center_x": 0.5, "y": -1}, duration=0.25).start(sheet)

    def show_date_picker(self):
        d = MDDatePicker()
        d.bind(on_save=self.on_date_selected)
        d.open()

    def on_date_selected(self, instance, value, date_range):
        self.selected_date = str(value)

    def switch_tab(self, tab_name, tab_widget):
        self.active_tab = tab_name
        underline = self.root.ids.tab_underline
        Animation(x=tab_widget.x, width=tab_widget.width, duration=0.18).start(underline)
        self.root.ids.tab_manager.current = tab_name

    # ── Save task ─────────────────────────────────────────────────
    def save_task(self):
        task_text = self.root.ids.task_input.text.strip()
        if not task_text:
            return

    # Always generate task_id first
        task_id   = self._new_task_id()
        flag_btn   = self.root.ids.flag_btn
        flag_icon  = flag_btn.icon
        flag_color = list(flag_btn.icon_color)

        if self.current_screen == "Calendar Screen":
            if self.selected_date:
                d = datetime.strptime(self.selected_date, "%Y-%m-%d").date()
            else:
                d = date.today()
            date_key  = d.strftime("%Y-%m-%d")
            task_date = d.strftime("%b %d")

            self.calendar_tasks.setdefault(date_key, []).append({
                "text":       task_text,
                "flag_icon":  flag_icon,
                "flag_color": flag_color,
                "date":       task_date,
                "task_id":    task_id,
            })

            self._show_tasks_for_date(date_key, d.strftime("%B %d, %Y"))
            self.build_calendar()

            self.root.ids.task_input.text = ""
            flag_btn.icon       = "flag-outline"
            flag_btn.icon_color = (0.5, 0.5, 0.5, 1)
            self.selected_date  = ""
            self.close_task_sheet()

        else:
            d         = date.today()
            task_date = d.strftime("%b %d")
            date_key  = d.strftime("%Y-%m-%d")

            self.calendar_tasks.setdefault(date_key, []).append({
                "text":       task_text,
                "flag_icon":  flag_icon,
                "flag_color": flag_color,
                "date":       task_date,
                "task_id":    task_id,
            })


        # Refresh the calendar 

        # Build the task card — rest of your existing save_task code
            task_item = TaskCard(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(65),
                padding=[15, 8],
                spacing=dp(10),
                radius=[10],
                md_bg_color=self.task_card_color,
                task_id=task_id,
             )

            checkbox = MDCheckbox(
                size_hint=(None, None),
                size=(dp(30), dp(30)),
                pos_hint={"center_y": 0.5}
            )

            _dk = date_key
            def on_cb(cb, val, dk=_dk):
                if val:                                                          
                    self.daily_completions[dk] = self.daily_completions.get(dk, 0) + 1
                    self.play_completion_tone()
                else:
                    self.daily_completions[dk] = max(0, self.daily_completions.get(dk, 0) - 1)
                    self._schedule_stats()

            checkbox.bind(active=on_cb)

            text_box = MDBoxLayout(
                orientation="vertical",
                spacing=dp(2),
                pos_hint={"center_y": 0.5}
            )
            title_label = MDLabel(
                text=task_text,
                theme_text_color="Custom",
                text_color=self.text_primary,
                font_size=dp(15),
                bold=True,
                size_hint_y=None,
                height=dp(22)
            )
            date_label_w = MDLabel(
                text=task_date,
                theme_text_color="Custom",
                text_color=(1, 0.2, 0.2, 1),
                font_size=dp(12),
                size_hint_y=None,
                height=dp(18)
            )
            flag_label = MDIcon(
                icon=flag_icon,
                theme_text_color="Custom",
                text_color=flag_color,
                size_hint=(None, None),
                size=(dp(24), dp(24)),
                pos_hint={"center_y": 0.5}
            )
            pin_icon = MDIcon(
                icon="pin",
                theme_text_color="Custom",
                text_color=(0.2, 0.2, 0.2, 1),
                size_hint=(None, None),
                size=(dp(0), dp(20)),
                pos_hint={"center_y": 0.5},
                opacity=0
            )
            fav_icon = MDIcon(
                icon="star",
                theme_text_color="Custom",
                text_color=(1, 0.75, 0, 1),
                size_hint=(None, None),
                size=(dp(0), dp(20)),
                pos_hint={"center_y": 0.5},
                opacity=0
            )

            text_box.add_widget(title_label)
            text_box.add_widget(date_label_w)
            task_item.add_widget(checkbox)
            task_item.add_widget(text_box)
            task_item.add_widget(Widget())
            task_item.add_widget(fav_icon)
            task_item.add_widget(pin_icon)
            task_item.add_widget(flag_label)

            self.task_registry[task_id] = {
                "text":        task_text,
                "date":        task_date,
                "flag_icon":   flag_icon,
                "flag_color":  flag_color,
                "pinned":      False,
                "favorited":   False,
                "tab":         self.active_tab,
                "widget":      task_item,
                "pin_icon":    pin_icon,
                "fav_icon":    fav_icon,
                "title_label": title_label,
            }

            task_item.bind(on_long_press=lambda inst, touch, tid=task_id:
                
            self.show_task_context_menu(tid, touch))

            self.task_lists[self.active_tab].add_widget(task_item)

            self.root.ids.task_input.text  = ""
            flag_btn.icon                  = "flag-outline"
            flag_btn.icon_color            = (0.5, 0.5, 0.5, 1)
            self.selected_date             = ""
            self.selected_priority         = "No priority"
            self.selected_repeat           = "Do not repeat"

            self._schedule_stats()
            self.close_task_sheet()
    # ── Context menu (long press) ─────────────────────────────────
    def show_task_context_menu(self, task_id, touch):
        task = self.task_registry.get(task_id)
        if not task:
            return

        popup_w = dp(220)
        popup_h = dp(232)
        win_w   = Window.width
        win_h   = Window.height
        widget  = task["widget"]
        wx, wy  = widget.to_window(*widget.pos)
        px = max(dp(8), min(wx + widget.width - popup_w, win_w - popup_w - dp(8)))
        py = wy - popup_h - dp(4)
        if py < dp(8):
            py = wy + widget.height + dp(4)
        py = min(py, win_h - popup_h - dp(8))

        modal = ModalView(
            size_hint=(1, 1),
            background_color=(0, 0, 0, 0),
            overlay_color=(0, 0, 0, 0.25),
            auto_dismiss=True,
        )
        fl        = FloatLayout()
        container = MDBoxLayout(
            orientation="vertical",
            md_bg_color=(1, 1, 1, 1),
            radius=[14],
            padding=[0, dp(6)],
            size_hint=(None, None),
            size=(popup_w, popup_h),
            pos=(px, py),
        )

        is_pinned    = task["pinned"]
        is_favorited = task["favorited"]

        def _row(icon_name, label, cb):
            btn = MDBoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(52),
                padding=[dp(18), 0],
                spacing=dp(18),
            )
            
            btn.add_widget(MDIcon(
                icon=icon_name,
                theme_text_color="Custom",
                text_color=(0.2, 0.2, 0.2, 1),
                size_hint=(None, None),
                size=(dp(24), dp(24)),
                pos_hint={"center_y": 0.5},
            ))
            btn.add_widget(MDLabel(
                text=label,
                font_size=dp(15),
                theme_text_color="Custom",
                text_color=(0.1, 0.1, 0.1, 1),
                valign="center",
            ))
            def _touch(inst, t):
                if inst.collide_point(*t.pos):
                    modal.dismiss()
                    cb()
                    return True
            btn.bind(on_touch_down=_touch)
            return btn

        container.add_widget(_row(
            "pin-off" if is_pinned else "pin",
            "Unpin"            if is_pinned    else "Pin",
            lambda: self._ctx_pin(task_id)))
        container.add_widget(_row(
            "star"             if is_favorited else "star-outline",
            "Remove Favorites" if is_favorited else "Add to Favorites",
            lambda: self._ctx_favorite(task_id)))
        container.add_widget(_row("delete-outline",        "Delete", lambda: self._ctx_delete(task_id)))
        container.add_widget(_row("share-variant-outline", "Share",  lambda: self._ctx_share(task_id)))

        fl.add_widget(container)
        modal.add_widget(fl)
        self._ctx_modal = modal
        modal.open()

    def _ctx_pin(self, task_id):
        task = self.task_registry.get(task_id)
        if not task:
            return
        task["pinned"] = not task["pinned"]
        pin = task["pin_icon"]
        if task["pinned"]:
            pin.width   = dp(22)
            pin.opacity = 1
        # Only move to top if it's a task screen task, not calendar
            if task["tab"] != "calendar":
                tl = self.task_lists[task["tab"]]
                w  = task["widget"]
                tl.remove_widget(w)
                tl.add_widget(w)
        else:
            pin.width   = dp(0)
            pin.opacity = 0
        self._schedule_stats()

    def _ctx_favorite(self, task_id):
        task = self.task_registry.get(task_id)
        if not task:
            return
        task["favorited"] = not task["favorited"]
        fav = task["fav_icon"]
        if task["favorited"]:
            fav.width   = dp(22)
            fav.opacity = 1
            if task_id not in self.favorites_list:
                self.favorites_list.append(task_id)
        else:
            fav.width   = dp(0)
            fav.opacity = 0
            if task_id in self.favorites_list:
                self.favorites_list.remove(task_id)

    def _ctx_delete(self, task_id):
        task = self.task_registry.get(task_id)
        if not task:
            return
        if task["tab"] != "calendar":
            tl = self.task_lists[task["tab"]]
            w  = task["widget"]
            if w in tl.children:
                tl.remove_widget(w)
        else:
        # Remove from calendar task list widget
            tl = self.root.ids.calendar_task_list
            w  = task["widget"]
            if w in tl.children:
                tl.remove_widget(w)
        if task_id in self.favorites_list:
            self.favorites_list.remove(task_id)
        if task_id not in self.trash_list:
            self.trash_list.append(task_id)
        self._schedule_stats()

    def _ctx_share(self, task_id):
        task = self.task_registry.get(task_id)
        if not task:
            return
        try:
            from android import mActivity
            from jnius import autoclass
            Intent = autoclass('android.content.Intent')
            String  = autoclass('java.lang.String')
            intent  = Intent()
            intent.setAction(Intent.ACTION_SEND)
            intent.putExtra(Intent.EXTRA_TEXT, String(task["text"]))
            intent.setType("text/plain")
            mActivity.startActivity(Intent.createChooser(intent, String("Share task")))
        except Exception:
            print(f"Share: {task['text']}")

    # ── Favorites screen ──────────────────────────────────────────
    def refresh_favorites_screen(self):
        try:
            fav_list  = self.root.ids.favorites_task_list
            fav_empty = self.root.ids.favorites_empty_label
            fav_list.clear_widgets()
            active = [tid for tid in self.favorites_list
                      if tid in self.task_registry and tid not in self.trash_list]
            fav_empty.opacity = 0 if active else 1
            for tid in active:
                task = self.task_registry[tid]
                item = MDBoxLayout(
                    orientation="horizontal",
                    size_hint_y=None,
                    height=dp(65),
                    padding=[15, 8],
                    spacing=dp(10),
                    radius=[10],
                    md_bg_color=self.task_card_color
                )
                item.add_widget(MDIcon(
                    icon="star",
                    theme_text_color="Custom",
                    text_color=(1, 0.8, 0, 1),
                    size_hint=(None, None),
                    size=(dp(24), dp(24)),
                    pos_hint={"center_y": 0.5}
                ))
                item.add_widget(MDLabel(
                    text=task["text"],
                    theme_text_color="Custom",
                    text_color=self.text_primary,
                    font_size=dp(15),
                    bold=True
                ))
                fav_list.add_widget(item)
        except Exception as e:
            print("Favorites refresh error:", e)

    # ── Trash screen ──────────────────────────────────────────────
    def refresh_trash_screen(self):
        try:
            trash_w = self.root.ids.trash_task_list
            empty_l = self.root.ids.trash_empty_label
            trash_w.clear_widgets()
            empty_l.opacity = 1 if not self.trash_list else 0
            for tid in self.trash_list:
                task = self.task_registry.get(tid)
                if not task:
                    continue
                item = MDBoxLayout(
                    orientation="horizontal",
                    size_hint_y=None,
                    height=dp(65),
                    padding=[15, 8],
                    spacing=dp(10),
                    radius=[10],
                    md_bg_color=self.task_card_color
                )
                restore_btn = MDIcon(
                    icon="restore",
                    theme_text_color="Custom",
                    text_color=(0.2, 0.6, 1, 1),
                    size_hint=(None, None),
                    size=(dp(24), dp(24)),
                    pos_hint={"center_y": 0.5}
                )

                def _restore_touch(inst, t, tid_=tid):
                    if inst.collide_point(*t.pos):
                        self._restore_from_trash(tid_)
                restore_btn.bind(on_touch_down=_restore_touch)

                item.add_widget(MDIcon(
                    icon="delete-outline",
                    theme_text_color="Custom",
                    text_color=(0.7, 0.3, 0.3, 1),
                    size_hint=(None, None),
                    size=(dp(24), dp(24)),
                    pos_hint={"center_y": 0.5}
                ))
                item.add_widget(MDLabel(
                    text=task["text"],
                    theme_text_color="Custom",
                    text_color=self.text_secondary,
                    font_size=dp(15),
                    italic=True
                ))
                item.add_widget(Widget())
                item.add_widget(restore_btn)
                trash_w.add_widget(item)
        except Exception as e:
            print("Trash refresh error:", e)

    def _restore_from_trash(self, task_id):
        task = self.task_registry.get(task_id)
        if not task:
            return
        if task_id in self.trash_list:
            self.trash_list.remove(task_id)
        tl = self.task_lists[task["tab"]]
        w  = task["widget"]
        if w not in tl.children:
            tl.add_widget(w)
        self.refresh_trash_screen()
        self._schedule_stats()

    # ── Stats — coalesced updates ─────────────────────────────────
    def _schedule_stats(self):
        """Collapse rapid successive stat-update requests into one call."""
        if self._stats_pending:
            self._stats_pending.cancel()
        self._stats_pending = Clock.schedule_once(self._do_update_stats, 0.08)

    def _do_update_stats(self, dt):
        self._stats_pending = None
        self.update_stats()

    def get_stats(self):
        pending = completed = 0
        for tl in self.task_lists.values():
            for card in tl.children:
                for child in card.children:
                    if hasattr(child, 'active'):
                        if child.active:
                            completed += 1
                        else:
                            pending += 1
        return pending, completed

    def get_category_stats(self):
        return {tab: len(tl.children)
                for tab, tl in self.task_lists.items()
                if tl.children}

    def update_stats(self):
        if self.current_screen != "Statistics":
            # Still update counts for drawer, but skip expensive chart draws
            self.update_category_counts()
            return
        try:
            pending, completed = self.get_stats()
            self.root.ids.stats_pending.text   = str(pending)
            self.root.ids.stats_completed.text = str(completed)
            self.update_pie_chart()
            self.update_bar_chart()
            self.update_category_counts()
        except Exception as e:
            print("Stats error:", e)

    def update_category_counts(self):
        try:
            self.count_personal = len(self.task_lists["Personal"].children)
            self.count_work     = len(self.task_lists["Work"].children)
            self.count_school   = len(self.task_lists["School"].children)
            self.count_other    = len(self.task_lists["Other"].children)
            self.count_all      = (self.count_personal + self.count_work +
                                   self.count_school + self.count_other)
        except Exception as e:
            print("Category count error:", e)

    def update_pie_chart(self):
        stats  = self.get_category_stats()
        total  = sum(stats.values()) if stats else 0
        colors = self._CAT_COLORS
        try:
            pie = self.root.ids.pie_chart
            pie.canvas.after.clear()
            cx = pie.center_x
            cy = pie.center_y
            r  = min(pie.width, pie.height) / 2 - dp(5)
            with pie.canvas.after:
                if total == 0:
                    Color(0.85, 0.85, 0.85, 1)
                    Ellipse(pos=(cx - r, cy - r), size=(r * 2, r * 2))
                else:
                    start = 0.0
                    for cat, count in stats.items():
                        angle = (count / total) * 360
                        Color(*colors[cat])
                        Ellipse(pos=(cx - r, cy - r), size=(r * 2, r * 2),
                                angle_start=start, angle_end=start + angle)
                        start += angle
                ir = r * 0.55
                Color(*self.surface_color)
                Ellipse(pos=(cx - ir, cy - ir), size=(ir * 2, ir * 2))
            legend = self.root.ids.pie_legend
            legend.clear_widgets()
            for cat, count in stats.items():
                row = MDBoxLayout(orientation="horizontal",
                                  size_hint_y=None, height=dp(25), spacing=dp(8))
                row.add_widget(MDBoxLayout(
                    size_hint=(None, None), size=(dp(14), dp(14)),
                    radius=[7], md_bg_color=colors[cat],
                    pos_hint={"center_y": 0.5}))
                row.add_widget(MDLabel(
                    text=f"{cat}  {count}", font_size=dp(13),
                    theme_text_color="Custom", text_color=self.text_primary))
                legend.add_widget(row)
        except Exception as e:
            print("Pie error:", e)

    def _get_week_bounds(self):
        today = date.today()
        days_since_sunday = (today.weekday() + 1) % 7
        sunday = today - timedelta(days=days_since_sunday)
        start  = sunday + timedelta(weeks=self.stats_week_offset)
        return start, start + timedelta(days=6)

    def update_bar_chart(self):
        try:
            chart      = self.root.ids.bar_chart
            week_label = self.root.ids.bar_chart_week_label
            chart.canvas.after.clear()

            week_start, week_end = self._get_week_bounds()
            week_label.text = (f"{week_start.strftime('%-m/%-d')} - "
                               f"{week_end.strftime('%-m/%-d')}")

            day_keys = [(week_start + timedelta(days=i)).strftime("%Y-%m-%d")
                        for i in range(7)]
            counts   = [self.daily_completions.get(k, 0) for k in day_keys]
            max_cnt  = max(counts) if any(counts) else 0

            cw = chart.width;  ch = chart.height
            pl = dp(32); pr = dp(10); pt = dp(12); pb = dp(12)
            dw = cw - pl - pr;  dh = ch - pt - pb

            slot_w = dw / 7
            bar_w  = slot_w * 0.5
            y_max  = max(max_cnt + (max_cnt % 2), 8)
            n_lines = y_max // 2 + 1
            ax = chart.x + pl
            by = chart.y + pb
            today = date.today()

            with chart.canvas.after:
                # Axes
                Color(0.55, 0.60, 0.68, 1)
                Rectangle(pos=(ax, by), size=(dw, dp(1.5)))
                Rectangle(pos=(ax, by), size=(dp(1.5), dh))

                # Y-axis labels — reuse cached textures
                for i in range(n_lines):
                    val = i * 2
                    y   = by + (val / y_max) * dh
                    key = val
                    if key not in self._bar_label_cache:
                        lbl = CoreLabel(text=str(val), font_size=dp(10),
                                        color=(0.4, 0.4, 0.5, 1))
                        lbl.refresh()
                        self._bar_label_cache[key] = lbl.texture
                    tex = self._bar_label_cache[key]
                    tw, th = tex.size
                    Color(1, 1, 1, 1)
                    Rectangle(texture=tex,
                              pos=(ax - tw - dp(4), y - th / 2),
                              size=(tw, th))

                # Bars
                for i, (count, dk) in enumerate(zip(counts, day_keys)):
                    if count <= 0:
                        continue
                    cx2   = ax + slot_w * i + slot_w / 2
                    bar_x = cx2 - bar_w / 2
                    bar_h = (count / y_max) * dh
                    d     = week_start + timedelta(days=i)
                    Color(0.1, 0.5, 1, 1) if d == today else Color(0.35, 0.65, 1, 0.9)
                    RoundedRectangle(
                        pos=(bar_x, by + dp(2)),
                        size=(bar_w, bar_h),
                        radius=[dp(4), dp(4), 0, 0]
                    )
        except Exception as e:
            print("Bar chart error:", e)

    def stats_prev_week(self):
        self.stats_week_offset -= 1
        Clock.schedule_once(lambda dt: self.update_bar_chart(), 0.04)

    def stats_next_week(self):
        self.stats_week_offset += 1
        Clock.schedule_once(lambda dt: self.update_bar_chart(), 0.04)

    # ── Calendar ──────────────────────────────────────────────────
    def build_calendar(self):
        try:
            grid = self.root.ids.calendar_grid
        except Exception:
            return
        grid.clear_widgets()
        today = date.today()
        self.current_month_label = datetime(
            self.cal_year, self.cal_month, 1).strftime("%B %Y").upper()
        first_dow    = (cal.monthrange(self.cal_year, self.cal_month)[0] + 1) % 7
        days_in_month = cal.monthrange(self.cal_year, self.cal_month)[1]

        # Empty leading cells
        for _ in range(first_dow):
            b = Factory.DayButton(); b.day = 0
            grid.add_widget(b)

        for day in range(1, days_in_month + 1):
            b            = Factory.DayButton()
            b.day        = day
            b.is_today   = (day == today.day and
                            self.cal_month == today.month and
                            self.cal_year  == today.year)
            b.is_selected = (day == self.selected_day)
            dk            = f"{self.cal_year}-{self.cal_month:02d}-{day:02d}"
            b.has_task    = dk in self.calendar_tasks
            grid.add_widget(b)

    def prev_month(self):
        if self.calendar_view == "week":
            self.week_offset -= 1; self.build_week_view()
        else:
            if self.cal_month == 1:
                self.cal_month = 12; self.cal_year -= 1
            else:
                self.cal_month -= 1
            self.selected_day = 0; self.build_calendar()

    def next_month(self):
        if self.calendar_view == "week":
            self.week_offset += 1; self.build_week_view()
        else:
            if self.cal_month == 12:
                self.cal_month = 1; self.cal_year += 1
            else:
                self.cal_month += 1
            self.selected_day = 0; self.build_calendar()

    def select_day(self, day):
        self.selected_day = day
        self.build_calendar()
        dk = f"{self.cal_year}-{self.cal_month:02d}-{day:02d}"
        self._show_tasks_for_date(
            dk, datetime(self.cal_year, self.cal_month, day).strftime("%B %d, %Y"))

    def _show_tasks_for_date(self, date_key, label_text):
        try:            
            selected_label = self.root.ids.selected_date_label
            tl       = self.root.ids.calendar_task_list
            no_tasks = self.root.ids.no_tasks_label
            tl.clear_widgets()
            tasks = self.calendar_tasks.get(date_key, [])

            if tasks:
                
                selected_label.text = label_text
                no_tasks.opacity = 0
                for task in tasks:
                    task_id  = task.get("task_id", self._new_task_id())
                    task_item = TaskCard(
                        orientation="horizontal",
                        size_hint_y=None,
                        height=dp(65),
                        padding=[15, 8],
                        spacing=dp(10),
                        radius=[10],
                        md_bg_color=self.task_card_color,
                        task_id=task_id,
                    )
                    checkbox = MDCheckbox(
                        size_hint=(None, None),
                        size=(dp(30), dp(30)),
                        pos_hint={"center_y": 0.5}
                    )
                    def on_cb(cb, val, dk=date_key):
                        if val:
                            self.daily_completions[dk] = self.daily_completions.get(dk, 0) + 1
                            self.play_completion_tone()
                        else:
                            self.daily_completions[dk] = max(0,             self.daily_completions.get(dk, 0) - 1)
                            self._schedule_stats()
                    checkbox.bind(active=on_cb)

                    text_box = MDBoxLayout(
                        orientation="vertical",
                        spacing=dp(2),
                        pos_hint={"center_y": 0.5}
                    )
                    title_label = MDLabel(
                        text=task["text"],
                        theme_text_color="Custom",
                        text_color=self.text_primary,
                        font_size=dp(15),
                        bold=True,
                        size_hint_y=None,
                        height=dp(22)
                    )
                    date_label_w = MDLabel(
                        text=task.get("date", date_key),
                        theme_text_color="Custom",
                        text_color=(1, 0.2, 0.2, 1),
                        font_size=dp(12),
                        size_hint_y=None,
                        height=dp(18)
                    )
                    flag_label = MDIcon(
                        icon=task["flag_icon"],
                        theme_text_color="Custom",
                        text_color=task["flag_color"],
                        size_hint=(None, None),
                        size=(dp(24), dp(24)),
                        pos_hint={"center_y": 0.5}
                    )
                    pin_icon = MDIcon(
                        icon="pin",
                        theme_text_color="Custom",
                        text_color=(0.2, 0.2, 0.2, 1),
                        size_hint=(None, None),
                        size=(dp(0), dp(20)),
                        pos_hint={"center_y": 0.5},
                        opacity=0
                    )
                    fav_icon = MDIcon(
                        icon="star",
                        theme_text_color="Custom",
                        text_color=(1, 0.75, 0, 1),
                        size_hint=(None, None),
                        size=(dp(0), dp(20)),
                        pos_hint={"center_y": 0.5},
                        opacity=0
                    )
                    text_box.add_widget(title_label)
                    text_box.add_widget(date_label_w)
                    task_item.add_widget(checkbox)
                    task_item.add_widget(text_box)
                    task_item.add_widget(Widget())
                    task_item.add_widget(fav_icon)
                    task_item.add_widget(pin_icon)
                    task_item.add_widget(flag_label)

                # Register in task_registry if not already there
                    if task_id not in self.task_registry:
                        self.task_registry[task_id] = {
                            "text":        task["text"],
                            "date":        task.get("date", date_key),
                            "flag_icon":   task["flag_icon"],
                            "flag_color":  task["flag_color"],
                            "pinned":      self.task_registry.get(task_id, {}).get("pinned", False),
                            "favorited":   self.task_registry.get(task_id, {}).get("favorited", False),
                            "tab":         "calendar",
                            "widget":      task_item,
                            "pin_icon":    pin_icon,
                            "fav_icon":    fav_icon,
                            "title_label": title_label,
                        }

                    task_item.bind(on_long_press=lambda inst, touch, tid=task_id:
                               self.show_task_context_menu(tid, touch))
                    tl.add_widget(task_item)
            else:
                selected_label.text = "Tap a date to see tasks"
                no_tasks.opacity = 1

        except Exception as e:
            print("Show tasks error:", e)
        
    def toggle_calendar_view(self):
        if self.calendar_view == "month":
            self.calendar_view = "week"
            self.week_offset   = 0
            self.build_week_view()
        else:
            self.calendar_view = "month"
            self.build_calendar()

    def build_week_view(self):
        try:
            grid = self.root.ids.calendar_grid
        except Exception:
            return
        grid.clear_widgets()
        grid.cols = 7
        today         = date.today()
        start_offset  = (today.weekday() + 1) % 7
        week_start    = today - timedelta(days=start_offset) + timedelta(weeks=self.week_offset)
        week_end      = week_start + timedelta(days=6)
        self.current_month_label = (
            f"{week_start.strftime('%b %d')} - {week_end.strftime('%b %d, %Y')}".upper())
        for i in range(7):
            d          = week_start + timedelta(days=i)
            b          = Factory.WeekDayButton()
            b.day_num  = f"{d.day:02d}"
            b.day_name = d.strftime("%a")
            b.is_today = (d == today)
            b.date_key = d.strftime("%Y-%m-%d")
            grid.add_widget(b)

    def select_day_from_key(self, date_key):
        y, m, d = (int(p) for p in date_key.split("-"))
        self.cal_year = y; self.cal_month = m; self.selected_day = d
        self._show_tasks_for_date(
            date_key, datetime(y, m, d).strftime("%B %d, %Y"))

    # ── Priority / Repeat menus ───────────────────────────────────
    def show_priority_menu(self):
        caller = self.root.ids.flag_btn
        items  = [
            {"viewclass": "PriorityItem", "icon": "flag",
             "icon_color": self._PRIORITY_COLORS["Important"],
             "text": "Important", "height": dp(48),
             "on_release": lambda: self.set_priority_dialog("Important")},
            {"viewclass": "PriorityItem", "icon": "flag",
             "icon_color": self._PRIORITY_COLORS["Urgent"],
             "text": "Urgent", "height": dp(48),
             "on_release": lambda: self.set_priority_dialog("Urgent")},
            {"viewclass": "PriorityItem", "icon": "flag",
             "icon_color": self._PRIORITY_COLORS["Long-term"],
             "text": "Long-term", "height": dp(48),
             "on_release": lambda: self.set_priority_dialog("Long-term")},
            {"viewclass": "PriorityItem", "icon": "flag-outline",
             "icon_color": self._PRIORITY_COLORS["No priority"],
             "text": "No priority", "height": dp(48),
             "on_release": lambda: self.set_priority_dialog("No priority")},
        ]
        self.priority_menu = MDDropdownMenu(
            caller=caller, items=items,
            width_mult=3, position="top", max_height=dp(220))
        self.priority_menu.open()

    def set_priority_dialog(self, priority):
        btn = self.root.ids.flag_btnp
        btn.icon_color      = self._PRIORITY_COLORS[priority]
        btn.icon            = self._PRIORITY_ICONS[priority]
        self.selected_priority = priority
        self.priority_menu.dismiss()

    def show_repeat_menu(self):
        caller = self.root.ids.repeat_btn
        items  = [
            {"viewclass": "OneLineListItem", "text": t, "height": dp(48),
             "on_release": lambda x=t: self.set_repeat(x)}
            for t in ("Daily", "Weekly", "Monthly", "Do not repeat")
        ]
        self.repeat_menu = MDDropdownMenu(
            caller=caller, items=items,
            width_mult=3, position="top", max_height=dp(220))
        self.repeat_menu.open()

    def set_repeat(self, repeat):
        self.root.ids.repeat_btn.icon_color = (
            (0.2, 0.6, 1, 1) if repeat != "Do not repeat" else (0.3, 0.3, 0.3, 1))
        self.selected_repeat = repeat
        self.repeat_menu.dismiss()

    # ── Build ─────────────────────────────────────────────────────
    def build(self):
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.theme_style     = "Light"
        Window.softinput_mode          = "pan"
        return Builder.load_file("realapp.kv")


if __name__ == "__main__":
    MainApp().run()
