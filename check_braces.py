with open('C:\\projects\\UrbanOS\\backend\\app\\main.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Find the function definition
idx = content.find('def _build_app')
if idx >= 0:
    print('Function starts at:', idx)
    # Find the return statement
    func_body = content[idx:]
    brace_count = 0
    in_str = False
    for i, ch in enumerate(func_body):
        if ch == '{' and not in_str:
            brace_count += 1
        elif ch == '}' and not in_str:
            brace_count -= 1
            if brace_count == 0:
                print(f'Function ends at offset {i} in func_body (absolute {idx + i})')
                print('Context:', repr(func_body[max(0,i-50):i+50]))
                break
        elif ch == '"':
            in_str = not in_str