import os

with open('templates/dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the pdf-wrapper block entirely
start_marker = "<!-- OVERLAY DE CARREGAMENTO & CONTAINER DO RELATÓRIO PDF -->"
end_marker = '  </div>\n</div>\n\n<script src="https://cdn.socket.io'
if end_marker not in content:
    end_marker = '  </div>\n\n<script src="https://cdn.socket.io'

if start_marker in content and end_marker in content:
    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker)
    # Just to be safe, leave the script tags
    content = content[:start_idx] + '\n<script src="https://cdn.socket.io' + content[end_idx + len('  </div>\n\n<script src="https://cdn.socket.io'):]
    with open('templates/dashboard.html', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Cleaned up dashboard.html")
else:
    print("Could not find markers to clean up dashboard.html")
