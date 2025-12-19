import re

# Read the file
with open(r'c:\Users\Home\OneDrive\Documents\laundry-link\templates\super_admin_reports.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix indentation for lines 387-435 (inside the first if block)
fixed_lines = []
in_uptime_chart = False
in_status_chart = False

for i, line in enumerate(lines):
    line_num = i + 1
    
    # Detect the start of the uptime chart block
    if 'const deviceLabels' in line:
        in_uptime_chart = True
        fixed_lines.append(line)
        continue
    
    # Detect the end of the uptime chart block
    if in_uptime_chart and line.strip() == '}':
        # Check if this is the closing brace for the Chart constructor
        if i > 0 and 'scales' in ''.join(lines[max(0, i-10):i]):
            in_uptime_chart = False
            fixed_lines.append(line)
            continue
    
    # Fix indentation for uptime chart content
    if in_uptime_chart and line.startswith('        ') and not line.startswith('                '):
        # Add 8 more spaces (2 levels of indentation)
        line = '        ' + line
    
    # Detect the start of the status chart block
    if 'const statusDistribution' in line:
        in_status_chart = True
        fixed_lines.append(line)
        continue
    
    # Detect the end of the status chart block  
    if in_status_chart and line.strip() == '}':
        # Check if this is the closing brace for the Chart constructor
        if i > 0 and 'plugins' in ''.join(lines[max(0, i-10):i]):
            in_status_chart = False
            fixed_lines.append(line)
            continue
    
    # Fix indentation for status chart content
    if in_status_chart and line.startswith('        ') and not line.startswith('                '):
        # Add 8 more spaces
        line = '        ' + line
    
    fixed_lines.append(line)

# Write the file back
with open(r'c:\Users\Home\OneDrive\Documents\laundry-link\templates\super_admin_reports.html', 'w', encoding='utf-8') as f:
    f.writelines(fixed_lines)

print("Indentation fixed successfully!")
