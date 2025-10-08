import os, time, sys
os.putenv('SDL_VIDEODRIVER', 'fbcon')
os.putenv('SDL_FBDEV', '/dev/fb1')
import pgzrun, pygame, pytmx
import pgzero.music as music
from pgzero.loaders import sounds
from functools import lru_cache


# === KONSTANSOK ===
WIDTH, HEIGHT = 320, 240
TILE_SIZE = 16
MOVEMENT_COOLDOWN = 0.15
DEBUG_MODE_ON = False

SCORE = 0  # Pontszám
HAS_KEY = False  # Kulcs

# Játék állapotok
STATE_LOGO = 0
STATE_TITLE = 1
STATE_GAME = 2
STATE_GAME_OVER = 3
STATE_END = 4
STATE_CREDITS = 5

# Játékszintek sorrendje
LEVEL_SEQUENCE = [
    "level_1",
    "level_2",
    "level_3",
    "level_4",
    "level_5",
    "level_6",
    "level_7",
    "level_8",
    "level_9",
    "level_boss",
]

# Színek
RETRO_BROWN = (88, 68, 34)
RETRO_GREEN = (120, 164, 106)
RETRO_CREAM = (212, 210, 155)

# RECT téglalapok foglalása
_temp_rect = pygame.Rect(0, 0, TILE_SIZE, TILE_SIZE)  # 16*16 px
_camera_rect = pygame.Rect(0, 0, WIDTH, HEIGHT)  # 320*240 px


# === GPIO ===
try:
    import RPi.GPIO as GPIO

    GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    GPIO_AVAILABLE = False
    print("GPIO nem elérhető")


class InputHandler:
    def __init__(self):
        self.gpio_enabled = False
        self.gpio_pins = {
            "LEFT": None,
            "RIGHT": None,
            "UP": None,
            "DOWN": None,
            "A": None,
            "B": None,
            "SELECT": None,
            "START": None,
        }

        if GPIO_AVAILABLE:
            self._load_gpio_config()

    def _load_gpio_config(self):
        try:
            with open("data/gpio.txt", "r") as file:
                lines = [line.strip() for line in file.readlines()]

            if len(lines) >= 8:
                button_names = [
                    "LEFT",
                    "RIGHT",
                    "UP",
                    "DOWN",
                    "A",
                    "B",
                    "SELECT",
                    "START",
                ]

                for i, button in enumerate(button_names):
                    try:
                        pin_num = int(lines[i])
                        self.gpio_pins[button] = pin_num
                    except ValueError:
                        print(f"Invalid pin {button}: {lines[i]}")

                # GPIO inicializálása
                GPIO.setmode(GPIO.BCM)
                for pin in self.gpio_pins.values():
                    if pin is not None:
                        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

                self.gpio_enabled = True
                print(f"GPIO pinek: {self.gpio_pins}")
            else:
                print("GPIO config file hiányos")

        except FileNotFoundError:
            print("data/gpio.txt nem található - GPIO disabled")
        except Exception as e:
            print(f"{e}")

    def is_pressed(self, button_name):
        if self.gpio_enabled and self.gpio_pins.get(button_name) is not None:
            pin = self.gpio_pins[button_name]
            return not GPIO.input(pin)

        if button_name == "LEFT":
            return keyboard.left
        elif button_name == "RIGHT":
            return keyboard.right
        elif button_name == "UP":
            return keyboard.up
        elif button_name == "DOWN":
            return keyboard.down
        elif button_name == "A":
            return keyboard.space
        elif button_name == "B":
            return keyboard.RETURN
        elif button_name == "SELECT":
            return keyboard.d
        elif button_name == "START":
            return keyboard.p

        return False

    def cleanup(self):
        if self.gpio_enabled:
            GPIO.cleanup()


# Create global input handler
input_handler = InputHandler()

