#!/usr/bin/env python3
import re, sys, os

if len(sys.argv) < 2:
    print('Usage: continue_markdown.py <path-to-md-file>')
    sys.exit(1)

md_path = sys.argv[1]
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app_py = os.path.join(repo_root, 'app.py')

# Prefer OPENAI_API_KEY environment variable. If missing, prompt interactively.
openai_api_key = os.environ.get('OPENAI_API_KEY')
if not openai_api_key:
    try:
        openai_api_key = input('Enter your OpenAI API key (sk-...): ').strip()
    except Exception:
        openai_api_key = None
    if not openai_api_key:
        print('No OpenAI API key provided; aborting')
        sys.exit(2)

try:
    import openai
except Exception as e:
    print('openai package not available:', e)
    sys.exit(3)

openai.api_key = openai_api_key

with open(md_path, 'r') as f:
    text = f.read()

# Find first fenced block
fence_open = re.search(r'```(?:markdown)?\s*', text)
if not fence_open:
    # nothing to continue
    print('No fenced markdown block found; aborting')
    sys.exit(0)

# Check if there's a closing fence
closing_idx = text.rfind('```')
# If closing fence equals opening index, then it's missing
open_idx = fence_open.end()
if closing_idx <= fence_open.start():
    inner = text[open_idx:]
    had_closing = False
else:
    inner = text[open_idx:closing_idx]
    had_closing = True

inner_stripped = inner.rstrip()
# Heuristic: if last non-space char is a single letter or ends abruptly, request continuation
last_non_ws = inner_stripped[-1:] if inner_stripped else ''
need_cont = False
if last_non_ws.isalpha() or len(inner_stripped.splitlines()[-1].strip()) < 6 and not inner_stripped.strip().endswith(('.', ':')):
    need_cont = True

if not need_cont:
    print('No obvious truncation detected. Last char:', repr(last_non_ws))
    sys.exit(0)

# Provide the tail of the existing content to help the model continue
last_snippet = inner_stripped[-2000:] if inner_stripped else ''
cont_prompt = "The previous response you generated may have been truncated. Continue the markdown report from where it likely left off; do not repeat earlier content. Keep the same style and finish the current section.\n\nHere is the end of the current report (use this as context and continue from its end):\n\n" + last_snippet
print('Requesting continuation from the LLM...')
try:
    # Send prior content as assistant-role message, then instruct as user to continue
    messages = [
        {'role': 'assistant', 'content': last_snippet},
        {'role': 'user', 'content': 'Please continue the markdown report immediately from the end of the assistant message above. Do NOT ask for the snippet again; continue the existing style and headings.'}
    ]
    resp = openai.chat.completions.create(model='gpt-4o', messages=messages, max_completion_tokens=600)
    cont_text = None
    if resp.choices:
        c = resp.choices[0]
        if hasattr(c, 'message') and hasattr(c.message, 'content'):
            cont_text = c.message.content
        elif hasattr(c, 'text'):
            cont_text = c.text
    if not cont_text:
        print('No continuation text received')
        sys.exit(4)
    # Append continuation before closing fence (or add closing fence)
    if had_closing:
        new_text = text[:closing_idx] + '\n\n' + cont_text.strip() + '\n```' + text[closing_idx+3:]
    else:
        new_text = text + '\n\n' + cont_text.strip() + '\n```'
    with open(md_path, 'w') as f:
        f.write(new_text)
    print('Continuation appended to', md_path)
    print('\n--- appended text start ---\n')
    print(cont_text)
    print('\n--- appended text end ---\n')
except Exception as e:
    print('Error calling OpenAI:', e)
    sys.exit(5)
