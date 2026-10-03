with open(r'C:\projects\UrbanOS\frontend\src\app\page.tsx', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix:
# 1. Line 512 (index 511): Add closing )} after the MODULES.map block ends at line 546
# 2. Remove line 547 (index 546) - the extra <div>
# 3. Line 548 (index 547) - the section should be at proper level

# The structure should be:
# Line 511: '            )}' - closes the {overviewCityError && ...} block
# Line 512: '{overviewCity && ...' - starts new conditional, needs closing )} after line 546
# Lines 513-546: MODULES.map block
# Line 547: '              </div>' - closes the grid div
# Then need '            )}' to close the conditional
# Then '          </section>' to close the Module Intelligence section
# Then Alerts section starts

# Current state:
# Line 511: '            )}' - closes error block
# Line 512: '{overviewCity && ...' - starts conditional
# Lines 513-546: MODULES.map
# Line 546: '              </div>' - closes grid div
# Line 547: '                        <div className="mt-2 text-xs text-gray-400">' - EXTRA, REMOVE
# Line 548: '          <section className="mb-6">' - Alerts section starts but at wrong level

# Fix: remove line 547, add closing )} after line 546, then add </section> before alerts

new_lines = []
for i, line in enumerate(lines):
    line_num = i + 1
    # Skip the extra line 547
    if line_num == 547:
        continue
    # After line 546 (which is '              </div>\n'), add closing )} and </section>
    if line_num == 546:
        new_lines.append(line)
        new_lines.append('            )}\n')
        new_lines.append('          </section>\n')
        # The next line (originally 548, now 547 after skip) is the Alerts section - keep it
        continue
    new_lines.append(line)

with open(r'C:\projects\UrbanOS\frontend\src\app\page.tsx', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print('Fixed!')