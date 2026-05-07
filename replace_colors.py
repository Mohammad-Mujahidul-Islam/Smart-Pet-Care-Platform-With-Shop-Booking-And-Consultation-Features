import os
import re

directories = ['templates', 'static/js']

# Replacements for backgrounds
bg_replacements = [
    (re.compile(r'bg-\[\#5AB9B4\]'), 'bg-gradient-to-r from-green-400 to-blue-500'),
    (re.compile(r'hover:bg-\[\#4a9c98\]'), 'hover:from-green-500 hover:to-blue-600'),
    (re.compile(r'bg-indigo-600'), 'bg-gradient-to-r from-green-400 to-blue-500'),
    (re.compile(r'hover:bg-indigo-700'), 'hover:from-green-500 hover:to-blue-600'),
    (re.compile(r'shadow-indigo-100'), 'shadow-blue-100'),
    (re.compile(r'shadow-indigo-200'), 'shadow-blue-200'),
    (re.compile(r'bg-indigo-50/30'), 'bg-teal-50/30'),
    (re.compile(r'hover:bg-indigo-50'), 'hover:bg-teal-50'),
    (re.compile(r'border-indigo-200'), 'border-teal-200'),
    (re.compile(r'ring-indigo-100'), 'ring-teal-100'),
    (re.compile(r'focus-within:border-indigo-500'), 'focus-within:border-teal-500'),
    (re.compile(r'focus-within:ring-indigo-100'), 'focus-within:ring-teal-100'),
    (re.compile(r'bg-indigo-500/10'), 'bg-gradient-to-r from-green-400/10 to-blue-500/10'),
    (re.compile(r'text-indigo-400'), 'text-teal-500'),
    (re.compile(r'bg-indigo-400'), 'bg-green-400'),
    (re.compile(r'bg-indigo-500'), 'bg-blue-500'),
]

# Replacements for text
text_replacements = [
    (re.compile(r'text-indigo-600'), 'text-transparent bg-clip-text bg-gradient-to-r from-green-400 to-blue-500'),
    (re.compile(r'group-hover:text-indigo-600'), 'group-hover:text-transparent group-hover:bg-clip-text group-hover:bg-gradient-to-r group-hover:from-green-400 group-hover:to-blue-500'),
    (re.compile(r'hover:text-indigo-600'), 'hover:text-transparent hover:bg-clip-text hover:bg-gradient-to-r hover:from-green-400 hover:to-blue-500'),
    (re.compile(r'hover:text-indigo-700'), 'hover:text-transparent hover:bg-clip-text hover:bg-gradient-to-r hover:from-green-500 hover:to-blue-600'),
    # for text-[#5AB9B4] -> text-transparent bg-clip-text ...
    # but wait, if it's on an svg, bg-clip-text breaks it.
    # So we will change text-[#5AB9B4] to text-teal-500 for safety, as gradient text on SVGs is broken in tailwind without masks
    (re.compile(r'text-\[\#5AB9B4\]'), 'text-teal-500'),
    (re.compile(r'hover:text-\[\#5AB9B4\]'), 'hover:text-teal-600'),
    (re.compile(r'ring-\[\#5AB9B4\]'), 'ring-teal-500'),
    (re.compile(r'border-\[\#5AB9B4\]'), 'border-teal-500'),
    (re.compile(r'hover:border-\[\#5AB9B4\]'), 'hover:border-teal-500'),
    (re.compile(r'focus:border-\[\#5AB9B4\]'), 'focus:border-teal-500'),
    (re.compile(r'focus:ring-\[\#5AB9B4\]'), 'focus:ring-teal-500'),
]

for d in directories:
    if not os.path.exists(d): continue
    for root, _, files in os.walk(d):
        for file in files:
            if file.endswith('.html') or file.endswith('.js'):
                path = os.path.join(root, file)
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                new_content = content
                for pattern, repl in bg_replacements + text_replacements:
                    new_content = pattern.sub(repl, new_content)
                
                if new_content != content:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f"Updated {path}")