# === HIGH SCORE ===
@lru_cache(maxsize=1)
def load_high_score():
    try:
        with open("data/highscore.txt", "r") as file:
            return int(file.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def save_high_score(score):
    try:
        os.makedirs("data", exist_ok=True)
        with open("data/highscore.txt", "w") as file:
            file.write(str(score))
        # print(f"Highscore saved: {score}")
        load_high_score.cache_clear()
    except Exception as e:
        print(f"{e}")


HIGH_SCORE = load_high_score()


# === JÁTÉK ÁLLAPOTOK ===
class GameStateManager:
    def __init__(self):
        pygame.mouse.set_visible(False)  # Kurzor elrejtése
        self.current_state = STATE_LOGO
        self.game_paused = False
        self.level_loader = None

        # Logo állapot
        self.logo_timer = 0
        self.logo_duration = 3.0
        self.logo_sound_delay = 0.3
        self.logo_image = None
        self.logo_sound_played = False

        # Menü állapot
        self.title_image = None
        self.title_font_small = None
        self.title_font_large = None
        self.game_over_font = None

        # Victory
        self.victory_freeze = False  # Input befagyasztás
        self.victory_freeze_timer = 0
        self.victory_freeze_duration = 3.0

        self.credits_images = []
        self.credits_index = 0
        self.credits_timer = 0
        self.credits_duration = 3.0
        self.credits_total = 0

        # Képernyőátmenet
        self.transitioning = False
        self.transition_timer = 0
        self.transition_duration = 0.5
        self.transition_surface = pygame.Surface((WIDTH, HEIGHT)).convert_alpha()
        self.next_state = None

        # Time cache a System Call-ok csökkentésére
        self._last_time = time.time()

        # Grafikai elemek betöltése
        self._load_logo_assets()
        self._load_title_assets()

    # INICIALIZÁCIÓ
    def _load_logo_assets(self):
        try:
            self.logo_image = pygame.image.load("images/state_logo.png").convert_alpha()
        except Exception as e:
            print(f"{e}")

    def _load_title_assets(self):
        try:
            self.title_image = pygame.image.load(
                "images/state_title.png"
            ).convert_alpha()
        except Exception as e:
            print(f"{e}")

        try:
            self.title_font_small = pygame.font.Font("fonts/early_gameboy.ttf", 16)
            self.title_font_large = pygame.font.Font("fonts/early_gameboy.ttf", 24)
            self.game_over_font = pygame.font.Font("fonts/early_gameboy.ttf", 24)
        except Exception as e:
            print(f"{e}")

    def _load_credits(self):
        self.credits_images.clear()
        self.credits_index = 0
        self.credits_timer = time.time()

        # Képek keresése "credits_0.png"-től kezdve
        credits_count = 0
        for i in range(0, 10):  # 0-tól 9-ig ellenőriz
            try:
                image_path = f"images/credits_{i}.png"
                if os.path.exists(image_path):
                    credits_count += 1
                else:
                    break
            except Exception as e:
                print("{e}")
                break

        self.credits_total = credits_count

        if credits_count == 0:
            self._start_state_transition(STATE_TITLE)
            return
        try:
            music.play("end_theme_2")
        except:
            pass

    def _get_current_credits_image(self):
        if self.credits_index >= self.credits_total:
            return None

        try:
            image_path = f"images/credits_{self.credits_index}.png"
            image = pygame.image.load(image_path).convert_alpha()
            return image
        except Exception as e:
            print(f"{e}")
            return None

    # ÁLLAPOTKEZELÉS ÉS ÁTMENETEK
    def update(self):
        current_time = time.time()

        # Átmenetek kezelése
        if self.transitioning:
            elapsed = current_time - self.transition_timer
            if elapsed < self.transition_duration:
                self.transitioning = False
                self._change_state(self.next_state)
                self.next_state = None
            return

        # Aktuális állapot frissítése
        if self.current_state == STATE_LOGO:
            self._update_logo(current_time)
        elif self.current_state == STATE_TITLE:
            self._update_title(current_time)
        elif self.current_state == STATE_GAME:
            self._update_game(current_time)
        elif self.current_state == STATE_GAME_OVER:
            self._update_game_over(current_time)
        elif self.current_state == STATE_CREDITS:
            self._update_credits(current_time)

        self._last_time = current_time

    def _change_state(self, new_state):
        old_state = self.current_state
        self.current_state = new_state

        if new_state == STATE_LOGO:
            self.logo_sound_played = False
            self.logo_timer = 0

        elif new_state == STATE_TITLE:
            try:
                music.play("village")
            except:
                pass

        elif new_state == STATE_GAME and old_state != STATE_GAME:
            # Játék kezdő inicializálása vagy újraindítás
            if (
                not self.level_loader
                or old_state == STATE_GAME_OVER
                or (
                    self.level_loader
                    and self.level_loader.player
                    and self.level_loader.player.is_dead()
                )
            ):
                self.level_loader = LevelLoader(LEVEL_SEQUENCE)

                # Pontszám nullázása, kulcs item nullázása
                global SCORE, HAS_KEY
                SCORE = 0
                HAS_KEY = False

        elif new_state == STATE_CREDITS:
            self._load_credits()

    def _start_state_transition(self, new_state):
        if self.transitioning:
            return False

        self.transitioning = True
        self.transition_timer = time.time()
        self.next_state = new_state
        return True

    # UPDATE FÜGGVÉNYEK
    def _update_logo(self, current_time):
        if self.logo_timer == 0:
            self.logo_timer = current_time

        elapsed = current_time - self.logo_timer

        if not self.logo_sound_played and elapsed >= self.logo_sound_delay:
            sounds.gold_2.play()
            self.logo_sound_played = True

        if elapsed >= self.logo_duration:
            self._start_state_transition(STATE_TITLE)

    def _update_title(self, current_time):
        pass

    def _update_game(self, current_time):
        if self.victory_freeze:
            if current_time - self.victory_freeze_timer >= self.victory_freeze_duration:
                self.victory_freeze = False
                self._start_state_transition(STATE_CREDITS)

        if not self.game_paused and self.level_loader:
            self.level_loader.update()

            if self.level_loader.player and self.level_loader.player.is_dead():
                if (
                    self.level_loader.player.state == "dying"
                    and self.level_loader.player.anim.finished
                ):
                    self._start_state_transition(STATE_GAME_OVER)

    def _update_game_over(self, current_time):
        pass

    def _update_credits(self, current_time):
        if self.credits_index == 0:
            duration = 7.0
        else:
            duration = 3.0

        if current_time - self.credits_timer >= duration:
            self.credits_index += 1
            self.credits_timer = current_time

            if self.credits_index >= self.credits_total:
                self._start_state_transition(STATE_TITLE)

    # INPUT FÜGGVÉNYEK
    def handle_input(self):
        # ESC billentyű a kilépéshez (minden állapotban működik)
        if keyboard.ESCAPE:
            pygame.quit()
            sys.exit(0)

        # Átmenet alatt nincs input kezelés
        if self.transitioning:
            return

        # Állapot-specifikus input kezelés
        if self.current_state == STATE_TITLE:
            self._handle_title_input()
        elif self.current_state == STATE_GAME:
            self._handle_game_input()
        elif self.current_state == STATE_GAME_OVER:
            self._handle_game_over_input()
        elif self.current_state == STATE_CREDITS:
            self._handle_credits_input()

    def _handle_title_input(self):
        # Játék indítása (START), (A), vagy (B) lenyomására
        if (
            input_handler.is_pressed("START")
            or input_handler.is_pressed("A")
            or input_handler.is_pressed("B")
        ):
            sounds.accept_2.play()
            self._start_state_transition(STATE_GAME)
            time.sleep(0.2)

    def _handle_game_input(self):
        if keyboard.ESCAPE:
            pygame.quit()
            sys.exit(0)

        if input_handler.is_pressed("START"):
            self.toggle_pause()
            time.sleep(0.2)

        if self.victory_freeze:
            return

        if input_handler.is_pressed("SELECT"):
            self.toggle_debug_mode()
            time.sleep(0.2)

        # Input feldolgozás csak ha a játék nincs szüneteltetve
        if not self.game_paused and self.level_loader and self.level_loader.player:
            # Támadás
            if input_handler.is_pressed("A"):
                self.level_loader.player.start_attack()
                time.sleep(0.1)

            # Ajtó
            if input_handler.is_pressed("B"):
                self.level_loader.try_enter_door()
                time.sleep(0.2)

            # Mozgás (csak ha nem támad és nincs átmenet)
            player = self.level_loader.player
            if player.state != "attacking" and not self.level_loader.transitioning:

                if input_handler.is_pressed("LEFT") and not any(
                    [
                        input_handler.is_pressed("RIGHT"),
                        input_handler.is_pressed("UP"),
                        input_handler.is_pressed("DOWN"),
                    ]
                ):
                    self.level_loader.move_player(-1, 0)
                elif input_handler.is_pressed("RIGHT") and not any(
                    [
                        input_handler.is_pressed("LEFT"),
                        input_handler.is_pressed("UP"),
                        input_handler.is_pressed("DOWN"),
                    ]
                ):
                    self.level_loader.move_player(1, 0)
                elif input_handler.is_pressed("UP") and not any(
                    [
                        input_handler.is_pressed("LEFT"),
                        input_handler.is_pressed("RIGHT"),
                        input_handler.is_pressed("DOWN"),
                    ]
                ):
                    self.level_loader.move_player(0, -1)
                elif input_handler.is_pressed("DOWN") and not any(
                    [
                        input_handler.is_pressed("LEFT"),
                        input_handler.is_pressed("RIGHT"),
                        input_handler.is_pressed("UP"),
                    ]
                ):
                    self.level_loader.move_player(0, 1)

    def _handle_game_over_input(self):
        if keyboard.ESCAPE:  # Keep ESC as keyboard-only for development
            pygame.quit()
            sys.exit(0)

        if (
            input_handler.is_pressed("A")
            or input_handler.is_pressed("B")
            or input_handler.is_pressed("START")
        ):
            self._start_state_transition(STATE_TITLE)
            time.sleep(0.2)

    def _handle_credits_input(self):
        if (
            input_handler.is_pressed("A")
            or input_handler.is_pressed("B")
            or input_handler.is_pressed("START")
        ):
            self.credits_index += 1
            self.credits_timer = time.time()

            if self.credits_index >= self.credits_total:
                self._start_state_transition(STATE_TITLE)

            time.sleep(0.2)

        if keyboard.ESCAPE:  # Keep ESC as keyboard-only
            self._start_state_transition(STATE_TITLE)

    # DRAW FÜGGVÉNYEK
    def draw(self, screen):
        if self.current_state == STATE_LOGO:
            self._draw_logo(screen)
        elif self.current_state == STATE_TITLE:
            self._draw_title(screen)
        elif self.current_state == STATE_GAME:
            self._draw_game(screen)
        elif self.current_state == STATE_GAME_OVER:
            self._draw_game_over(screen)
        elif self.current_state == STATE_CREDITS:
            self._draw_credits(screen)

        # Átmenet overlay rajzolása (mindig utoljára)
        if self.transitioning:
            self._draw_transition(screen)

    def _draw_logo(self, screen):
        screen.fill((RETRO_BROWN))
        if self.logo_image:
            logo_rect = self.logo_image.get_rect(center=(WIDTH // 2, HEIGHT // 2))
            screen.blit(self.logo_image, logo_rect)

    def _draw_title(self, screen):
        global HIGH_SCORE
        screen.fill((RETRO_BROWN))

        # Főmenü háttérkép rajzolása
        if self.title_image:
            title_rect = self.title_image.get_rect(center=(WIDTH // 2, HEIGHT // 2))
            screen.blit(self.title_image, title_rect)

        # Szöveg felületek cache-elése (High Score)
        if (
            not hasattr(self, "_cached_high_score")
            or self._cached_high_score != HIGH_SCORE
        ):
            self._cached_high_score = HIGH_SCORE
            high_score_text = f"High Score: {HIGH_SCORE}"
            if self.title_font_small:
                self._cached_high_score_surface = self.title_font_small.render(
                    high_score_text, True, RETRO_GREEN
                )
                self._cached_high_score_rect = self._cached_high_score_surface.get_rect(
                    center=(WIDTH // 2, 160)
                )

        # Press Start with flashing effect (no caching since it changes)
        if self.title_font_large:
            # Flash on/off every 0.5 seconds
            if int(time.time() * 2) % 2:  # Changes every 0.5 seconds
                press_start_text = "PRESS START"
                press_start_surface = self.title_font_large.render(
                    press_start_text, True, RETRO_CREAM
                )
                press_start_rect = press_start_surface.get_rect(
                    center=(WIDTH // 2, 160 + 32)
                )
                screen.blit(press_start_surface, press_start_rect)

        # Cache-elt High Score rajzolása
        if hasattr(self, "_cached_high_score_surface"):
            screen.blit(self._cached_high_score_surface, self._cached_high_score_rect)

    def _draw_game(self, screen):
        if self.level_loader:
            self.level_loader.draw(screen)

            # Pause alatt elsötétítő overlay
            if self.game_paused and not self.victory_freeze:
                # Overlay cache-elése
                if not hasattr(self, "_pause_overlay"):
                    self._pause_overlay = pygame.Surface(
                        (WIDTH, HEIGHT)
                    ).convert_alpha()
                    self._pause_overlay.fill((0, 0, 0))
                    self._pause_overlay.set_alpha(96)
                screen.blit(self._pause_overlay, (0, 0))

            if self.game_paused and DEBUG_MODE_ON and not self.victory_freeze:
                if not hasattr(self, "_debug_pause_surf"):
                    self._debug_pause_surf = pygame.Surface((4, 4)).convert_alpha()
                    self._debug_pause_surf.fill((255, 255, 0))
                screen.blit(self._debug_pause_surf, (WIDTH - 8, 4))

    def _draw_game_over(self, screen):
        global SCORE, HIGH_SCORE
        screen.fill((RETRO_BROWN))

        # Szöveg felületek cache-elése (Game Over, High Score és pontszám, ha nem változott)
        if not hasattr(self, "_cached_game_over_surface"):
            game_over_text = "GAME OVER"
            if self.game_over_font:
                self._cached_game_over_surface = self.game_over_font.render(
                    game_over_text, True, RETRO_CREAM
                )
                self._cached_game_over_rect = self._cached_game_over_surface.get_rect(
                    center=(WIDTH // 2, HEIGHT // 2 - 30)
                )

        if (
            not hasattr(self, "_cached_go_high_score")
            or self._cached_go_high_score != HIGH_SCORE
        ):
            self._cached_go_high_score = HIGH_SCORE
            high_score_text = f"High Score: {HIGH_SCORE}"
            if self.title_font_small:
                self._cached_go_high_score_surface = self.title_font_small.render(
                    high_score_text, True, RETRO_CREAM
                )
                self._cached_go_high_score_rect = (
                    self._cached_go_high_score_surface.get_rect(
                        center=(WIDTH // 2, HEIGHT // 2 + 30)
                    )
                )

        if (
            not hasattr(self, "_cached_final_score")
            or self._cached_final_score != SCORE
        ):
            self._cached_final_score = SCORE
            score_text = f"Score: {SCORE}"
            if self.title_font_large:
                self._cached_final_score_surface = self.title_font_large.render(
                    score_text, True, RETRO_CREAM
                )
                self._cached_final_score_rect = (
                    self._cached_final_score_surface.get_rect(
                        center=(WIDTH // 2, HEIGHT // 2 + 10)
                    )
                )

        # Cache-elt GAME OVER rajzolása
        if hasattr(self, "_cached_game_over_surface"):
            screen.blit(self._cached_game_over_surface, self._cached_game_over_rect)

        # Cache-elt high score rajzolása
        if hasattr(self, "_cached_go_high_score_surface"):
            screen.blit(
                self._cached_go_high_score_surface, self._cached_go_high_score_rect
            )

        # Cache-elt pontszám rajzolása
        if hasattr(self, "_cached_final_score_surface"):
            screen.blit(self._cached_final_score_surface, self._cached_final_score_rect)

    def _draw_credits(self, screen):
        screen.fill(RETRO_BROWN)

        # Az utolsó kép után ne rajzoljon tovább
        if self.credits_index >= self.credits_total:
            return

        # Aktuális kép betöltése és rajzolása
        credits_image = self._get_current_credits_image()
        if credits_image:
            image_rect = credits_image.get_rect(center=(WIDTH // 2, HEIGHT // 2))
            screen.blit(credits_image, image_rect)
        else:
            print(f"ERROR loading credits_{self.credits_index}.png")

    def _draw_transition(self, screen):
        elapsed = time.time() - self.transition_timer
        progress = elapsed / self.transition_duration

        alpha = int(255 * progress)
        self.transition_surface.fill(RETRO_BROWN)
        self.transition_surface.set_alpha(alpha)
        screen.blit(self.transition_surface, (0, 0))

    # EGYÉB FÜGGVÉNYEK
    def _start_victory_freeze(self):
        if not self.victory_freeze:
            self.victory_freeze = True
            self.victory_freeze_timer = time.time()

    def _set_paused(self, paused):
        # Játékos animációk szüneteltetése
        if self.level_loader and self.level_loader.player:
            self.level_loader.player.set_paused(paused or self.victory_freeze)

        # Entity-k szüneteltetése
        if self.level_loader:
            self.level_loader.set_paused(paused or self.victory_freeze)

    def toggle_pause(self):
        # Szünet (PAUSE) kapcsolója
        if self.current_state == STATE_GAME:
            self.game_paused = not self.game_paused

    def toggle_debug_mode(self):
        # Debug kapcsoló
        global DEBUG_MODE_ON
        DEBUG_MODE_ON = not DEBUG_MODE_ON


class ObjectPool:
    # Object Pool memória allokáció csökkentésére
    # A gyakran létrehozott és törölt objektumokat újrahasznosítja, csökkentve a garbage collector terhelést
    def __init__(self, factory_func, initial_size=10):
        self.factory_func = factory_func  # Objektum gyártó függvény
        self.available = []  # Elérhető (szabad) objektumok
        self.in_use = []  # Használatban lévő objektumok

        # Objektumok létrehozása (pre-allocation)
        for _ in range(initial_size):
            self.available.append(factory_func())

    def get(self, *args, **kwargs):
        # Ha van szabad objektum, azt újrafelhasználja, ha nincs, újat hoz létre
        if self.available:
            # Van szabad objektum - újrafelhasználás
            obj = self.available.pop()

            # Objektum visszaállítása új paraméterekkel
            if hasattr(obj, "reset"):
                obj.reset(*args, **kwargs)

            # Áthelyezés a használatban lévő listába
            self.in_use.append(obj)
            return obj
        else:
            # ObjectPool kimerült - új objektum létrehozása
            obj = self.factory_func(*args, **kwargs)
            self.in_use.append(obj)
            return obj

    def return_object(self, obj):
        # Objektum visszaadása újrafelhasználásra
        if obj in self.in_use:
            # Eltávolítás a használatban lévő listából
            self.in_use.remove(obj)

            # Visszahelyezés a szabad objektumok közé
            self.available.append(obj)


# Globális ObjectPool gyakran használt objektumokhoz
_rect_pool = ObjectPool(lambda: pygame.Rect(0, 0, 0, 0), 20)

# === ANIMÁCIÓ KEZELŐ ===
class AnimationManager:
    # Osztály szintű cache-ek (minden példány számára közös)
    _sprite_cache = {}  # Globális cache az összes sprite sheet-hez
    _frame_cache = {}  # Cache a kivágott frame-ekhez
    _temp_surface = None  # Előre lefoglalt felület frame vágáshoz

    # INICIALIZÁCIÓ
    def __init__(self, spritesheet_path, tile_size=16, animations=None):
        self.tile_size = tile_size
        self.animations = animations or {}

        # Animáció állapot változók
        self.current_anim = None  # Aktuális animáció neve
        self.frame_idx = 0  # Aktuális frame index
        self.last_update = 0  # Utolsó frissítés időpontja
        self.finished = False  # Animáció befejeződött-e (nem loop esetén)
        self.paused = False

        # Sprite sheet betöltése cache-elés használatával
        if spritesheet_path not in AnimationManager._sprite_cache:
            try:
                loaded_sprite = pygame.image.load(spritesheet_path).convert_alpha()
                AnimationManager._sprite_cache[spritesheet_path] = loaded_sprite
            except pygame.error as e:
                print(f"{e}")
                # Tartalék felület létrehozása (magenta színű hibajelzés)
                fallback = pygame.Surface((tile_size * 4, tile_size * 4))
                fallback.fill((255, 0, 255))  # Magenta szín hiányzó sprite-okhoz
                AnimationManager._sprite_cache[spritesheet_path] = fallback

        # Cache-elt sprite sheet referencia tárolása
        self.spritesheet = AnimationManager._sprite_cache[spritesheet_path]

    # ANIMÁCIÓ VEZÉRLÉS
    def play(self, anim_name, reset=True):
        if anim_name not in self.animations:
            print(f"'{anim_name}' not found")
            return

        # Animáció indítása vagy váltása
        if self.current_anim != anim_name or reset:
            self.current_anim = anim_name
            self.frame_idx = 0
            self.last_update = time.time()
            self.finished = False

    def update(self):
        # Kilépés ha nincs mit frissíteni
        if not self.current_anim or self.finished or self.paused:
            return

        # Aktuális animáció adatainak lekérése
        anim = self.animations[self.current_anim]
        now = time.time()

        if now - self.last_update >= anim["duration"]:
            self.frame_idx += 1
            self.last_update = now

            # Frame szám ellenőrzése és loop/befejezés kezelése
            frame_count = len(anim["frames"])
            if self.frame_idx >= frame_count:
                if anim.get("loop", True):
                    # Loop animáció: vissza az elejére
                    self.frame_idx = 0
                else:
                    # Nem loopolt animáció: megállás az utolsó frame-en
                    self.frame_idx = frame_count - 1
                    self.finished = True

    def set_paused(self, paused):
        self.paused = paused

    def get_frame(self):
        if not self.current_anim:
            return None

        # Frame index számítás (túlindexelés elkerülése)
        frame_count = len(self.animations[self.current_anim]["frames"])
        safe_frame_idx = min(self.frame_idx, frame_count - 1)

        return self._get_frame(self.current_anim, safe_frame_idx)

    # CACHE KEZELÉS
    def _get_frame(self, anim_name, frame_idx):
        # Egyedi cache kulcs generálása
        # (spritesheet ID + animáció név + frame index kombinációja)
        cache_key = f"{id(self.spritesheet)}_{anim_name}_{frame_idx}"

        # Cache ellenőrzés: már létre van hozva ez a frame?
        if cache_key not in AnimationManager._frame_cache:
            try:
                # Frame koordináták kiszámítása az animáció definíció alapján
                row, col = self.animations[anim_name]["frames"][frame_idx]
                x, y = col * self.tile_size, row * self.tile_size

                # Subsurface használata
                frame = self.spritesheet.subsurface(
                    x, y, self.tile_size, self.tile_size
                )

                # Frame cache-elése
                AnimationManager._frame_cache[cache_key] = frame.convert_alpha()

            except (KeyError, IndexError, ValueError) as e:
                print(f"{e}")

                # Hiba esetén piros négyzet létrehozása hibajelzésként
                error_frame = pygame.Surface((self.tile_size, self.tile_size))
                error_frame.fill((255, 0, 0))
                AnimationManager._frame_cache[cache_key] = error_frame.convert_alpha()

        # Cache-elt frame visszaadása
        return AnimationManager._frame_cache[cache_key]

    # CLEANUP
    @classmethod
    def clear_caches(cls):
        # Összes cache törlése a memória felszabadításához
        cls._sprite_cache.clear()
        cls._frame_cache.clear()


# === JÁTÉKOS ===
class Player:
    # OSZTÁLY SZINTŰ KONSTANSOK
    # Karakter animációk definíciója
    ANIMATIONS = {
        "idle_right": {
            "frames": [(0, 0), (0, 1), (0, 2)],
            "duration": 0.6,
            "loop": True,
        },
        "idle_left": {
            "frames": [(1, 0), (1, 1), (1, 2)],
            "duration": 0.6,
            "loop": True,
        },
        "walk_right": {
            "frames": [(2, 0), (2, 1), (2, 2), (2, 3)],
            "duration": 0.6,
            "loop": True,
        },
        "walk_left": {
            "frames": [(3, 0), (3, 1), (3, 2), (3, 3)],
            "duration": 0.6,
            "loop": True,
        },
        "hurt_right": {
            "frames": [(4, 1), (4, 2), (4, 3), (4, 4), (4, 5)],
            "duration": 0.6,
            "loop": False,
        },
        "hurt_left": {
            "frames": [(5, 1), (5, 2), (5, 3), (5, 4), (5, 5)],
            "duration": 0.6,
            "loop": False,
        },
        "die_right": {
            "frames": [(6, 1), (6, 2), (6, 3)],
            "duration": 0.6,
            "loop": False,
        },
        "die_left": {
            "frames": [(7, 1), (7, 2), (7, 3)],
            "duration": 0.6,
            "loop": False,
        },
    }

    # Kard animációk definíciója
    SWORD_ANIMATIONS = {
        "attack_left": {
            "frames": [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)],
            "duration": 0.1,
            "loop": False,
        },
        "attack_right": {
            "frames": [(2, 0), (2, 1), (2, 2), (2, 3), (2, 4)],
            "duration": 0.1,
            "loop": False,
        },
    }

    # INICIALIZÁCIÓ ÉS SETUP
    def __init__(self, x, y):
        # Pozíció grid-re illesztése (tile-okra igazítás)
        self.x = (x // TILE_SIZE) * TILE_SIZE
        self.y = (y // TILE_SIZE) * TILE_SIZE
        self.facing = "right"
        self.last_move = 0
        self.health = 3
        self.max_health = 3
        self.state = "idle"
        self.state_timer = 0
        self.invincible_timer = 0

        # Rectangle cache-elése új objektumok létrehozásának elkerülésére
        self._rect = pygame.Rect(self.x, self.y, TILE_SIZE, TILE_SIZE)

        # Animáció kezelők inicializálása
        self.anim = AnimationManager("images/player.png", TILE_SIZE, self.ANIMATIONS)
        self.sword_anim = AnimationManager(
            "images/weapons_animated.png", 48, self.SWORD_ANIMATIONS
        )
        self.anim.play("idle_right")  # Kezdő animáció indítása
        self._last_update = (
            time.time()
        )  # Idő cache-elése a system call-ok csökkentésére

    # FŐ FRISSÍTÉSI CIKLUS ÉS ÁLLAPOT KEZELÉS
    def update(self):
        now = time.time()
        dt = now - self._last_update

        # Időzítők frissítése
        if self.invincible_timer > 0:
            self.invincible_timer = max(0, self.invincible_timer - dt)

        # Állapot gép (state machine)
        if self.state == "dying":
            if not self.anim.finished:
                self.anim.update()

        elif self.state == "hurt":
            if now - self.state_timer >= 1.0:
                self.state = "idle"
            self.anim.update()

        elif self.state == "attacking":
            if now - self.state_timer >= 0.5:
                self.state = "idle"
            # Kard és karakter animáció frissítése
            self.sword_anim.update()
            self.anim.update()

        else:
            # Idle/Moving állapot megfelelő animációjának kiválasztása
            if self.state in ["idle", "moving"]:
                anim_name = (
                    f"{'walk' if self.state == 'moving' else 'idle'}_{self.facing}"
                )
                self.anim.play(anim_name, False)  # Nem reseteljük ha már ez játszódik
            self.anim.update()

        self._last_update = now

    def set_paused(self, paused):
        self.anim.set_paused(paused)
        self.sword_anim.set_paused(paused)

    # MOZGÁS ÉS POZÍCIÓ KEZELÉS
    def move(self, dx, dy, level_width, level_height, current_time):
        # Mozgás csak egyenesen oldalra vagy le- vagy felfelé lehetséges
        # Mozgás blokkolása bizonyos állapotokban vagy cooldown alatt
        if self.state in ["attacking", "hurt", "dying"] or not self._can_move(
            current_time
        ):
            return False

        # Néző irány frissítése
        if dx > 0:
            self.facing = "right"
        elif dx < 0:
            self.facing = "left"

        # Új pozíció kiszámítása
        new_x = self.x + (dx * TILE_SIZE)
        new_y = self.y + (dy * TILE_SIZE)

        # Pálya határainak ellenőrzése
        if (
            0 <= new_x <= level_width - TILE_SIZE
            and 0 <= new_y <= level_height - TILE_SIZE
        ):
            self.x, self.y = new_x, new_y
            self._rect.x, self._rect.y = self.x, self.y

            # Mozgás állapot beállítása
            self.last_move = current_time
            self.state = "moving"
            return True
        return False

    def _can_move(self, current_time):
        return current_time - self.last_move >= MOVEMENT_COOLDOWN

    # HARC ÉS TÁMADÁS RENDSZER
    def start_attack(self):
        # Támadás blokkolása bizonyos állapotokban
        if self.state in ["attacking", "hurt", "dying"]:
            return False

        # Támadás állapot
        self.state = "attacking"
        self.state_timer = time.time()
        sounds.sword_2.play()

        # Kard animáció indítása
        self.sword_anim.play(f"attack_{self.facing}", True)
        return True

    # SEBZÉS RENDSZER
    def take_damage(self, damage=1):
        # Sebzés blokkolása sebzésállóság vagy speciális állapotok alatt
        if self.invincible_timer > 0 or self.state in ["hurt", "dying"]:
            return False

        self.health -= damage

        # Halál vagy sérülés állapot indítása
        if self.health <= 0:
            self._start_death()
        else:
            self._start_hurt()
        return True

    def _start_hurt(self):
        self.state = "hurt"
        self.state_timer = time.time()
        self.invincible_timer = 1.8

        sounds.hit_7.play()
        self.anim.play(f"hurt_{self.facing}", True)

    def _start_death(self):
        self.state = "dying"
        self.state_timer = time.time()

        music.stop()
        sounds.game_over.play()
        self.anim.play(f"die_{self.facing}", True)

    # LEKÉRDEZŐ FÜGGVÉNYEK ÉS SEGÉDFÜGGVÉNYEK
    def get_rect(self):
        return self._rect  # Cache-elt rectangle visszaadása

    def is_dead(self):
        return self.health <= 0

    # RAJZOLÁS ÉS MEGJELENÍTÉS
    def draw(self, screen, camera_x, camera_y):
        # Képernyő koordináták kiszámítása
        screen_x = self.x - camera_x
        screen_y = self.y - camera_y

        # Korai kilépés ha képernyőn kívül van
        if (
            screen_x < -TILE_SIZE
            or screen_x > WIDTH
            or screen_y < -TILE_SIZE
            or screen_y > HEIGHT
        ):
            return

        # Villogás effekt sebzésállóság alatt (de nem sérülés/halál alatt)
        if self.invincible_timer > 0 and self.state not in ["hurt", "dying"]:
            if int(self._last_update * 10) % 2:
                return

        # Játékos karakter rajzolása
        frame = self.anim.get_frame()
        if frame:
            screen.blit(frame, (screen_x, screen_y))

        # Kard rajzolása támadás alatt (de nem halál alatt)
        if self.state == "attacking" and self.state != "dying":
            sword_frame = self.sword_anim.get_frame()
            if sword_frame:
                # Kard 16 pixellel feljebb és balra rajzolása (a kard 48*48px sprite mérete miatt eltolva)
                screen.blit(sword_frame, (screen_x - 16, screen_y - 16))


# === ELLENSÉGEK ===
class Enemy:
    # OSZTÁLY SZINTŰ ANIMÁCIÓ DEFINÍCIÓK (közös minden ellenséghez)
    ANIMATIONS = {
        "idle_right": {
            "frames": [(0, 0), (0, 1)],
            "duration": 0.6,
            "loop": True,
        },
        "idle_left": {
            "frames": [(1, 0), (1, 1)],
            "duration": 0.6,
            "loop": True,
        },
        "walk_right": {
            "frames": [(2, 0), (2, 1), (2, 2)],
            "duration": 0.4,
            "loop": True,
        },
        "walk_left": {
            "frames": [(3, 0), (3, 1), (3, 2)],
            "duration": 0.4,
            "loop": True,
        },
        "hurt_right": {
            "frames": [(4, 0), (4, 1), (4, 2), (4, 3)],
            "duration": 0.2,
            "loop": False,
        },
        "hurt_left": {
            "frames": [(5, 0), (5, 1), (5, 2), (5, 3)],
            "duration": 0.2,
            "loop": False,
        },
    }

    # INICIALIZÁCIÓ ÉS SETUP
    def __init__(self, x, y, enemy_type="rat", movement="horizontal", blocks=2):
        # Pozíció grid-re illesztése
        self.x = (x // TILE_SIZE) * TILE_SIZE
        self.y = (y // TILE_SIZE) * TILE_SIZE
        self.start_x, self.start_y = self.x, self.y

        # Mozgás konfiguració
        self.facing = "right"  # Néző irány
        self.movement_type = movement  # "horizontal" vagy "vertical"
        self.blocks = blocks
        self.blocks_moved = 0
        self.last_move = 0
        self.move_cooldown = 0.3

        # Állapot gép
        self.state = "moving"  # moving, idle, hurt, dying
        self.state_timer = 0

        # Animáció kezelő inicializálása
        spritesheet_path = f"images/enemy_{enemy_type}.png"
        self.anim = AnimationManager(spritesheet_path, TILE_SIZE, self.ANIMATIONS)
        self.anim.play("walk_right")

    # FŐ FRISSÍTÉSI CIKLUS ÉS ÁLLAPOT KEZELÉS
    def update(self, level_loader=None):
        now = time.time()

        # Állapot gép frissítése
        if self.state == "dying":
            if now - self.state_timer >= 1.0:
                return

        elif self.state == "hurt":
            if now - self.state_timer >= 0.8:
                self.state = "moving"
                self.anim.play(f"walk_{self.facing}")

        elif self.state == "moving":
            self._update_movement(now, level_loader)

        elif self.state == "idle":
            if now - self.state_timer >= 3.0:
                self.facing = "left" if self.facing == "right" else "right"
                self.state = "moving"
                self.blocks_moved = 0
                self.anim.play(f"walk_{self.facing}")

        # Animáció frissítése minden állapotban
        self.anim.update()

    def set_paused(self, paused):
        self.anim.set_paused(paused)

    # MOZGÁSI LOGIKA
    def _update_movement(self, now, level_loader):
        if now - self.last_move < self.move_cooldown:
            return

        # Mozgás irányának kiszámítása
        dx = dy = 0
        if self.movement_type == "horizontal":
            dx = 1 if self.facing == "right" else -1
        else:  # vertical
            dy = (
                1 if self.facing == "right" else -1
            )  # "right" = lefelé, "left" = felfelé

        # Új pozíció kiszámítása
        new_x = self.x + (dx * TILE_SIZE)
        new_y = self.y + (dy * TILE_SIZE)

        # Ütközés ellenőrzése
        can_move = True
        if level_loader:
            can_move = not level_loader.is_position_blocked(new_x, new_y)

        if can_move:
            self.x, self.y = new_x, new_y
            self.blocks_moved += 1
            self.last_move = now

            if self.blocks_moved >= self.blocks:
                self.state = "idle"
                self.state_timer = now
                self.anim.play(f"idle_{self.facing}")
        else:
            self.state = "idle"
            self.state_timer = now
            self.anim.play(f"idle_{self.facing}")

    # SEBZÉS ÉS HALÁL RENDSZER
    def take_damage(self):
        if self.state in ["hurt", "dying"]:
            return False

        self.state = "hurt"
        self.state_timer = time.time()
        self.anim.play(f"hurt_{self.facing}", True)
        return True

    def start_death(self):
        self.state = "dying"
        self.state_timer = time.time()
        sounds.hit_7.play()

    def should_be_removed(self):
        return self.state == "dying" and time.time() - self.state_timer >= 1.0

    # RAJZOLÁS ÉS EGYÉB
    def get_rect(self):
        return pygame.Rect(self.x, self.y, TILE_SIZE, TILE_SIZE)

    def draw(self, screen, camera_x, camera_y):
        screen_x, screen_y = self.x - camera_x, self.y - camera_y

        # Villogás sebződéskor/ha az ellenfél meghal
        if self.state == "dying":
            if int(time.time() * 10) % 2:
                return

        # Ellenség sprite rajzolása
        frame = self.anim.get_frame()
        if frame:
            screen.blit(frame, (screen_x, screen_y))


class Boss(Enemy):
    # BOSS-SPECIFIKUS ANIMÁCIÓ DEFINÍCIÓK
    BOSS_ANIMATIONS = {
        "idle_right": {
            "frames": [(0, 0), (0, 1)],
            "duration": 0.6,
            "loop": True,
        },
        "idle_left": {
            "frames": [(1, 0), (1, 1)],
            "duration": 0.6,
            "loop": True,
        },
        "walk_right": {
            "frames": [(2, 0), (2, 1), (2, 2), (2, 3)],
            "duration": 0.4,
            "loop": True,
        },
        "walk_left": {
            "frames": [(3, 0), (3, 1), (3, 2), (3, 3)],
            "duration": 0.4,
            "loop": True,
        },
        "hurt_right": {
            "frames": [(4, 0), (4, 1), (4, 2), (4, 3)],
            "duration": 0.2,
            "loop": False,
        },
        "hurt_left": {
            "frames": [(5, 0), (5, 1), (5, 2), (5, 3)],
            "duration": 0.2,
            "loop": False,
        },
    }

    # INICIALIZÁCIÓ
    def __init__(self, x, y):
        # ALAP POZÍCIÓ ÉS ÁLLAPOT
        self.x = (x // TILE_SIZE) * TILE_SIZE
        self.y = (y // TILE_SIZE) * TILE_SIZE
        self.start_x, self.start_y = self.x, self.y

        # Alap Enemy tulajdonságok (csak a szükségesek)
        self.facing = "right"
        self.movement_type = "boss_ai"  # Speciális boss AI jelölő
        self.state = "moving"
        self.state_timer = 0

        # Specifikus tulajdonságok
        self.max_health = 3  # Boss 3 találatot bír ki
        self.current_health = self.max_health
        self.size = 32  # Boss 32x32 pixel (2x2 tile)

        # Animáció kezelő (különálló sprite sheet)
        self.anim = AnimationManager("images/boss_slime.png", 32, self.BOSS_ANIMATIONS)

        # T-alakú mozgás
        self.move_cooldown = 0.3  # Mozgás sebessége
        self.last_move = 0
        self.blocks_moved = 0
        self.target_blocks = 3  # Mindig 3 blokkot mozog minden irányban

        # T-alakú mozgási szekvencia
        self.t_sequence = ["right", "left", "left", "right", "down", "up"]
        self.current_sequence_index = 0
        self.current_direction = self.t_sequence[0]

        # Győzelem/Vereség állapotok
        self.defeated = False  # Le van-e győzve a boss
        self.victory_timer = 0  # Győzelem időzítő

        # Kezdő animáció indítása
        self.anim.play("walk_right")

    # FELÜLÍRT ALAPFÜGGVÉNYEK
    def get_rect(self):
        # 32x32 pixel ütközési terület (16x16 helyett)
        return pygame.Rect(self.x, self.y, self.size, self.size)

    def should_be_removed(self):
        if not self.defeated:
            return False
        # Boss 3 másodpercig marad a győzelem után
        return time.time() - self.victory_timer >= 3.0

    # FŐ FRISSÍTÉSI CIKLUS, MOZGÁS
    def update(self, level_loader=None):
        if self.defeated:
            # Ha le van győzve, csak várunk az eltávolításra
            return

        now = time.time()

        # _last_update inicializálása ha nem létezik
        if not hasattr(self, "_last_update"):
            self._last_update = now

        # Sérülés állapot kezelése
        if self.state == "hurt":
            hurt_duration = now - self.state_timer

            if hurt_duration >= 0.8:
                self.state = "moving"  # Kilépés a sérülés állapotból
                self._start_current_direction_animation()  # Mozgás folytatása a helyes animációval

            # Animáció frissítése függetlenül
            self.anim.update()
            self._last_update = now
            return

        # Halál állapot kezelése
        if self.state == "dying":
            if now - self.state_timer >= 2.0:
                pass
            self.anim.update()
            self._last_update = now
            return

        # Mozgás frissítése
        self._update_t_motion(now, level_loader)
        self.anim.update()
        self._last_update = now

    def _update_t_motion(self, now, level_loader):
        # Cooldown ellenőrzése
        if now - self.last_move < self.move_cooldown:
            return

        # Mozgás irányának kiszámítása a jelenlegi szekvencia alapján
        dx = dy = 0
        if self.current_direction == "right":
            dx = 1
        elif self.current_direction == "left":
            dx = -1
        elif self.current_direction == "down":
            dy = 1
        elif self.current_direction == "up":
            dy = -1

        # Új pozíció kiszámítása
        new_x = self.x + (dx * TILE_SIZE)
        new_y = self.y + (dy * TILE_SIZE)

        # Mozgás validálása (határok és ütközések)
        can_move = True
        if level_loader:
            level_width, level_height = level_loader.get_level_size()
            # Határ ellenőrzés
            if (
                new_x < 0
                or new_x > level_width - self.size
                or new_y < 0
                or new_y > level_height - self.size
            ):
                can_move = False
            # Ütközés ellenőrzés
            elif level_loader.is_position_blocked(new_x, new_y):
                can_move = False

        if can_move:
            # Boss mozgatása
            self.x, self.y = new_x, new_y
            self.blocks_moved += 1
            self.last_move = now

            # Ellenőrzés: befejezte-e ezt az irányt
            if self.blocks_moved >= self.target_blocks:
                self._next_direction()
        else:
            # Nem tud mozogni ebbe az irányba, következő irány
            self._next_direction()

    def _next_direction(self):
        # Blokk számláló nullázása
        self.blocks_moved = 0

        # Következő irány a szekvenciában
        self.current_sequence_index = (self.current_sequence_index + 1) % len(
            self.t_sequence
        )
        self.current_direction = self.t_sequence[self.current_sequence_index]

        # Megfelelő animáció indítása az új irányhoz
        self._start_current_direction_animation()

    def _start_current_direction_animation(self):
        # Helyes animáció indítása a jelenlegi irányhoz
        if self.current_direction in ["right", "down"]:
            self.facing = "right"
            self.anim.play("walk_right", True)
        else:  # left, up
            self.facing = "left"
            self.anim.play("walk_left", True)

    # SEBZÉS ÉS HALÁL RENDSZER (FELÜLÍRT)
    def take_damage(self):
        if self.state in ["hurt", "dying"]:
            return False

        self.current_health -= 1  # Életerő csökkentése
        if self.current_health <= 0:  # Ellenőrzés: le van-e győzve
            self._start_defeat()
            return True

        # Sérülés állapot indítása
        self.state = "hurt"
        self.state_timer = time.time()

        # Sérülés animáció és hang lejátszása
        hurt_anim = f"hurt_{self.facing}"
        self.anim.play(hurt_anim, True)
        sounds.hit_7.play()

        # Pontszám hozzáadása találatért
        global SCORE
        SCORE += 25

        return True

    def _start_defeat(self):
        self.defeated = True
        self.state = "dying"
        self.state_timer = time.time()
        self.victory_timer = time.time()

        music.stop()
        sounds.levelup_3.play()

        global SCORE, HIGH_SCORE
        SCORE += 500

        # High score frissítése ha a jelenlegi pontszám magasabb
        if SCORE > HIGH_SCORE:
            HIGH_SCORE = SCORE
            save_high_score(HIGH_SCORE)
        else:
            pass

        # Globális game state manager elérése a victory freeze indításához
        global game_state_manager
        game_state_manager._start_victory_freeze()

    # RAJZOLÁS ÉS MEGJELENÍTÉS (speciális effektekkel)
    def draw(self, screen, camera_x, camera_y):
        screen_x, screen_y = self.x - camera_x, self.y - camera_y

        # Villogás sérülés állapotban (gyorsabb mint normál ellenségnél)
        if self.state == "hurt":
            if int(time.time() * 15) % 2:
                return

        # Villogás halál állapotban
        if self.state == "dying":
            if int(time.time() * 8) % 2:
                return

        # Boss sprite rajzolása
        frame = self.anim.get_frame()
        if frame:
            # Boss 32x32 pixel
            screen.blit(frame, (screen_x, screen_y))


# === UI ===
class UI:
    # INICIALIZÁCIÓ ÉS GRAFIKAI ELEMEK BETÖLTÉSE
    def __init__(self):
        # UI Spritesheet betöltése
        self.spritesheet = pygame.image.load("images/ui_hud.png")

        # Szív ikonok kivágása
        self.full_heart = self.spritesheet.subsurface(0, 0, TILE_SIZE, TILE_SIZE)

        self.empty_heart = self.spritesheet.subsurface(
            2 * TILE_SIZE, 0, TILE_SIZE, TILE_SIZE
        )

        # Kulcs ikon kivágása
        self.key_icon = self.spritesheet.subsurface(
            2 * TILE_SIZE, 1 * TILE_SIZE, TILE_SIZE, TILE_SIZE
        )

        # Betűtípus betöltése
        self.score_font = pygame.font.Font("fonts/early_gameboy.ttf", 12)

    # UI RAJZOLÁS ÉS MEGJELENÍTÉS
    def draw(self, screen, player):
        # Globális változók elérése
        global SCORE, HAS_KEY

        # Szívek rajzolása
        for i in range(player.max_health):
            # Szív X pozíciója: 16px margó + index * tile méret
            x = 16 + (i * TILE_SIZE)

            # Szív típus kiválasztása: teli ha van még életerő, üres ha nincs
            heart = self.full_heart if i < player.health else self.empty_heart

            # Szív rajzolása a képernyő tetején (Y=16)
            screen.blit(heart, (x, 16))

        # Pontszám rajzolása és 3 jegyűvé formázása
        score_text = f"{SCORE:03d}"

        if self.score_font:
            score_surface = self.score_font.render(score_text, True, RETRO_CREAM)

            # Szöveg középre igazítása a képernyő tetején
            score_rect = score_surface.get_rect(center=(WIDTH // 2, 16))

            # Pontszám kirajzolása
            screen.blit(score_surface, score_rect)

        # Kulcs rajzolása - csak akkor rajzolja ki ha a játékosnak van kulcsa
        if HAS_KEY:
            # Kulcs pozíció számítása: jobb szél - 16px margó - tile méret
            key_x = WIDTH - 16 - TILE_SIZE
            key_y = 16  # Tetejétől 16px

            # Kulcs ikon kirajzolása
            screen.blit(self.key_icon, (key_x, key_y))


# === AJTÓK ===
class Door:
    def __init__(self, x, y, width, height, locked=True):
        self.rect = pygame.Rect(x, y, width, height)  # Ajtó ütközési területe
        self.locked = locked  # Ajtó zárolt állapota

    def can_enter(self):
        global HAS_KEY

        if not self.locked:
            # Nyitott ajtó - mindig nyitható
            return True
        else:
            # Zárolt ajtó - csak kulccsal nyitható
            return HAS_KEY

    def check_collision(self, player_rect):
        # Ez a függvény csak azt ellenőrzi, hogy a játékos az ajtó területén van-e.
        return self.rect.colliderect(player_rect)


# A pickup és a Level loader nem magyar!
# === PICKUP ===
class Pickup:
    # OSZTÁLY SZINTŰ ANIMÁCIÓ DEFINÍCIÓK
    ANIMATIONS = {
        "coin": {
            "frames": [(0, 0), (0, 1), (0, 2), (0, 3)],
            "duration": 0.6,
            "loop": True,
        },
        "key": {
            "frames": [(1, 0), (1, 1), (1, 2), (1, 3)],
            "duration": 0.6,
            "loop": True,
        },
        "heart": {
            "frames": [(4, 0), (4, 1), (4, 2), (4, 3)],
            "duration": 0.6,
            "loop": True,
        },
    }

    # INICIALIZÁCIÓ ÉS SETUP
    def __init__(self, x, y, pickup_type="heart"):
        # Pozíció grid-re illesztése (tile-okra igazítás)
        self.x = (x // TILE_SIZE) * TILE_SIZE
        self.y = (y // TILE_SIZE) * TILE_SIZE

        # Pickup állapot változók
        self.pickup_type = pickup_type  # Pickup típusa
        self.collected = False  # Fel van-e véve

        # Animáció kezelő inicializálása
        self.anim = AnimationManager(
            "images/pickup_animated.png", TILE_SIZE, self.ANIMATIONS
        )

        # Megfelelő animáció indítása típus alapján
        if pickup_type in self.ANIMATIONS:
            self.anim.play(pickup_type)
        else:
            # Ismeretlen típus esetén fallback heart-re
            self.pickup_type = "heart"
            self.anim.play("heart")

    # FŐ FRISSÍTÉSI CIKLUS ÉS ÁLLAPOT KEZELÉS
    def update(self):
        if not self.collected:
            self.anim.update()

    def set_paused(self, paused):
        self.anim.set_paused(paused)

    # BEGYŰJTÉS ÉS TÍPUS KEZELÉS
    def collect(self, player):
        if self.collected:
            return False

        # Pickup megjelölése felvettként
        self.collected = True

        # Típus-specifikus kezelés végrehajtása
        if self.pickup_type == "coin":
            self._collect_coin(player)
        elif self.pickup_type == "heart":
            self._collect_heart(player)
        elif self.pickup_type == "key":
            self._collect_key(player)

        return True

    # TÍPUS-SPECIFIKUS PICKUP KEZELŐK
    def _collect_coin(self, player):
        global SCORE
        SCORE += 10
        sounds.gold_2.play()

    def _collect_heart(self, player):
        player.health += 1
        sounds.bonus_3.play()

    def _collect_key(self, player):
        global HAS_KEY
        sounds.coin_3.play()
        HAS_KEY = True

    # LEKÉRDEZŐ FÜGGVÉNYEK ÉS SEGÉDFÜGGVÉNYEK
    def get_rect(self):
        return pygame.Rect(self.x, self.y, TILE_SIZE, TILE_SIZE)

    def should_be_removed(self):
        return self.collected

    # RAJZOLÁS ÉS MEGJELENÍTÉS
    def draw(self, screen, camera_x, camera_y):
        # Korai kilépés ha már felvéve
        if self.collected:
            return

        # Képernyő koordináták kiszámítása
        screen_x, screen_y = self.x - camera_x, self.y - camera_y

        # Csak akkor rajzol ha a képernyőn van (margin-nel a smooth scrolling-hoz)
        if -TILE_SIZE <= screen_x <= WIDTH and -TILE_SIZE <= screen_y <= HEIGHT:

            frame = self.anim.get_frame()
            if frame:
                # Pickup sprite rajzolása
                screen.blit(frame, (screen_x, screen_y))
            else:
                # Debug: színes négyzet ha nincs elérhető frame
                debug_surf = pygame.Surface((TILE_SIZE, TILE_SIZE))
                debug_surf.fill((255, 0, 255))  # Magenta szín hiányzó pickup frame-hez
                screen.blit(debug_surf, (screen_x, screen_y))


# === VÁZA ===
class Pot:
    def __init__(self, x, y):
        self.x = (x // TILE_SIZE) * TILE_SIZE
        self.y = (y // TILE_SIZE) * TILE_SIZE

        self.destroyed = False

        try:
            spritesheet = pygame.image.load("images/props.png").convert_alpha()
            self.sprite = spritesheet.subsurface(
                3 * TILE_SIZE, 1 * TILE_SIZE, TILE_SIZE, TILE_SIZE
            ).convert_alpha()
        except Exception as e:
            print(f"{e}")
            self.sprite = pygame.Surface((TILE_SIZE, TILE_SIZE))
            self.sprite.fill((139, 69, 19))  # Barna szín

    def destroy(self, level_loader=None):
        if self.destroyed:
            return False

        self.destroyed = True

        if level_loader:
            tile_x = int(self.x // TILE_SIZE)
            tile_y = int(self.y // TILE_SIZE)
            if 0 <= tile_y < len(level_loader.collision_grid) and 0 <= tile_x < len(
                level_loader.collision_grid[0]
            ):
                level_loader.collision_grid[tile_y][tile_x] = False

        import random

        if random.random() < 0.6:
            global SCORE
            SCORE += 10
            sounds.gold_2.play()
        else:
            sounds.bounce_2.play()

        return True

    def get_rect(self):
        return pygame.Rect(self.x, self.y, TILE_SIZE, TILE_SIZE)

    def should_be_removed(self):
        return self.destroyed

    def draw(self, screen, camera_x, camera_y):
        if self.destroyed:
            return

        screen_x = self.x - camera_x
        screen_y = self.y - camera_y

        # Csak akkor rajzol ha a képernyőn van
        if -TILE_SIZE <= screen_x <= WIDTH and -TILE_SIZE <= screen_y <= HEIGHT:
            screen.blit(self.sprite, (screen_x, screen_y))


class LevelLoader:
    def __init__(self, level_sequence):
        self.level_sequence = level_sequence
        self.current_level_index = 0
        self.tmx_data = None
        self.bg_surface = None
        self.camera_x = self.camera_y = 0
        self.objects = []
        self.player = None
        self.collision_grid = []
        self.animated_tiles = []
        self.doors = []
        self.pickups = []
        self.pots = []
        self.ui = UI()

        self.transitioning = False
        self.transition_timer = 0
        self.transition_duration = 0.5
        self.transition_surface = pygame.Surface((WIDTH, HEIGHT)).convert_alpha()

        self._temp_rect = pygame.Rect(0, 0, TILE_SIZE, TILE_SIZE)
        self._screen_rect = pygame.Rect(0, 0, WIDTH, HEIGHT)
        self._level_width = 0
        self._level_height = 0
        self._paused_frame_time = 0
        self.load_current_level()

    def load_current_level(self):
        if self.current_level_index >= len(self.level_sequence):
            return False

        level_name = self.level_sequence[self.current_level_index]
        tmx_path = os.path.join("data", "tmx", f"{level_name}.tmx")

        try:
            if hasattr(self, "_tile_conversion_cache"):
                self._tile_conversion_cache.clear()
            if hasattr(self, "_animated_frame_cache"):
                self._animated_frame_cache.clear()

            self.tmx_data = pytmx.load_pygame(tmx_path)
            self._create_collision_grid()
            self._render_background()
            self._load_objects()
            self._load_animated_tiles()
            return True
        except Exception as e:
            print(f"{e}")
            return False

    def _create_collision_grid(self):
        if not self.tmx_data:
            return

        w, h = self.tmx_data.width, self.tmx_data.height
        self.collision_grid = [[False for _ in range(w)] for _ in range(h)]

        for layer in self.tmx_data.layers:
            if layer.name == "colliders" and hasattr(layer, "data"):
                for x, y, gid in layer:
                    if gid and 0 <= y < h and 0 <= x < w:
                        self.collision_grid[y][x] = True
                break

    def _render_background(self):
        if not self.tmx_data:
            return

        w = self.tmx_data.width * self.tmx_data.tilewidth
        h = self.tmx_data.height * self.tmx_data.tileheight

        self._level_width, self._level_height = w, h
        self.bg_surface = pygame.Surface((w, h)).convert_alpha()

        if not hasattr(self, "_tile_conversion_cache"):
            self._tile_conversion_cache = {}

        for layer_name in ["background", "colliders"]:
            for layer in self.tmx_data.layers:
                if layer.name == layer_name and hasattr(layer, "data"):
                    for x, y, gid in layer:
                        if gid:
                            tile = self.tmx_data.get_tile_image_by_gid(gid)
                            if tile:
                                if gid not in self._tile_conversion_cache:
                                    self._tile_conversion_cache[
                                        gid
                                    ] = tile.convert_alpha()

                                converted_tile = self._tile_conversion_cache[gid]
                                self.bg_surface.blit(
                                    converted_tile,
                                    (
                                        x * self.tmx_data.tilewidth,
                                        y * self.tmx_data.tileheight,
                                    ),
                                )

    def _load_objects(self):
        previous_health = None
        if self.player:
            previous_health = self.player.health

        self.objects.clear()
        old_player = self.player
        self.player = None
        self.doors.clear()
        self.pickups.clear()
        self.pots.clear()

        if not self.tmx_data:
            return

        for layer in self.tmx_data.layers:
            if layer.name == "objects":
                for obj in layer:
                    name = obj.name.lower() if obj.name else ""

                    if name == "player":
                        player = Player(obj.x, obj.y)

                        if previous_health is not None:
                            player.health = previous_health

                        self.objects.append(player)
                        self.player = player

                    elif name == "door":
                        locked = getattr(obj, "locked", True)
                        if hasattr(obj, "properties"):
                            locked = obj.properties.get("locked", locked)

                        door = Door(obj.x, obj.y, obj.width, obj.height, locked)
                        self.doors.append(door)

                    elif name == "pickup":
                        pickup_type = getattr(obj, "pickup_type", "heart")
                        if hasattr(obj, "properties"):
                            pickup_type = obj.properties.get("pickup_type", pickup_type)

                        pickup = Pickup(obj.x, obj.y, pickup_type)
                        self.pickups.append(pickup)

                    elif name == "pot":
                        pot = Pot(obj.x, obj.y)
                        self.pots.append(pot)

                    elif name == "enemy":
                        enemy_type = getattr(obj, "enemy_type", "rat")
                        movement = getattr(obj, "enemy_movement", "horizontal")
                        blocks = getattr(obj, "blocks", 2)

                        if hasattr(obj, "properties"):
                            enemy_type = obj.properties.get("enemy_type", enemy_type)
                            movement = obj.properties.get("enemy_movement", movement)
                            blocks = obj.properties.get("blocks", blocks)

                        enemy = Enemy(obj.x, obj.y, enemy_type, movement, int(blocks))
                        self.objects.append(enemy)

                    elif name == "boss":
                        boss = Boss(obj.x, obj.y)
                        self.objects.append(boss)

                    elif name == "info":
                        music_file = getattr(obj, "music", None)
                        if hasattr(obj, "properties"):
                            music_file = obj.properties.get("music", music_file)
                        if music_file:
                            self._load_music(music_file)
                break

    def _load_music(self, filename):
        try:
            music.stop()
            if os.path.exists(f"music/{filename}.ogg"):
                music.play(filename)
        except Exception as e:
            print(f"{e}")

    def _load_animated_tiles(self):
        self.animated_tiles.clear()
        if not self.tmx_data:
            return

        if not hasattr(self, "_animated_frame_cache"):
            self._animated_frame_cache = {}

        for layer in self.tmx_data.layers:
            if layer.name == "animated" and hasattr(layer, "data"):
                for x, y, gid in layer:
                    if gid:
                        frames = self._get_tile_frames(gid)
                        if (
                            frames and len(frames) > 1
                        ):  # Only store truly animated tiles
                            converted_frames = []
                            for i, frame in enumerate(frames):
                                if frame:
                                    # Use GID + frame index as cache key
                                    cache_key = f"{gid}_{i}"
                                    if cache_key not in self._animated_frame_cache:
                                        self._animated_frame_cache[
                                            cache_key
                                        ] = frame.convert_alpha()
                                    converted_frames.append(
                                        self._animated_frame_cache[cache_key]
                                    )

                            if converted_frames:
                                self.animated_tiles.append(
                                    {
                                        "x": x * self.tmx_data.tilewidth,
                                        "y": y * self.tmx_data.tileheight,
                                        "frames": converted_frames,
                                    }
                                )
                break

    def _get_tile_frames(self, gid):
        try:
            props = self.tmx_data.get_tile_properties_by_gid(gid)
            if props and "frames" in props:
                frames = []
                for frame in props["frames"]:
                    surface = self.tmx_data.get_tile_image_by_gid(frame.gid)
                    if surface:
                        frames.append(surface)
                return frames
            else:
                surface = self.tmx_data.get_tile_image_by_gid(gid)
                return [surface] if surface else []
        except Exception as e:
            print(f"{e}")
            surface = self.tmx_data.get_tile_image_by_gid(gid)
            return [surface] if surface else []

    def start_transition(self):
        if self.transitioning:
            return False

        self.transitioning = True
        self.transition_timer = time.time()
        return True

    def next_level(self):
        self.current_level_index += 1
        if self.current_level_index >= len(self.level_sequence):
            self.current_level_index = len(self.level_sequence) - 1
            return False

        return self.load_current_level()

    def update(self):
        if (
            hasattr(game_state_manager, "victory_freeze")
            and game_state_manager.victory_freeze
        ):
            return

        if self.transitioning:
            elapsed = time.time() - self.transition_timer
            if elapsed >= self.transition_duration:
                self.transitioning = False
                self.next_level()
            return

        for entity in self.objects:
            if hasattr(entity, "update"):
                if isinstance(entity, Enemy):
                    entity.update(self)
                else:
                    entity.update()

        for pickup in self.pickups:
            pickup.update()

        self.pots = [pot for pot in self.pots if not pot.should_be_removed()]

        self._check_collisions()

        self.objects = [
            obj
            for obj in self.objects
            if not (isinstance(obj, Enemy) and obj.should_be_removed())
        ]

        self.pickups = [
            pickup for pickup in self.pickups if not pickup.should_be_removed()
        ]

    def set_paused(self, paused):
        if self.player:
            self.player.set_paused(paused)

        for obj in self.objects:
            if isinstance(obj, Enemy):
                obj.set_paused(paused)

        for pickup in self.pickups:
            pickup.set_paused(paused)

    def _check_collisions(self):
        if not self.player:
            return

        player_rect = self.player.get_rect()

        for pickup in self.pickups:
            if not pickup.collected and player_rect.colliderect(pickup.get_rect()):
                pickup.collect(self.player)
                break

        if self.player.invincible_timer <= 0:
            for obj in self.objects:
                if (
                    isinstance(obj, Enemy)
                    and obj.state not in ["hurt", "dying"]
                    and player_rect.colliderect(obj.get_rect())
                ):
                    self.player.take_damage(1)
                    break

        if self.player.state == "attacking":
            sword_rect = self._get_sword_rect()
            if sword_rect:
                for obj in self.objects:
                    if (
                        isinstance(obj, Enemy)
                        and obj.state not in ["hurt", "dying"]
                        and sword_rect.colliderect(obj.get_rect())
                    ):
                        if obj.take_damage():
                            if not isinstance(obj, Boss):
                                obj.start_death()
                        break

                for pot in self.pots:
                    if not pot.destroyed and sword_rect.colliderect(pot.get_rect()):
                        pot.destroy(self)
                        break

    def _get_sword_rect(self):
        if not self.player or self.player.state != "attacking":
            return None

        if self.player.facing == "right":
            self._temp_rect.x = self.player.x + TILE_SIZE
            self._temp_rect.y = self.player.y
        else:
            self._temp_rect.x = self.player.x - TILE_SIZE
            self._temp_rect.y = self.player.y

        self._temp_rect.width = TILE_SIZE
        self._temp_rect.height = TILE_SIZE
        return self._temp_rect

    def is_position_blocked(self, x, y):
        tile_x, tile_y = int(x // TILE_SIZE), int(y // TILE_SIZE)

        if (
            tile_x < 0
            or tile_y < 0
            or tile_y >= len(self.collision_grid)
            or tile_x >= len(self.collision_grid[0])
        ):
            return True

        for pot in self.pots:
            if not pot.destroyed:
                pot_tile_x = int(pot.x // TILE_SIZE)
                pot_tile_y = int(pot.y // TILE_SIZE)
                if pot_tile_x == tile_x and pot_tile_y == tile_y:
                    return True

        return self.collision_grid[tile_y][tile_x]

    def move_player(self, dx, dy):
        if self.player:
            new_x = self.player.x + (dx * TILE_SIZE)
            new_y = self.player.y + (dy * TILE_SIZE)

            if not self.is_position_blocked(new_x, new_y):
                level_width, level_height = self.get_level_size()
                current_time = pygame.time.get_ticks() / 1000.0
                return self.player.move(dx, dy, level_width, level_height, current_time)
        return False

    def try_enter_door(self):
        if not self.player or self.transitioning:
            return

        global HAS_KEY
        player_rect = self.player.get_rect()

        for door in self.doors:
            if door.check_collision(player_rect):
                if door.can_enter():

                    if door.locked and HAS_KEY:
                        HAS_KEY = False

                    try:
                        sounds.wings.play()
                    except:
                        pass
                    self.start_transition()
                    return
                else:
                    try:
                        pass
                    except:
                        pass
                    return

    def get_level_size(self):
        return (self._level_width, self._level_height)

    def draw(self, screen):
        self._screen_rect.x = self.camera_x
        self._screen_rect.y = self.camera_y

        if self.bg_surface:
            screen.blit(self.bg_surface, (0, 0), self._screen_rect)

        if self.animated_tiles:
            if (
                hasattr(game_state_manager, "game_paused")
                and game_state_manager.game_paused
            ):
                frame_time = self._paused_frame_time
            else:
                frame_time = pygame.time.get_ticks() // 600
                self._paused_frame_time = frame_time

            for tile in self.animated_tiles:
                if len(tile["frames"]) > 1:
                    screen_x = tile["x"] - self.camera_x
                    screen_y = tile["y"] - self.camera_y

                    if (
                        -TILE_SIZE <= screen_x <= WIDTH
                        and -TILE_SIZE <= screen_y <= HEIGHT
                    ):
                        frame_idx = frame_time % len(tile["frames"])
                        screen.blit(tile["frames"][frame_idx], (screen_x, screen_y))

        for pickup in self.pickups:
            pickup.draw(screen, self.camera_x, self.camera_y)

        for pot in self.pots:
            pot.draw(screen, self.camera_x, self.camera_y)

        for obj in self.objects:
            if hasattr(obj, "x") and hasattr(obj, "y"):
                screen_x = obj.x - self.camera_x
                screen_y = obj.y - self.camera_y
                if -64 <= screen_x <= WIDTH + 64 and -64 <= screen_y <= HEIGHT + 64:
                    obj.draw(screen, self.camera_x, self.camera_y)
            else:
                obj.draw(screen, self.camera_x, self.camera_y)

        if self.player:
            self.ui.draw(screen, self.player)

        if DEBUG_MODE_ON:
            self._draw_debug(screen)

        if self.transitioning:
            self._draw_transition(screen)

    def _draw_transition(self, screen):
        elapsed = time.time() - self.transition_timer
        progress = elapsed / self.transition_duration

        alpha = int(255 * progress)
        self.transition_surface.fill(RETRO_BROWN)
        self.transition_surface.set_alpha(alpha)
        screen.blit(self.transition_surface, (0, 0))

    def _draw_debug(self, screen):
        for y, row in enumerate(self.collision_grid):
            for x, blocked in enumerate(row):
                if blocked:
                    screen_x = (x * TILE_SIZE) - self.camera_x
                    screen_y = (y * TILE_SIZE) - self.camera_y
                    if (
                        -TILE_SIZE <= screen_x <= WIDTH
                        and -TILE_SIZE <= screen_y <= HEIGHT
                    ):
                        if not hasattr(self, "_debug_red_surf"):
                            self._debug_red_surf = pygame.Surface(
                                (TILE_SIZE, TILE_SIZE)
                            ).convert_alpha()
                            self._debug_red_surf.set_alpha(128)
                            self._debug_red_surf.fill((255, 0, 0))
                        screen.blit(self._debug_red_surf, (screen_x, screen_y))

        for door in self.doors:
            screen_x = door.rect.x - self.camera_x
            screen_y = door.rect.y - self.camera_y
            if (
                -door.rect.width <= screen_x <= WIDTH
                and -door.rect.height <= screen_y <= HEIGHT
            ):

                if not hasattr(self, "_debug_door_surfs"):
                    self._debug_door_surfs = {}

                color_key = "green" if door.can_enter() else "yellow"
                if color_key not in self._debug_door_surfs:
                    surf = pygame.Surface(
                        (door.rect.width, door.rect.height)
                    ).convert_alpha()
                    surf.set_alpha(128)
                    color = (0, 255, 0) if color_key == "green" else (255, 255, 0)
                    surf.fill(color)
                    self._debug_door_surfs[color_key] = surf

                screen.blit(self._debug_door_surfs[color_key], (screen_x, screen_y))

        # Draw pickup debug info in blue
        for pickup in self.pickups:
            if not pickup.collected:
                screen_x = pickup.x - self.camera_x
                screen_y = pickup.y - self.camera_y
                if -TILE_SIZE <= screen_x <= WIDTH and -TILE_SIZE <= screen_y <= HEIGHT:
                    if not hasattr(self, "_debug_pickup_surf"):
                        self._debug_pickup_surf = pygame.Surface(
                            (TILE_SIZE, TILE_SIZE)
                        ).convert_alpha()
                        self._debug_pickup_surf.set_alpha(128)
                        self._debug_pickup_surf.fill((0, 0, 255))
                    screen.blit(self._debug_pickup_surf, (screen_x, screen_y))


# === JÁTÉK CIKLUS ===
game_state_manager = GameStateManager()


def update():
    game_state_manager.update()
    game_state_manager.handle_input()

    if (
        game_state_manager.current_state == STATE_GAME
        and game_state_manager.level_loader
    ):
        game_state_manager.level_loader.set_paused(game_state_manager.game_paused)


def draw():
    screen.clear()
    game_state_manager.draw(screen.surface)


def cleanup():
    AnimationManager.clear_caches()
    input_handler.cleanup()
    pygame.quit()


import atexit

atexit.register(cleanup)
pgzrun.go()
