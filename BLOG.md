*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 3: Slow and Steady](https://dev.to/challenges/hacktoberfest-week3-2026-10-19)*

## What I Built

**Sloth** is a local file tidier that runs entirely on your laptop.

You point it at a folder — usually the download folder you have been avoiding for months — and it reads the files, groups them into piles, renames them into something you can actually search for, and shows you the whole plan before a single byte moves. When you approve it, everything goes into `Sloth Sorted/`, and Sloth leaves a short morning note describing what happened.

The person who gets to be lazier is anyone who has ever opened their Downloads folder, felt a small wave of dread, and closed it again. That is the entire audience. Sloth does the reading and the sorting; you keep the judgement call.

The model is **Qwen2.5-1.5B-Instruct** — open weights, Apache-2.0 — running locally through **llama.cpp**. No account, no API key, no cloud, no telemetry. The app itself is Python standard library only. The only thing it asks of the network is one setup step to download the engine and the weights.

## Demo

There is no hosted demo, on purpose: the whole point is that your files never leave your machine. Here is what it looks like running locally.

![Sloth dashboard](https://raw.githubusercontent.com/kondekarshubham123/sloth/main/docs/ui-hero.png)

A scan of a 42-file messy folder (about 26 seconds on an M-series Mac):

![Sloth plan](https://raw.githubusercontent.com/kondekarshubham123/sloth/main/docs/ui-plan.png)

Every row shows the new name, the original name, the model's reason, and a confidence score. The two files it is unsure about start unticked. Nothing moves until you press the button.

After applying, a receipt and a morning note:

![Sloth receipt](https://raw.githubusercontent.com/kondekarshubham123/sloth/main/docs/ui-receipt.png)

To reproduce locally:

```bash
git clone https://github.com/kondekarshubham123/sloth.git
cd sloth
./setup.sh          # builds llama.cpp, fetches ~1 GB of weights, makes a demo folder
./sloth ui --open   # http://127.0.0.1:8765
```

Or stay in the terminal:

```bash
./sloth scan ~/Downloads
./sloth apply last --yes
./sloth undo
./sloth night --once --apply   # tidy now, then leave a note
```

## Code

The repository is here: **[kondekarshubham123/sloth](https://github.com/kondekarshubham123/sloth)**

```bash
git clone https://github.com/kondekarshubham123/sloth.git
```

The interesting parts are small and readable:

- `src/sloth/scanner.py` — a careful folder walk that skips junk, symlinks, and its own output, and reads a bounded snippet from text-like files.
- `src/sloth/planner.py` — batching, rule hints, model reconciliation, and filename sanitising.
- `src/sloth/llm.py` — spawns and supervises a local `llama-server`; talks to it over loopback.
- `src/sloth/store.py` — plans, apply, a JSONL journal, undo, and the morning note.
- `src/sloth/netguard.py` — a socket-level guard that refuses non-loopback connections.
- `src/sloth/ui/` — the dashboard in plain HTML, CSS, and JavaScript, with inline SVG illustrations and no external assets.

Twelve unit tests cover the boring-but-important bits: name sanitising, extracting JSON from a chatty model, scan skip rules, path escapes, idempotent apply, undo, and the airgap.

## How I Built It

I wanted the model to be genuinely load-bearing, not a chat bubble bolted onto a file sorter. But I also knew a 1.5B model would occasionally be confidently wrong. So Sloth is a hybrid, and the split is deliberate.

**The model decides.** For each batch of six files, the planner sends a compact JSON view — name, extension, size, modification date, a short text snippet, and a rule hint — to a local `llama-server`. It asks for strict JSON back: bucket, a kebab-case name, a reason under twelve words, and a confidence score.

**The rules keep it honest.** A small deterministic engine supplies an objective hint for every file. If the model agrees with a hard signal, confidence gets a small bump. If it disagrees about something objective — an `.mp3` is not a document, a file named `screenshot-2026-03-14` is a screenshot, a boarding pass is travel — the rule wins, and the override is visible in the `why` line. Semantic corrections are more conservative and only apply when the model itself is unsure.

While testing, the model kept stamping today's date onto filenames that had no date in them. That is a very small, very believable hallucination, and exactly the kind of thing a person would not notice until next year. So `drop_bogus_date()` strips a `YYYY-MM-DD` prefix unless those digits appear in the original name or the file's actual modified date. Small guardrail, big difference in trust.

The prompt treats filenames and snippets as untrusted data, never instructions, because a file called `ignore-previous-instructions.txt` should be a file, not a command.

Everything else is intentionally boring. The HTTP server is `http.server`. The UI streams scan progress as newline-delimited JSON. The journal is JSONL. Undo reads the journal backwards and refuses any move that would escape the scan root. The morning note is Markdown written to `~/.sloth/briefings/`.

And the airgap is real rather than decorative: `netguard.install()` replaces the socket connection path so non-loopback connections fail for the life of the process, the UI binds to `127.0.0.1`, and `llama-server` is launched with a loopback host. `./sloth doctor` prints the model checksum, the engine backend, and the airgap state. The dashboard loads no CDN, no web fonts, and no analytics. The sloth drawing is inline SVG.

The slow part is the point. Batches of six, a visible "reading files 13–18 of 42" line, and a plan you have to approve. It is a file tidier that behaves like a careful person rather than a progress bar.

## Why Does Open Innovation Matter?

A closed API would have made this project easier and worse.

The easy version sends your filenames, and possibly snippets of your contracts and medical notes, to someone else's server. That is a strange price to pay for tidying a Downloads folder. With open weights and open inference, the private version is also the capable version. Qwen2.5-1.5B is small enough to run on a laptop, good enough to name a file sensibly, and licensed so that I can ship it without asking permission.

Open weights also made the *design* possible. I could inspect how the model behaved, notice the invented-date pattern, and build a guardrail around it. I could swap in a larger model by changing one environment variable. I could build the entire thing offline, on a train, without a billing dashboard. And anyone reading the repo can verify the privacy claim in the code instead of trusting a landing page.

The agent harness matters here too. llama.cpp is open, hackable, and runs on the hardware people already own. That is what turns "local AI" from a demo into something a normal person can actually use on a Tuesday night.

## My Agent Session

I did not publish a DevRelay session for this build, so there is no embed to share. Being honest about that feels better than linking to something that does not exist.

What I can share is the loop I actually worked in. I used an AI coding agent to scaffold the project, then spent most of the time on the unglamorous parts: making the model's JSON parse reliably, reducing the batch size until the 1.5B model stopped truncating output, catching the bogus date prefixes, fixing the apply button's disabled state, and re-running the same 42-file demo until apply and undo were both correct. The screenshots in this post are from the final build, not a mockup.

The most useful agent contribution was not code generation. It was being able to run the app, read the model's output, and iterate on the prompt and the reconciliation rules in the same session.

## The Lazy Payoff

On the demo folder, Sloth read and classified **42 files into 12 piles in about 26 seconds**. I approved 40 of them; the two low-confidence files stayed put. Apply moved all 40 into `Sloth Sorted/` in under a second. Undo put all 40 back, from the journal, just as quickly.

The honest number is not the 26 seconds. It is the twenty minutes I would have spent opening files called `scan0001.pdf` and `q3 budget final FINAL v3.xlsx` to work out what they were, plus the future minutes I will not spend searching for them. The folder is now something I can look at without flinching, and I did not have to make a single decision about a `.HEIC` file.

That is the laziness Sloth is selling: not zero effort, just the effort moved to a place where it is cheap. The sloth reads slowly so you do not have to.
