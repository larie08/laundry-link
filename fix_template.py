import re

# Read the file
with open(r'c:\Users\Home\OneDrive\Documents\laundry-link\templates\super_admin_reports.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the first broken Jinja2 tag
content = re.sub(
    r'                const deviceLabels = \{\{ stats\.device_labels \| tojson\r?\n            \}\r?\n        \};\r?\n        const deviceUptimes',
    '                const deviceLabels = {{ stats.device_labels | tojson }};\r\n                const deviceUptimes',
    content
)

# Fix the second broken Jinja2 tag  
content = re.sub(
    r'            const statusDistribution = \{\{ stats\.device_status_distribution \| tojson\r?\n        \}\};',
    '                const statusDistribution = {{ stats.device_status_distribution | tojson }};',
    content
)

# Fix indentation issues
content = re.sub(
    r'\r?\n        // Color code',
    '\r\n                \r\n                // Color code',
    content
)

content = re.sub(
    r'\r?\n        const uptimeColors',
    '\r\n                const uptimeColors',
    content
)

content = re.sub(
    r'\r?\n        new Chart\(uptimeCtx',
    '\r\n                new Chart(uptimeCtx',
    content
)

content = re.sub(
    r'\r?\n        new Chart\(deviceStatusCtx',
    '\r\n                new Chart(deviceStatusCtx',
    content
)

# Write the file back
with open(r'c:\Users\Home\OneDrive\Documents\laundry-link\templates\super_admin_reports.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("File fixed successfully!")
