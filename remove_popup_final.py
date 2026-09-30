with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'r') as f:
    content = f.read()

# Find the popup start
start = content.find('false && selectedStand && (')
if start >= 0:
    # Find the matching closing
    paren = 0
    brace = 0
    in_str = False
    esc = False
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
        if paren == 0 and brace == 0 and i > 0:
            end = i + 1
            break
    
    if end > 0:
        # Also include the comment before it
        comment_start = content.rfind('/*', 0, start)
        if comment_start >= 0 and content[comment_start:comment_start+50].find('Selected Stand Popup') >= 0:
            start = comment_start
        
        print(f'Start: {start}, End: {end}')
        print(f'Length: {end - start}')
        
        new_content = content[:start] + content[end:]
        with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'w') as f:
            f.write(new_content)
        print('Removed popup successfully!')
    else:
        print('Could not find end')
else:
    print('Popup start not found')