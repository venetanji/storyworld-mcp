import json
from mcp_server import mcp_app

code = '0027g'
# call underlying wrapped function if present
def call_tool(tool, *args):
    func = getattr(tool, 'fn', None) or getattr(tool, '__wrapped__', None) or tool
    if callable(func):
        return func(*args)
    raise RuntimeError('tool not callable')

try:
    ctx = call_tool(mcp_app.get_character_context, code)
    print('get_character_context:')
    print(json.dumps(ctx, indent=2, ensure_ascii=False))

    imgs = call_tool(mcp_app.list_character_images, code)
    print('\nlist_character_images (paths):')
    for i in imgs:
        # if Image object, print its path attribute if present
        p = getattr(i, 'path', None)
        print(' -', p)
except Exception as e:
    import traceback
    traceback.print_exc()
    print('ERROR', e)
