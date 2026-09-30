with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'r') as f:
    content = f.read()

idx = content.find('Selected Stand Popup')
if idx >= 0:
    # Find the matching closing
    paren = 0
    brace = 0
    in_str = False
    esc = False
    start = idx
    end = -1
    for i, ch in enumerate(content[start:], start):
        if ch == '(' and not in_str:
            paren += 1
        elif ch == ')' and not in_str:
            paren -= 1
        elif ch == '{' and not in_str:
            brace += 1
        elif ch == '}' and not in_str:
            brace -= 1
        elif ch == '"':
            in_str = not in_str
        if paren == 0 and brace == 0 and i > start:
            end = i + 1
            break
    
    if end > 0:
        print(f'Start: {start}, End: {end}')
        print(f'Length: {end - start}')
        # Remove the popup
        new_content = content[:start] + content[end:]
        with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'w') as f:
            f.write(new_content)
        print('Removed popup successfully!')
    else:
        print('Could not find end')
else:
    print('Popup not found')