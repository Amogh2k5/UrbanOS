with open(r'C:\projects\UrbanOS\frontend\src\app\page.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the return statement and check brace balance
idx = content.find('return (')
if idx >= 0:
    brace_count = 0
    paren_count = 0
    in_string = False
    string_char = None
    for i, ch in enumerate(content[idx:]):
        if not in_string and ch in '\"\'':
            in_string = True
            string_char = ch
        elif in_string and ch == string_char and content[idx+i-1] != '\\':
            in_string = False
            string_char = None
        elif not in_string:
            if ch == '(':
                paren_count += 1
            elif ch == ')':
                paren_count -= 1
            elif ch == '{':
                brace_count += 1
            elif ch == '}':
                brace_count -= 1
        if paren_count == 0 and brace_count == 0 and i > 0:
            print(f'Balanced at offset {idx+i} (line {content[:idx+i].count(chr(10))+1})')
            break
    print(f'Final: paren={paren_count}, brace={brace_count}')
else:
    print('return ( not found')