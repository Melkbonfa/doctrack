import os

with open('static/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the html2canvas config line
old_line = "html2canvas: { scale: 4, useCORS: true, backgroundColor: '#0f0f28' },"
new_line = "html2canvas: { scale: 4, useCORS: true, backgroundColor: '#0f0f28', windowWidth: 794, windowHeight: 1123, width: 794, height: 1123 },"
content = content.replace(old_line, new_line)

with open('static/app.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("done js")
