"""Every global name a module's code reads exists once it is imported — a
stdlib stand-in for pyflakes' undefined-name check. A rebase once left
App.do_startup reading _LAYOUT_MODE after app.py had stopped importing it;
nothing here runs do_startup, so only the live service found out, by
crashing at startup."""

import builtins
import glob
import importlib
import os
import symtable

import pytest

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
_MODULES = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(_SRC, "*.py"))
                  if "-" not in os.path.basename(p))


def _read_globals(table):
    """Names a scope (and everything nested in it) reads as globals. At
    module level only names never assigned there: since Python 3.12 a
    module-level comprehension's loop variable lives in the module's own
    table, without ever existing on the module."""
    module = table.get_type() == "module"
    names = {s.get_name() for s in table.get_symbols()
             if s.is_referenced() and (not s.is_assigned() if module else s.is_global())}
    for child in table.get_children():
        names |= _read_globals(child)
    return names


@pytest.mark.parametrize("name", _MODULES)
def test_no_undefined_globals(monkeypatch, name):
    # Split mode imports the most: win.py pulls the split renderer in only then.
    monkeypatch.setenv("DECKERY_HUD_LAYOUT", "split")
    import win
    importlib.reload(win)
    mod = win if name == "win" else importlib.import_module(name)
    with open(os.path.join(_SRC, name + ".py")) as f:
        table = symtable.symtable(f.read(), name + ".py", "exec")
    missing = sorted(n for n in _read_globals(table)
                     if not hasattr(mod, n) and not hasattr(builtins, n))
    assert not missing, f"{name}.py reads undefined globals: {missing}"
