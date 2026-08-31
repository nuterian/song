"""The stdlib-only modules must stay stdlib-only.

CI runs the suite with nothing installed, which is what makes it finish in
seconds. That only works while the modules under test can be imported without
numpy or torch behind them - a property one convenience re-export in a package
__init__ is enough to lose, silently, on any machine that happens to have them.

Importing a submodule runs its package's __init__ first, so `song.video.karaoke`
being on this list is also what holds `song/video/__init__.py` to resolving its
names lazily, the way `song/align/__init__.py` does.
"""

import importlib
import sys
import unittest


PURE = [
    "song.parse_lyrics",
    "song.project",
    "song.exports",
    "song.align.mapping",
    "song.align.gaps",
    "song.video.karaoke",
]

HEAVY = ("numpy", "torch", "torchaudio", "librosa", "whisper", "demucs", "faster_whisper")


class _Blocker:
    """A meta-path finder that refuses the heavy dependencies."""

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in HEAVY:
            raise ImportError(f"{name} is blocked: this module must not need it")
        return None


class PureModulesImportAlone(unittest.TestCase):
    def setUp(self):
        self._saved = dict(sys.modules)
        for name in list(sys.modules):
            if name.split(".")[0] in HEAVY or name.startswith("song"):
                del sys.modules[name]
        sys.meta_path.insert(0, _Blocker())

    def tearDown(self):
        sys.meta_path.pop(0)
        sys.modules.clear()
        sys.modules.update(self._saved)

    def test_each_pure_module_imports_with_no_third_party_available(self):
        for name in PURE:
            with self.subTest(module=name):
                importlib.import_module(name)

    def test_the_blocker_itself_works(self):
        # Otherwise the test above could pass by doing nothing at all.
        with self.assertRaises(ImportError):
            importlib.import_module("numpy")


if __name__ == "__main__":
    unittest.main()
