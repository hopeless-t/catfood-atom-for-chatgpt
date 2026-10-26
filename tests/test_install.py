#!/usr/bin/env python3
from __future__ import annotations

import plistlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import install  # noqa: E402


def main():
    spaced = Path('/tmp/CAT FOOD & TEST/app')

    service, unit = install.linux_unit(spaced)
    assert service.name == 'catfood-atom.service'
    assert 'ExecStart=' in unit
    assert f'"{spaced / "atomd.py"}"' in unit
    assert '--host 127.0.0.1 --port 8766' in unit

    plist_path, xml = install.macos_plist(spaced)
    assert plist_path.name == 'com.catfood.atom.chatgpt.plist'
    data = plistlib.loads(xml.encode())
    assert data['Label'] == install.LABEL
    assert data['ProgramArguments'][1] == str(spaced / 'atomd.py')
    assert data['RunAtLoad'] is True and data['KeepAlive'] is True

    startup, cmd = install.windows_startup_file(spaced)
    assert startup.name == 'catfood-atom.cmd'
    assert str(spaced / 'atomd.py') in cmd
    assert '--host 127.0.0.1 --port 8766' in cmd

    for kind in ('linux', 'macos', 'windows'):
        app = install.app_dir(kind)
        state = install.state_dir(kind)
        assert app != state
        assert app.name in {'catfood-atom-for-chatgpt', 'app'}
        assert state.name in {'catfood-atom', 'state'}

    print('PASS cross-platform installer generation')


if __name__ == '__main__':
    main()
