# Deprecated — do not use this file as the email shell

**wrk-reviewer-ono** emails must use the Henry skill email template:

`~/.claude/skills/henry/templates/email-dark.html`

Also read: `~/.claude/skills/henry/SKILL.md` → Format adapters → Email.

That file is the inline-table, subject-agnostic shell (tables + inline hex + `{{…}}` slots).
Copy it, fill every slot from the Ono report mapping in `SKILL.md` Step 3, rewrite
every `img src` to a resized data-URI / https / CID before send.

Do not invent a layout and do not resurrect the old light bone report shell.
