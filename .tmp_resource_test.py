from mcp_server import mcp_app
import json

code = '0027g'

def call_impl(obj, *args):
    func = getattr(obj, 'fn', None) or getattr(obj, '__wrapped__', None) or obj
    if callable(func):
        return func(*args)
    raise RuntimeError('not callable')

# call profile resource implementation
try:
    res = call_impl(mcp_app.character_profile_resource, code)
    print('profile resource returned:', type(res))
    if hasattr(res, 'contents'):
        for c in res.contents:
            print(' - mime:', getattr(c, 'mime_type', None), 'len:', len(getattr(c, 'content', b'')))
except Exception as e:
    print('ERROR calling profile resource:', e)

try:
    res2 = call_impl(mcp_app.character_profile_image, code)
    print('profile image resource returned:', type(res2))
    if hasattr(res2, 'contents'):
        for c in res2.contents:
            print(' - mime:', getattr(c, 'mime_type', None), 'len:', len(getattr(c, 'content', b'')))
except Exception as e:
    print('ERROR calling image resource:', e)

# call resource-as-tool (if added) via wrapper names if present
try:
    if hasattr(mcp_app.mcp, 'list_resources'):
        print('mcp has list_resources tool')
except Exception:
    pass
