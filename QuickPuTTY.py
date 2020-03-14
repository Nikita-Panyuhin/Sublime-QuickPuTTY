#  Copyright (c) 2020 Nikita Paniukhin  |
#     Licensed under the MIT license    |
# ---------------------------------------

import sublime
import sublime_plugin
from subprocess import Popen
import os
from re import match as re_match
from copy import deepcopy

from .QuickPuTTY_text import MSG, TEMPLATE_MENU, INSTALL_HTML

# If you want to edit default settings:
# Go to "class Session > def on_load" and change "view.set_read_only(True)" to False (or comment this line)

PACKAGE_NAME = "QuickPuTTY"

IPV4_REGEX = r"(?:https?:?[\/\\]{,2})?(\d+)[\.:,](\d+)[\.:,](\d+)[\.:,](\d+)(?::\d+)?"

USER_DATA_PATH, USER_PACKAGE_PATH, SETTINGS_PATH, SESSIONS_PATH, MENU_PATH = None, None, None, None, None


def mkpath(*paths) -> str:
    '''Combines paths and normalizes the result'''
    return os.path.normpath(os.path.join(*paths))


class QuickPuTTYEncryption:
    def __init__(self, key_one: int, key_two: str):
        self.ASCII_SIZE = 1114159
        self.alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        self.key_one = key_one
        self.key_two = sum(ord(key_two[i]) * (self.ASCII_SIZE ** i) for i in range(len(key_two))) % self.key_one

    def base_36(self, num: int) -> str:
        '''Converts number to base 36'''
        return self.alphabet[num] if num < 36 else self.base_36(num // 36) + self.alphabet[num % 36]

    def encrypt(self, string: str) -> str:
        '''Encrypts string'''
        res = sum([(ord(string[i]) + self.key_one) * ((self.ASCII_SIZE + self.key_one + self.key_two) ** i) for i in range(len(string))])
        return self.base_36(res)

    def decrypt(self, string: str) -> str:
        '''Decrypts string'''
        string = int(string, 36)
        result = []
        while string > 0:
            string, letter = divmod(string, (self.ASCII_SIZE + self.key_one + self.key_two))
            result.append(chr(letter - self.key_one))
        return "".join(result)

# key_one, key_two, string = 42, "my_key", "You can't read this string"
# encryption = QuickPuTTYEncryption(key_one, key_two)
# encrypted = encryption.encrypt(string)
# decrypted = encryption.decrypt(encrypted)
# print(encrypted, decrypted)


def makeSessionMenuFile(sessions: dict) -> None:
    '''Creates a .sublime-menu file containing given sessions (from a template).
       Takes an encrypted password'''
    data = deepcopy(TEMPLATE_MENU)

    for name in sessions:
        to_write = {
            "caption": name,
            "command": "quickputty_open",
            "args": {
                "host": sessions[name]["host"],
                "port": sessions[name]["port"]
            }
        }

        if sessions[name]["login"]:
            to_write["args"]["login"] = sessions[name]["login"]
        if sessions[name]["password"]:
            to_write["args"]["password"] = sessions[name]["password"]

        data[1]["children"].append(to_write)

    with open(MENU_PATH, "w", encoding="utf-8") as file:
        file.write(sublime.encode_value(data, True))

    print(MSG["reload"])
    sublime.status_message(MSG["reload"])


def checkSessions(sessions: dict) -> dict:
    '''Checks whether the session format is correct and encrypts the password'''
    if not isinstance(sessions, dict):
        sublime.error_message(MSG["invalid_sessions"])

    for name in sessions:
        if not isinstance(sessions[name], dict) or "host" not in sessions[name] or "port" not in sessions[name]:
            sublime.error_message(MSG["invalid_sessions"])
            break

        if "encrypt" in sessions[name] or "encr" in sessions[name]:
            del sessions[name]["encrypt"]
            sessions[name]["password"] = encryption.encrypt(sessions[name]["password"])
    else:
        return sessions


def checkSettings() -> bool:
    '''Checks whether the session format is correct'''
    settings = sublime.load_settings(PACKAGE_NAME + ".sublime-settings")

    if not settings.has("encryption_key_one") \
            or not settings.has("encryption_key_two") \
            or not settings.has("PuTTY_run_command") \
            or not settings.has("clear_on_remove"):
        sublime.error_message(MSG["setting_not_found"])
        return False

    settings.clear_on_change("check_settings")
    settings.add_on_change("check_settings", checkSettings)

    if not isinstance(settings.get("encryption_key_one"), int) or not isinstance(settings.get("encryption_key_two"), str):
        sublime.error_message(MSG["bad_keys"])
        return False

    if not isinstance(settings.get("clear_on_remove"), bool):
        sublime.error_message(MSG["bad_clear_on_remove"])
        return False

    if not isinstance(settings.get("PuTTY_run_command"), str):
        sublime.error_message(MSG["bad_PuTTY_run_command"])
        return False

    print("QuickPuTTY: Settings checked")
    return True


class QuickputtyOpen(sublime_plugin.WindowCommand):
    '''Responsible for opening PuTTY.
       Handles "quickputty_open" command.'''

    def run(self, host: str = None, port: int = 22, login: str = "", password: str = "") -> None:
        run_command = sublime.load_settings(PACKAGE_NAME + ".sublime-settings").get("PuTTY_run_command")

        if host is None:
            Popen([run_command])
        else:
            password = encryption.decrypt(password)
            command = [run_command, "-ssh", host, "-P", str(port)]
            if login:
                command += ["-l", login]
            if password:
                command += ["-pw", password]
            Popen(command)


class QuickputtyNew(sublime_plugin.WindowCommand):
    '''Responsible for creating new sessions.
       Handles "quickputty_new" command.'''

    def run(self):
        with open(SESSIONS_PATH, "r", encoding="utf-8") as file:
            try:
                self.sessions = sublime.decode_value(file.read().strip())
            except Exception:
                sublime.error_message(MSG["invalid_json"])
                return

        if checkSessions(self.sessions) is None:
            sublime.status_message(MSG["cancel"])
            return

        self.new_session = {key: None for key in ("host", "port", "login", "password")}

        # Asking for name
        self.window.show_input_panel("Session name", "", self.choose_host, 0, lambda: sublime.status_message(MSG["cancel"]))

    def choose_host(self, session_name):
        # Session name check
        session_name = session_name.strip()

        if not session_name:
            print(MSG["cancel"])
            sublime.status_message(MSG["cancel"])
            return

        if session_name in self.sessions:
            sublime.error_message(MSG["already_has_name"])
            return

        # Saving and asking for host
        self.session_name = session_name
        self.window.show_input_panel("Server host", "127.0.0.1", self.choose_port, 0, lambda: sublime.status_message(MSG["cancel"]))

    def choose_port(self, session_host):
        # Session host check
        session_host = session_host.strip()
        if not session_host:
            sublime.error_message(MSG["empty_host"])
            print(MSG["cancel"])
            sublime.status_message(MSG["cancel"])
            return

        # If ipv4 is recognized:
        ipv4_match = re_match(IPV4_REGEX, session_host)
        if ipv4_match is not None:
            session_host = ".".join(ipv4_match.group(i) for i in range(1, 5))

        # Saving and asking for port
        self.new_session["host"] = session_host
        self.window.show_input_panel("Connection port", "22", self.choose_login, 0, lambda: sublime.status_message(MSG["cancel"]))

    def choose_login(self, session_port):
        # Session port check
        try:
            session_port = int(session_port)
            wrong = session_port <= 0
        except Exception:
            wrong = True

        if wrong:
            sublime.error_message(MSG["wrong_port"])
            print(MSG["cancel"])
            sublime.status_message(MSG["cancel"])
            return

        # Saving and asking for username
        self.new_session["port"] = session_port
        self.window.show_input_panel("Username (optional)", "", self.choose_password, 0, lambda: sublime.status_message(MSG["cancel"]))

    def choose_password(self, session_login):
        # Saving and asking for password
        self.new_session["login"] = session_login.strip()
        self.window.show_input_panel("Password (optional)", "", self.save, 0, lambda: sublime.status_message(MSG["cancel"]))

    def save(self, session_password):
        # Saving
        self.new_session["password"] = encryption.encrypt(session_password.strip())

        self.sessions[self.session_name] = self.new_session

        # Saving to "sessions.json"
        with open(SESSIONS_PATH, "w", encoding="utf-8") as file:
            file.write(MSG["encrypt_changed_password"] + sublime.encode_value(self.sessions, True))

        # Writing to sublime-menu file
        makeSessionMenuFile(self.sessions)


class QuickputtyRemove(sublime_plugin.WindowCommand):
    '''Responsible for removing sessions.
       Handles "quickputty_remove" command.'''

    def run(self):
        # Get sessions
        with open(SESSIONS_PATH, "r", encoding="utf-8") as file:
            try:
                self.sessions = sublime.decode_value(file.read().strip())
            except Exception:
                sublime.error_message(MSG["invalid_json"])
                return

        # Check sessions
        if checkSessions(self.sessions) is None:
            sublime.status_message(MSG["cancel"])
            return

        # If sessions list is empty
        if not self.sessions:
            sublime.message_dialog(MSG["no_sessions"])
            return

        # Create a list [name, host]
        self.sessions_data = [[name, self.sessions[name]["host"]] for name in self.sessions]

        # Ask user
        self.window.show_quick_panel(["{} ({})".format(name, host) for name, host in self.sessions_data], self.confirm)

    def confirm(self, index):
        # If nothing is chosen
        if index == -1:
            print(MSG["cancel"])
            sublime.status_message(MSG["cancel"])
            return

        name, host = self.sessions_data[index]
        if sublime.yes_no_cancel_dialog("Session \"{}\" ({}) will be deleted. Are you sure?".format(name, host)) == sublime.DIALOG_YES:
            # User agreed to remove, removing:
            del self.sessions[name]

            print(MSG["remove"].format(session_name=name))

            # Updating "sessions.json" and menu file
            with open(SESSIONS_PATH, "w", encoding="utf-8") as file:
                file.write(MSG["encrypt_changed_password"] + sublime.encode_value(self.sessions, True))
            makeSessionMenuFile(self.sessions)

        else:
            print(MSG["cancel"])
            sublime.status_message(MSG["cancel"])


class Files(sublime_plugin.EventListener):
    '''Controls the behavior of settings file and sessions file and updates the .sublime-menu file.'''

    def on_load(self, view):
        if view.file_name() == SETTINGS_PATH:
            # Preventing the user from changing the default settings.
            view.set_read_only(True)

    def on_post_save_async(self, view):
        if view.file_name() == SESSIONS_PATH:
            # Updating menu file
            with open(SESSIONS_PATH, "r", encoding="utf-8") as file:
                try:
                    sessions = sublime.decode_value(file.read().strip())
                except Exception:
                    sublime.error_message(MSG["invalid_json"])
                    return

            # Checking sessiosn
            sessions = checkSessions(sessions)
            if sessions is None:
                return

            # Updating "sessiosn.json"
            with open(SESSIONS_PATH, "w", encoding="utf-8") as file:
                file.write(MSG["encrypt_changed_password"] + sublime.encode_value(sessions, True))
            makeSessionMenuFile(sessions)


class QuickputtyReadme(sublime_plugin.WindowCommand):
    '''Responsible for showing the README file when installing the package.
       Handles "quickputty_readme" command.'''

    def run(self):
        view = sublime.active_window().new_file()
        view.set_read_only(True)
        view.set_name("QuickPuTTY")
        view.add_phantom("test", sublime.Region(0, 0), INSTALL_HTML, sublime.LAYOUT_BELOW, lambda url: sublime.run_command("open_url", args={"url": url}))


def plugin_loaded():
    # Initialization
    import sublime
    from package_control import events

    global USER_DATA_PATH
    global USER_PACKAGE_PATH
    global SETTINGS_PATH
    global SESSIONS_PATH
    global MENU_PATH
    global TEMPLATE_MENU
    global encryption

    TEMPLATE_MENU = sublime.decode_value(TEMPLATE_MENU)

    USER_DATA_PATH = mkpath(sublime.packages_path(), "User")
    USER_PACKAGE_PATH = mkpath(USER_DATA_PATH, "QuickPuTTY")
    SETTINGS_PATH = mkpath(sublime.packages_path(), PACKAGE_NAME, "QuickPuTTY.sublime-settings")
    SESSIONS_PATH = mkpath(USER_PACKAGE_PATH, "sessions.json")
    MENU_PATH = mkpath(USER_PACKAGE_PATH, "Main.sublime-menu")

    # Show README
    if events.install(PACKAGE_NAME):
        QuickputtyReadme(sublime.active_window()).run()

    # Check settings
    if not checkSettings():
        return

    settings = sublime.load_settings(PACKAGE_NAME + ".sublime-settings")

    encryption = QuickPuTTYEncryption(settings.get("encryption_key_one"), settings.get("encryption_key_two"))

    # Creating "User file"
    if not os.path.isdir(USER_PACKAGE_PATH):
        os.mkdir(mkpath(USER_PACKAGE_PATH))

    # (Re-)Creating file for storing sessions
    if os.path.isfile(SESSIONS_PATH):
        with open(SESSIONS_PATH, "r", encoding="utf-8") as file:
            try:
                sessions = sublime.decode_value(file.read().strip())
            except Exception:
                sublime.error_message(MSG["invalid_json"])
                return
            sessions = checkSessions(sessions)
            if sessions is None:
                return
    else:
        sessions = {}

    # Updating sessions.json
    with open(SESSIONS_PATH, "w", encoding="utf-8") as file:
        file.write(MSG["encrypt_changed_password"] + sublime.encode_value(sessions, True))

    # Making menu file
    makeSessionMenuFile(sessions)


def plugin_unloaded():
    from package_control import events

    # Removing unnecessary menu file
    if os.path.exists(MENU_PATH):
        os.remove(MENU_PATH)

    if events.remove(PACKAGE_NAME):
        # If setting "clear_on_remove" is True:
        if sublime.load_settings(PACKAGE_NAME + ".sublime-settings").get("clear_on_remove", False):
            # Removing sessions.json
            os.remove(SESSIONS_PATH)
            # Trying to remove QuickPuTTY user directory
            try:
                os.rmdir(USER_PACKAGE_PATH)
            except Exception:
                sublime.error_message("Can not remove QuickPuTTY user directory.")
