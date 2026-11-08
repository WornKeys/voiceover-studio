# 2. The UI

The studio's page is built with [Gradio](https://www.gradio.app/), a Python library for model demos and small
tools. You describe the page in Python (components and events), and Gradio serves the HTML and JavaScript. The
whole UI is one file: [`voiceover_studio/ui.py`](../../voiceover_studio/ui.py).

## Gradio in five minutes

Three ideas cover almost everything in `ui.py`:

1. **Blocks and components.** `with gr.Blocks() as ui:` opens a page. Inside it, each component (`gr.Textbox`,
   `gr.Dropdown`, `gr.Audio`, `gr.Button`, `gr.Markdown`…) is placed in the order you create it. Layout helpers
   such as `gr.Row()` and `gr.Accordion()` are context managers too.
2. **Events.** `button.click(fn, inputs, outputs)` means: when clicked, read the current values of `inputs`, call
   `fn` with them, and put what it returns into `outputs`, in the same order.
3. **Updates.** A function can return a new value for an output, or `gr.update(...)` to change its properties
   instead: `gr.update(choices=..., value=..., visible=True)`. Returning `gr.update()` with no arguments leaves
   that output unchanged.

That's how the steps work: an accordion is just another output, and a handler returns
`gr.update(label="✓ 1. Your voice: …", open=False)` to collapse it into a summary.

## The page: three steps

`build_ui(services)` builds the page from `services.info()`: the consent sentence, the sample length limits, the
voice model's languages, the enabled plugins and their settings.

```text
INTRO
▸ 1. Your voice              saved voices · "Use this voice" · record + save
▸ 2. Your script             describe · length · language · tone · audience · draft · script · optional tools
▸ 3. Generate the voiceover  summary · generate · player · downloads
```

- **Step state lives in the components.** There's no separate state object: the selected voice is the dropdown's
  value, the script is the textbox's value, the language is the language dropdown's value. Handlers take what they
  need as inputs.
- **The first view depends on the data.** With a saved voice, step 1 starts collapsed with the newest voice as its
  summary, and step 2 starts open. A returning user lands on the script.
- **Readable labels.** `voice_label` turns `2026-11-08T09:05:00+00:00` and an id into "Recorded 8 Nov 2026, 09:05
  UTC (a1b2)". `language_choices` turns codes into names: Gradio dropdowns accept `(label, value)` pairs, so the
  user sees "German" while the code keeps `de`.

## The handlers

Each event handler is a small function inside `build_ui`, so it can use `services` directly (a closure). They
follow one pattern: try the action, and on a known error return a plain-language message instead of a stack trace.

```python
def write_script(description, audience, tone, seconds, language):
    try:
        draft = services.draft_script(
            ScriptRequest(description or "", float(seconds), audience, tone, language)
        )
    except (ScriptRefusedError, ValueError) as exc:
        return gr.update(), f"**Not written.** {exc}"
    return draft.text, "Draft written. Edit it below, or try the optional tools."
```

A few worth reading:

- **`save_voice`** returns six outputs: the message, the voice dropdown, the voice buttons, both accordions and the
  recording. With quality warnings it keeps step 1 open so the warnings get read; without them it collapses step 1
  and opens step 2.
- **`delete_voice`** is wired with a bit of JavaScript that runs in the browser first:
  `js="(v) => (v && confirm('Delete this voice? …')) ? v : null"`. If you cancel, the Python function gets `None`
  and does nothing.
- **`next_to_generate`** refuses to move on without a script, then collapses step 2 into a summary ("35 words,
  about 14 s, English") and opens step 3 with a summary of exactly what will be used.

## Plugins without UI code

The optional tools in step 2 are built from data. Each plugin declares its settings as a pydantic model; the
manifest carries its JSON schema, and `component_for` turns each property into a control:

| In the schema | Becomes |
|---|---|
| a number with `minimum` and `maximum` | a slider |
| `enum` | a dropdown (with language names if the field is a language) |
| boolean | a checkbox |
| anything else | a textbox |

The handler for every plugin is the same function, `run`, with the plugin's name bound as a default argument
(`_name=manifest["name"]`). That's a common Python idiom: without it, every button would call the *last* plugin in
the loop. A plugin may change the language too (translate does), so `run` returns it, and the language dropdown
follows.

## Progress while rendering

`generate` is a **generator**: Gradio streams each `yield` to the page. It submits the render job, then polls it
once a second:

```python
while job.status in ("queued", "running"):
    if job.total:
        progress((job.done, job.total), desc="Sentences spoken", unit="sentences")
        yield f"Speaking sentence {min(job.done + 1, job.total)} of {job.total}...", None, None
    time.sleep(1)
```

`progress` is a `gr.Progress()` default argument, Gradio's way of drawing a progress bar on the outputs. When the
job finishes, the files are fetched from storage into a temporary folder and returned to the player and the
download list.

## Look and feel

`THEME` (slate greys, graphite primary buttons, the system font) and a few lines of `CSS` (page width, no footer)
are passed to `gr.mount_gradio_app` in `__main__.py`. In Gradio 6 that's where they go: `gr.Blocks` no longer
takes a theme. Light and dark follow the browser's setting.

## Why the microphone needs localhost

Browsers only allow microphone access on secure pages: HTTPS, or `localhost`. The studio has no public address
and no certificate; through the SSM tunnel (chapter 4) it's `http://localhost:7860`, which counts as secure. One
browser-specific catch: in Brave, the recorder freezes. Brave's fingerprinting protection slows down how pages
read recorded audio, and Gradio's recorder reads it one sample at a time. Firefox works.

## How the UI is tested without a browser

Gradio keeps every event's Python function in `ui.fns`. The tests in [`tests/test_ui.py`](../../tests/test_ui.py)
look handlers up by name and call them directly, which drives the whole guided flow (save a voice, use it, write
a script, move on, generate) in about a second:

```python
def handler(ui: gr.Blocks, name: str):
    return next(f.fn for f in ui.fns.values() if f.fn and f.fn.__name__ == name)


hint, step1, step2 = handler(ui, "choose_voice")(voice_id)
assert step1["label"].startswith("✓ 1. Your voice: Recorded ") and step2["open"] is True
```

What this can't test is the browser itself: the recorder, the layout, the theme. That's what the dry run on a
real instance was for.

## Idle tracking

The instance stops itself when nobody uses the studio. "Using" is defined in `ActivityTracker` in
[`api.py`](../../voiceover_studio/api.py): opening the page or any action (a POST, PUT or DELETE) counts. Plain
reads don't, because an open browser tab keeps polling with GETs, and a tab you forgot must not keep a GPU
running. A middleware on the FastAPI app sees every request, including Gradio's, and `/api/activity` reports the
idle time to the instance's timer.
