import re

with open('F:/spendly/templates/profile.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix: most Jinja vars are missing closing }} — they look like {{ foo<endquote>
# Strategy: any {{ that's NOT immediately followed by '{' and that doesn't have }} soon
# should get }} appended.

# Step 1: {{ word\n  → {{ word }}\n   (newline case)
content = re.sub(r'(\{\{\s*\w[\w.]*)\s*\n', r'\1 }}\n', content)

# Step 2: {{ word followed by HTML tag start, quote, or backslash
content = re.sub(r'(\{\{\s*\w[\w.]*)\s*(</|<a| style=")', r'\1 }} \2', content)

# Step 3: {{ word followed by literal {{ or {% or end of string
# For remaining cases where it's just a dangling {{ ... without }}
# e.g.  {{ tx.amount  →  {{ tx.amount }}
content = re.sub(r'(\{\{\s*\w[\w.]*)(\s*\}\}?|\s*$)', lambda m: m.group(1) + ' }}', content)

# Step 3 fixup: ensure we don't double-close already-closed ones
# Remove any triple-closing braces
content = re.sub(r'\}\}\s*\}\}', r'}}', content)

with open('F:/spendly/templates/profile.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed. Checking key lines:")
for i, line in enumerate(content.split('\n'), 1):
    if '{{' in line and i <= 25:
        print(f"{i}: {line}")