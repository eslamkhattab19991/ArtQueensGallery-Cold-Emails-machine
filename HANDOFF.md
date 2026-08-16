# Running the machine yourself

A plain-English guide for running the artist prospecting machine and checking its
work, without needing to read any code. If you can open a terminal and copy-paste,
you can run everything here.

For *why* the system is built the way it is, see [`ARCHITECTURE.md`](ARCHITECTURE.md).
For the results and the numbers, see `Artist Prospecting System - Full Guide.pdf`.

---

## 1. What you need before you start

| Thing | Where to get it | Notes |
|---|---|---|
| Python 3.12 or newer | [python.org](https://www.python.org/downloads/) | Tick "Add Python to PATH" during install |
| Git | [git-scm.com](https://git-scm.com/downloads) | Only needed to receive updates |
| The Firecrawl account | [firecrawl.dev](https://firecrawl.dev) | Reads gallery websites. Metered — see §6 |
| The Anthropic account | [console.anthropic.com](https://console.anthropic.com) | Judges artist profiles |

### If you have just taken this project over

The **Firecrawl account transfers with the project** by changing the account
email. Its API key does not change when the email does, so once the transfer is
done nothing in the project needs editing — the existing `.env` keeps working.

Order matters. The outgoing owner should **detach or replace the saved payment
card first**, because billing transfers with the account and they may not be able
to get back in afterwards to remove it. Then change the email, verify it, set a
new password, and add your own payment method.

The **Anthropic account is separate** and does not transfer.

Confirm the handover worked:

```bash
firecrawl --status
```

### Where the keys actually live

Worth understanding, because it decides what is safe to send.

| Location | Contains | Travels with the folder? |
|---|---|---|
| `.env.example` | A blank template. **No real keys** | Yes — harmless |
| `.env` | Your live keys, once you create it | **No — git-ignored, and must not be shared** |
| Firecrawl CLI config | The CLI's own saved login, stored outside the project | No — you log in on your own machine |

Right now the project folder contains **only the template**, so nothing sensitive
is in it. The Firecrawl CLI holds its own login separately, which is why
transferring the *account* is what matters rather than copying any file.

Once you create your `.env`, that changes:

> **From that point, do not send the project folder by email.** Move it on a USB
> drive or through a private repository. An emailed credential is a leaked
> credential, even to the right person. If a key is ever exposed, revoke and
> reissue it in the account dashboard, then paste the new one into `.env`.

**Keys are never stored in the code.** That is deliberate: keys committed into
code is how companies leak credentials.

---

## 2. One-time setup

Open a terminal in the project folder and run these four commands in order.

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -e ".[dev]"
```

```bash
copy .env.example .env
```

On macOS or Linux, use `source .venv/bin/activate` and `cp` instead.

Now open `.env` in Notepad and paste your two keys next to `FIRECRAWL_API_KEY=`
and `ANTHROPIC_API_KEY=`. Save and close.

**Check it worked:**

```bash
prospect config
```

This prints the settings it loaded and where each value came from. If a key is
missing or a setting is malformed, it says so here — it lists *every* problem at
once rather than failing on the first one an hour into a run.

---

## 3. Setting your rules

Everything that decides *who counts as a lead* lives in two plain text files. You
edit them in Notepad; there is no code involved.

| File | What it controls |
|---|---|
| `config/icp.yaml` | The ideal artist: which countries, career stage, gender requirement |
| `config/runtime.yaml` | How the run behaves: how strict the email confidence bar is, how many pages to read |

Every setting has a comment above it explaining what it does. After any edit, run
`prospect config` again to confirm the file is still valid before starting a run.

---

## 4. Adding galleries

The input is `Galleries sheet.xlsx`. Add one row per organisation with its name,
website, and Instagram if you have it. Rows without a website are skipped and
reported — they cannot be read.

You never need to remove old rows. The machine remembers every artist it has
already processed, so a second run skips them and works only the new ground.

---

## 5. Running it

```bash
python run_pipeline.py --budget 300
```

That is the whole thing. `--budget` is the maximum number of web-reading credits
the run may spend on tracing artists; at the measured rate it buys roughly one
artist per 1.8 credits. The run refuses to start if the balance is lower than the
budget you asked for, so it can never quietly overspend.

Two more flags are worth knowing:

- `--dry-run` — print the eleven steps, mark the ones that cost money, and stop
  without spending anything. Good for a first look.
- `--budget 0` — re-build the output sheets from work already done, spending
  nothing. Useful after editing the rules.

**Re-running is safe and cheap.** Every artist and every site map is cached, so a
second run skips what is done and pays only for new ground. If a run is
interrupted, simply run it again.

### It will stop once, on purpose

Part-way through, the run halts and asks which of the discovered artists are
women. That is the one judgement the machine does not make: an artist wrongly
included is a real embarrassment in front of a real person, and an earlier
version without this check sent two male artists to the operator.

You will see the pending names and where to record your decision. If you are
working in Claude Code, say *"classify the pending artist names"* and it will do
the reading for you. Then run the same command again — it resumes from the stop
and re-pays for nothing.

### What you get

Two files land in the **`output/`** folder:

- **`completed_leads.csv`** — the deliverable, newest first. Name, biography,
  verified email, confidence score, and a link back to the exact page the email
  came from.
- **`enrichment_not_a_must.csv`** — everything else worth keeping, phone numbers
  included. These are *not* leads and are never counted as such.

A third file, `coverage_report.csv`, reports how thoroughly each gallery was read
— see §7.

> **Note:** `prospect run` is the future entry point for the rebuilt engine and
> does **not** work yet. It exits with "no pipeline stages are wired yet". Use
> `python run_pipeline.py` as above.

---

## 6. Watching the cost

Reading websites is metered, and it is the only real cost. Check your balance at
any time:

```bash
firecrawl --status
```

Rough measured figures, so you can budget:

| Action | Cost |
|---|---|
| Listing one gallery's pages | ~1 credit |
| Testing 3 artists from a gallery | ~5 credits |
| Fully researching one artist | ~1.7 credits average |
| **One completed lead, all-in** | **~9 credits** |

**The single most important habit:** test a few artists from a gallery before
committing to its whole roster. Most galleries publish only one shared address
and can never produce a personal email — testing three artists costs about five
credits and tells you whether the remaining fifty are worth anything at all.
Skipping this step is how a budget gets spent on galleries that cannot deliver.

---

## 7. Checking the machine's work

This is the part to run whenever you want to satisfy yourself that no artists are
being silently missed.

```bash
python spikes/roster_probe/coverage_audit.py
```

It costs nothing — it re-reads already-saved data — and produces
`out/coverage_report.csv`, one row per gallery, with:

| Column | What it tells you |
|---|---|
| `pages_seen` | How many pages were found on that gallery's site |
| `artist_pages_seen` | How many of those look like individual artist pages |
| `artists_discovered` | How many artists were actually identified |
| `artists_processed` | How many were then researched for an email |
| `paginated` | Whether the artist list runs over multiple pages |
| `hit_page_limit` | Whether we stopped because of a limit rather than the end |
| `verdict` | The plain-English judgement (below) |
| `trusted` | `yes` means the count needs no human check |

### The verdicts, and what to do about each

| Verdict | Meaning | Action |
|---|---|---|
| `OK` | Full listing read, artists found | Nothing |
| `REVIEW - listing is paginated` | The artist list continues over several pages; we may not have followed all of them | Open the gallery, count the artists, compare to `artists_discovered` |
| `REVIEW - artist pages found but no names read` | Artist pages exist but no names could be extracted — usually names loaded by JavaScript | Needs a browser-based read; report it |
| `INCOMPLETE - hit page limit` | We stopped at a service limit, not at the end of the site | Re-run that gallery alone with a higher limit |
| `CANNOT VERIFY - no pages returned` | The site gave us nothing. **This is not the same as "no artists"** | Check the site by hand |
| `CANNOT VERIFY - site unreachable` | The site could not be loaded at all | Check the URL is still live |
| `NO ARTISTS FOUND` | Pages were read and genuinely contain no artist listing | Usually correct for magazines and suppliers |

**The rule this enforces:** a gallery that cannot be fully processed is *reported*,
never quietly counted as empty. `CANNOT VERIFY` and `NO ARTISTS FOUND` are
deliberately different answers.

---

## 8. Checking the code still works

Four commands, all of which should pass before you trust a change. These are the
same checks that run automatically.

```bash
pytest
```

```bash
mypy
```

```bash
ruff check .
```

```bash
lint-imports
```

`pytest` runs 564 automated checks. If any fail, do not run a paid job — something
is broken and a run would waste credits.

---

## 9. When something goes wrong

| Symptom | Cause and fix |
|---|---|
| `prospect: command not found` | The environment is not active. Run `.venv\Scripts\activate` |
| `Configuration error` on startup | A key is missing from `.env`, or a YAML file has a typo. The message names the exact file and field |
| Run stops part-way | Usually the credit balance. Check `firecrawl --status`, top up, then `prospect run --run-id <same id>` to resume |
| Everything returns "no pages returned" | Firecrawl key is invalid or out of credit |
| A gallery gives 0 artists but has them | Expected for JavaScript-heavy sites. It will appear in the coverage report as `CANNOT VERIFY`, not as zero |

---

## 10. Known limits, stated plainly

These are real and worth knowing before you rely on the output.

- **Emails are not test-mailed.** Verification means the format is valid, the mail
  server genuinely exists, and the ownership evidence holds. It does not mean a
  message has been delivered. Expect some bounces.
- **JavaScript-only artist lists are not yet read.** 13 galleries currently return
  nothing for this reason. They are reported as `CANNOT VERIFY`, never as empty.
- **Pagination is detected but not yet followed automatically.** 29 galleries are
  flagged `REVIEW` for this. Their artist counts should be treated as a floor, not
  a total.
- **The female-only check is currently applied by a person, not the machine.**
  Ambiguous names are excluded rather than guessed, so the list is shorter than
  the data allows but does not contain men.
- **The machine never sends email.** It finds and verifies; a person sends.
