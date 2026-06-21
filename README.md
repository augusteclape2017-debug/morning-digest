# Morning Market Digest

Every weekday morning, a GitHub Action calls the Claude API (with web search)
to research overnight macro news and surface 5 ideas across stocks, ETFs,
funds, and options. The result is written to `docs/data.json`, and
`docs/index.html` is a phone-friendly page that displays it — bookmark that
page to your phone's home screen and it'll always show the latest digest.

## One-time setup (15-20 minutes)

### 1. Create the GitHub repository
1. Go to github.com → click the **+** in the top right → **New repository**
2. Name it `morning-digest` (or anything you like)
3. Set it to **Public** (required for the free GitHub Pages hosting used here — the
   digest is market commentary, not personal data, so public is fine. If you'd
   rather keep it private, see the note at the bottom.)
4. Click **Create repository**

### 2. Upload these files
On the new repo's page, click **Add file → Upload files**, and drag in this
entire folder structure, keeping the paths intact:
```
.github/workflows/digest.yml
generate_digest.py
docs/index.html
docs/data.json
```
Commit directly to the `main` branch.

### 3. Add your Anthropic API key as a secret
1. In the repo, go to **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Name: `ANTHROPIC_API_KEY`
4. Value: paste your key (starts with `sk-ant-...`)
5. Click **Add secret**

This keeps the key encrypted and out of your code — it's never visible in the
repo itself.

### 4. Turn on GitHub Pages
1. Go to **Settings → Pages**
2. Under "Build and deployment" → Source: **Deploy from a branch**
3. Branch: **main**, folder: **/docs** → **Save**
4. After a minute, GitHub will show you a URL like:
   `https://yourusername.github.io/morning-digest/`

### 5. Point the page at your data file
The page currently fetches `data.json` using a relative path, which already
works correctly once it's served from `/docs` on GitHub Pages — **no edit
needed** for the default setup. (If you ever move data.json elsewhere, edit
the `DATA_URL` constant near the top of the `<script>` block in `index.html`.)

### 6. Run it once manually to test
1. Go to the **Actions** tab in your repo
2. Click **Generate Morning Digest** in the left sidebar
3. Click **Run workflow → Run workflow**
4. Wait ~1-2 minutes, refresh the Actions tab until it shows a green check
5. Visit your GitHub Pages URL — you should see a real digest

If it fails (red X), click into the run to see the error log — most likely
cause is the API key secret name not matching exactly, or no credit on the
Anthropic Console account.

### 7. Add to your phone's home screen
1. Open your GitHub Pages URL in Safari (iPhone) or Chrome (Android)
2. iPhone: tap the **Share** icon → **Add to Home Screen**
   Android: tap the **⋮** menu → **Add to Home screen**
3. It'll appear as an app icon. Tapping it opens the latest digest full-screen.

## Schedule

The workflow runs **weekdays at 11:30 UTC** (= 6:30am Eastern during daylight
time, 7:30am during standard time). To change the time, edit the cron line in
`.github/workflows/digest.yml`:

```yaml
- cron: '30 11 * * 1-5'
```

Format is `minute hour day month weekday`, always in UTC. Use
[crontab.guru](https://crontab.guru) to build a different schedule.

Note: GitHub free-tier scheduled workflows can run a few minutes late during
busy periods — this is normal and not a bug.

## Cost

Each run does several web searches plus one Claude API call. Expect roughly
**$0.05–$0.15 per weekday**, so under $3/month. Check actual spend anytime at
console.anthropic.com → Settings → Usage.

## Keeping the repo private instead of public

GitHub Pages on a private repo requires a **paid GitHub plan** (Pro or above).
If you'd rather not pay for that and not go public, an alternative is to skip
Pages entirely and have the phone page read `data.json` via the GitHub API
with a personal access token — that's more setup. Public is simplest and
fine here since the content is just market news commentary, not anything
personal.

## Files

- `generate_digest.py` — calls the Claude API, parses the response, writes `docs/data.json`
- `.github/workflows/digest.yml` — the schedule + the steps that run the script and commit results
- `docs/index.html` — the phone-facing app
- `docs/data.json` — latest digest (overwritten by every run)
