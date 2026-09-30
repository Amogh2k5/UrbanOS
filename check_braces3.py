with open('C:\\projects\\UrbanOS\\backend\\app\\main.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Find the function start
idx = content.find('def _build_app')
if idx < 0:
    print('Function not found')
    exit()

# Count braces from function start
brace_count = 0
in_str = False
for i, ch in enumerate(content[idx:], idx):
    if ch == '{':
        brace_count += 1
    elif ch == '}':
        brace_count -= 1
        if brace_count == 0:
            print(f'Brace count zero at absolute position {i}')
            print(f'Context: {repr(content[i-50:i+50])}')
            break
    elif ch == '"':
        in_str = not in_str
    elif ch == "'" and not in_str:
        in_str = not in_str

print(f'Final brace count: {brace_count}')