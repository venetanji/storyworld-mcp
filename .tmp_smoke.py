import json
from mcp_server import mcp_app, config

try:
    obj = mcp_app.get_character_context
    # Debug: show wrapper info if not callable
    if callable(obj):
        out = obj('0027g')
    else:
        # Try common attributes that hold the original function
        if hasattr(obj, 'fn') and callable(getattr(obj, 'fn')):
            out = obj.fn('0027g')
        elif hasattr(obj, 'run') and callable(getattr(obj, 'run')):
            # run may expect invocation payload; try calling directly
            try:
                out = obj.run('0027g')
            except Exception as e:
                out = {'error_run': str(e)}
        else:
            info = {
                'type': repr(type(obj)),
                'dir': [d for d in dir(obj) if not d.startswith('__')][:50]
            }
            out = {'error': 'tool not directly callable', 'wrapper': info}
    print(json.dumps(out, indent=2, ensure_ascii=False))
except Exception as e:
    import traceback
    traceback.print_exc()
    print('ERROR:', e)
