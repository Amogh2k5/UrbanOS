with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'r') as f:
    content = f.read()

# Find the main return
main_return_pos = content.find('  return (\n    <div className="h-full bg-')
print(f'Main return at position: {main_return_pos}')

# Check parens/braces from there
paren_count = 0
brace_count = 0
for i, ch in enumerate(content[main_return_pos:]):
    if ch == '(':
        paren_count += 1
    elif ch == ')':
        paren_count -= 1
    elif ch == '{':
        brace_count += 1
    elif ch == '}':
        brace_count -= 1
    if paren_count < 0 or brace_count < 0:
        context_start = max(0, i - 100)
        context_end = min(len(content), i + 100)
        print(f'NEGATIVE at offset {main_return_pos + i}: paren={paren_count}, brace={brace_count}')
        print(f'Context: {repr(content[context_start:context_end])}')
        break
    if i % 5000 == 0 and i > 0:
        print(f'Progress: offset {i}, paren={paren_count}, brace={brace_count}')

print(f'Final: paren={paren_count}, brace={brace_count}')