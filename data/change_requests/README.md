# data/change_requests/

Drop zone for change-request `.json` files exported by the "+ Add Activity"
quick-capture form on the **public GitHub Pages site**
(`web/index_template.html`). That page has no backend, so instead of writing
to the journal directly it downloads a small JSON file describing the
activity you just captured.

To apply what's in here: ask Claude (in the Cowork workspace) to run

```
python3 scripts/journal.py import-all
```

which reads every `.json` file in this folder, creates the corresponding
Partner Value Journal entry (skipping anything already imported — matched by
the file's `request_id`, so re-running this is always safe), and moves
processed files into `processed/` so they don't get considered again.

You can also import one specific file:

```
python3 scripts/journal.py import-request --file data/change_requests/activity-CR-....json
```

The Cowork dashboard's own "+ Add Activity" form doesn't use this folder at
all — it can talk to Claude directly, so it applies the entry immediately
with no export/import round-trip. This folder only exists for the
public-site path, where that's not possible.

Files in here are plain data (JSON), never executable — see
`scripts/journal.py`'s `_check_no_executable_content()` for the guard that
refuses to import anything that looks like it's trying to smuggle markup or
script content through a text field.
