# pytest-anki
#
# Copyright (C)  2019-2021 Aristotelis P. <https://glutanimate.com/>
#                and contributors (see CONTRIBUTORS file)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version, with the additions
# listed at the end of the license file that accompanied this program.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# NOTE: This program is subject to certain additional terms pursuant to
# Section 7 of the GNU Affero General Public License.  You should have
# received a copy of these additional terms immediately following the
# terms and conditions of the GNU Affero General Public License that
# accompanied this program.
#
# If not, please request a copy through one of the means of contact
# listed here: <https://glutanimate.com/contact/>.
#
# Any modifications to this file must keep this entire header intact.

from contextlib import contextmanager
from types import ModuleType
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterator, List, Optional

from anki.importing.apkg import AnkiPackageImporter

from ._addons import ConfigPaths, create_addon_config
from ._anki import AnkiStateUpdate, get_collection, update_anki_state
from ._errors import AnkiSessionError
from ._types import PathLike

if TYPE_CHECKING:
    from anki.collection import Collection
    from aqt import AnkiApp
    from aqt.main import AnkiQt


class AnkiSession:
    def __init__(self, app: "AnkiApp", mw: "AnkiQt", user: str, base: str):
        """Anki test session object, returned by anki_session fixture.

        Contains a number of helpful properties and methods to characterize and
        interact with a running Anki test session.

        Arguments:
            app {AnkiApp} -- Anki QApplication instance
            mw {AnkiQt} -- Anki QMainWindow instance
            user {str} -- User profile name (e.g. "User 1")
            base {str} -- Path to Anki base directory
        """

        self._app = app
        self._mw = mw
        self._user = user
        self._base = base

    # Key session properties ####

    @property
    def app(self) -> "AnkiApp":
        """Anki's current QApplication instance"""
        return self._app

    @property
    def mw(self) -> "AnkiQt":
        """Anki's current main window instance"""
        return self._mw

    @property
    def user(self) -> str:
        """The current user profile name (e.g. 'User 1')"""
        return self._user

    @property
    def base(self) -> str:
        """Path to Anki base directory"""
        return self._base

    # Collection and profiles ####

    @property
    def collection(self) -> "Collection":
        """Returns current Anki collection if loaded"""
        return get_collection(self._mw)

    def load_profile(self) -> "Collection":
        """Load Anki profile, returning user collection

        Note: In a multi-profile configuration this method will raise the profile
        selection dialog, blocking until a profile is selected via UI interaction
        """
        self._mw.setupProfile()
        if self._mw.col is None:
            raise AnkiSessionError("Could not load collection")
        return self._mw.col

    def unload_profile(self, on_profile_unloaded: Optional[Callable] = None):
        """Unload current profile, optionally running a callback when profile
        unload complete"""
        if on_profile_unloaded is None:
            on_profile_unloaded = lambda *args, **kwargs: None  # noqa: E731
        self._mw.unloadProfile(on_profile_unloaded)

    @contextmanager
    def profile_loaded(self) -> Iterator["Collection"]:
        """Context manager that takes care of loading and then tearing down
        user profile"""
        collection = self.load_profile()

        yield collection

        self.unload_profile()

    # Deck management ####

    def install_deck(self, path: PathLike) -> int:
        """Install deck from specified .apkg file, returning deck ID"""
        old_ids = set(self._get_deck_ids())

        importer = AnkiPackageImporter(col=self.collection, file=str(path))
        importer.run()

        new_ids = set(self._get_deck_ids())

        # deck IDs are strings on <=2.1.26
        deck_id = int(next(iter(new_ids - old_ids)))

        return deck_id

    def remove_deck(self, deck_id: int):
        """Remove deck as specified by provided deck ID"""
        try:  # 2.1.28+
            # Deck methods on 2.1.45 and up use a DeckId NewType derived from int.
            # This only makes a difference at type-check time, so we stick with
            # passing in an int for now.
            self.collection.decks.remove([deck_id])  # type: ignore[list-item]
        except AttributeError:  # legacy
            self.collection.decks.rem(deck_id, cardsToo=True)

    @contextmanager
    def deck_installed(self, path: PathLike) -> Iterator[int]:
        """Context manager that takes care of installing deck and then removing
        it upon context completion"""
        deck_id = self.install_deck(path=path)

        yield deck_id

        self.remove_deck(deck_id=deck_id)

    def _get_deck_ids(self) -> List[int]:
        try:  # 2.1.28+
            return [d.id for d in self.collection.decks.all_names_and_ids()]
        except AttributeError:  # legacy
            return self.collection.decks.allIds()  # type: ignore[attr-defined]

    # Add-on loading ####

    def load_addon(self, package_name: str) -> ModuleType:
        """Dynamically import an add-on as specified by its package name"""
        addon_package = __import__(package_name)
        return addon_package

    # Add-on config handling ####

    def create_addon_config(
        self,
        package_name: str,
        default_config: Optional[Dict[str, Any]] = None,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> ConfigPaths:
        """Create and populate the config.json and meta.json configuration
        files for an add-on, as specified by its package name"""
        if default_config is None and user_config is None:
            raise ValueError(
                "Need to provide at least one of default_config, user_config"
            )

        return create_addon_config(
            anki_base_dir=self._base,
            package_name=package_name,
            default_config=default_config,
            user_config=user_config,
        )

    @contextmanager
    def addon_config_created(
        self,
        package_name: str,
        default_config: Optional[Dict[str, Any]] = None,
        user_config: Optional[Dict[str, Any]] = None,
    ) -> Iterator[ConfigPaths]:
        """Context manager that takes care of creating the configuration files
        for an add-on, as specified by its package name, and then deleting them
        upon context exit."""
        if default_config is None and user_config is None:
            raise ValueError(
                "Need to provide at least one of default_config, user_config"
            )

        config_paths = self.create_addon_config(
            package_name=package_name,
            default_config=default_config,
            user_config=user_config,
        )

        yield config_paths

        if config_paths.default_config and config_paths.default_config.exists():
            config_paths.default_config.unlink()

        if config_paths.user_config and config_paths.user_config.exists():
            config_paths.user_config.unlink()

    # Anki config object handling ####

    def update_anki_state(self, anki_state_update: AnkiStateUpdate):
        """Set the state of certain Anki storage objects that are frequently used by add-ons.
        This includes mw.col.conf (colconf_storage), mw.pm.profile (profile_storage),
        and mw.pm.meta (meta_storage).

        The combined state of all objects is supplied as a pytest_anki.AnkiStateUpdate
        data class.
        """
        update_anki_state(main_window=self._mw, anki_state_update=anki_state_update)
