import fastmcp
import importlib
import pkgutil
print('fastmcp version:', getattr(fastmcp, '__version__', 'unknown'))
print('fastmcp module file:', fastmcp.__file__)

try:
    import fastmcp.resources as resmod
    print('\nfastmcp.resources module:', resmod)
    print('module file:', getattr(resmod, '__file__', None))
    names = dir(resmod)
    print('\nnames in fastmcp.resources:', [n for n in names if not n.startswith('__')])
    # try to import common names
    for name in ('ResourceResult','ResourceContent','Resource','ResourceContents'):
        try:
            obj = getattr(resmod, name)
            print(f'Found {name}:', obj)
        except AttributeError:
            print(f'Not found: {name}')
except Exception as e:
    print('could not import fastmcp.resources:', e)

# inspect submodules
print('\nSubmodules under fastmcp.resources:')
for finder, name, ispkg in pkgutil.iter_modules(fastmcp.resources.__path__):
    print(' -', name, 'pkg' if ispkg else 'mod')

# try common alternative paths
alts = [
    'fastmcp.resources.types',
    'fastmcp.server.resources',
    'fastmcp.resources.base',
]
for a in alts:
    try:
        m = importlib.import_module(a)
        print(f'Imported {a}:', m)
        print('names:', [n for n in dir(m) if not n.startswith('__')][:50])
    except Exception as e:
        print(f'Cannot import {a}:', e)
