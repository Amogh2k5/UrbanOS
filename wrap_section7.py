with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'r') as f:
    content = f.read()

# Find the comment anchor
anchor = '{/* Interactive Map Section */}'
idx = content.find(anchor)
if idx >= 0:
    # The old string starts from the comment
    old = content[idx:idx+800]  # Get enough characters
    # Find the end of the mapData conditional
    # We'll replace from the comment to the end of the mapData conditional
    # But we need to be precise
    
    # Let's just do a simple replace of the comment and everything up to the mapData conditional end
    # Actually, let's just replace the specific section we want
    
    # Find the end of the mapData conditional
    # It ends with ')}' after the mapData conditional
    # But there might be multiple ')}' - we need the one that closes the mapData conditional
    
    # For now, let's just replace the comment and the section opening
    old_section = content[idx:idx+800]
    print('Old section:')
    print(repr(old_section[:300]))
else:
    print('Anchor not found')