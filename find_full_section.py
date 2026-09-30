with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'r') as f:
    content = f.read()

# Find the mapData conditional start
idx = content.find('{mapData && (')
print('mapData conditional at:', idx)
if idx >= 0:
    # Count parens and braces from here
    paren = 0
    brace = 0
    in_str = False
    end_idx = -1
    for i, ch in enumerate(content[idx:], 0):
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
        if paren == 0 and brace == 0 and i > 100:
            end_idx = i + 1
            print('Found end at offset:', i)
            print('Total length:', end_idx)
            print(repr(content[idx:idx+end_idx][-200:]))
            break
    
    if end_idx > 0:
        old_segment = content[idx:end_idx]
        print('\\nOld segment length:', len(old_segment))
        
        # Now find the comment anchor to get the full section
        comment_idx = content.rfind('{/* Interactive Map Section */}', 0, idx)
        if comment_idx >= 0:
            full_section = content[comment_idx:idx+len(content[idx:idx+end_idx])]
            print('Full section length:', len(full_section))
            print(repr(full_section[:500]))