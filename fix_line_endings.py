with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'rb') as f:
    content = f.read()

# Normalize line endings to \n
content = content.replace(b'\r\n', b'\n')

with open('C:\\projects\\UrbanOS\\frontend\\src\\app\\mobility\\roads\\page.tsx', 'wb') as f:
    f.write(content)

print('Normalized line endings to LF')