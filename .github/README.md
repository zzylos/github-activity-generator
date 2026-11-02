GitHub Activity Generator [![build](https://github.com/zzylos/github-activity-generator/actions/workflows/build.yml/badge.svg)](https://github.com/zzylos/github-activity-generator/actions/workflows/build.yml)
=========================

A script that fills in your GitHub contributions graph for the last year (or
any dates you pick) in a few seconds.

This is a fork of [Shpota/github-activity-generator](https://github.com/Shpota/github-activity-generator)
with fixes for many of the problems reported there. See [What changed in this fork](#what-changed-in-this-fork).

## ⚠ Disclaimer

This script is for educational purposes and for showing how GitHub counts
contributions. It should not be used to misrepresent your professional
contributions or coding activity.

## What it looks like

### Before :neutral_face: :no_mouth: :unamused:
![Before](before.png)
### After :muscle: :relieved: :heart: :sunglasses: :metal: :horse: :wink: :fire: :dancer: :santa: :fireworks: :cherries: :tada:
![After](after.png)

## What you need

- **Python 3.8 or newer.** Check with `python --version` (or `python3 --version`
  on macOS and Linux).
- **Git.** Check with `git --version`. If it is missing, install it from
  [git-scm.com](https://git-scm.com/downloads).
- **Git must be able to push to your GitHub account**, either with an
  [SSH key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh)
  or by signing in over HTTPS with
  [GitHub CLI or Git Credential Manager](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git).
  The script checks this before it does anything else and tells you if it
  does not work.

## How to use

1. **Create a new, empty repository on GitHub.** On the "Create a new
   repository" page, do **not** add a README, .gitignore or license. Those
   would add a commit, and the script only pushes to empty repositories.
2. **Copy the repository link.** On the new repository's page, click "SSH" or
   "HTTPS" and copy the link:
   - SSH looks like `git@github.com:USER/REPO.git`. Use it if you have an SSH
     key set up.
   - HTTPS looks like `https://github.com/USER/REPO.git`. Use it if you sign
     in with GitHub CLI or Git Credential Manager (included with Git for
     Windows).
3. **Download [contribute.py](https://raw.githubusercontent.com/zzylos/github-activity-generator/main/contribute.py)**
   (right-click the link and choose "Save link as"), or download the
   [whole project as a zip](https://github.com/zzylos/github-activity-generator/archive/refs/heads/main.zip).
4. **Open a terminal in the folder where `contribute.py` is** and run it with
   your link:
   ```sh
   python contribute.py --repository=git@github.com:USER/REPO.git
   ```
   On macOS and Linux, use `python3` instead of `python`. On Windows, `py`
   also works.
5. **Wait for GitHub to update.** It usually takes a few minutes, but
   [GitHub says it can take up to 24 hours](https://docs.github.com/en/account-and-profile/how-tos/contribution-settings/troubleshooting-missing-contributions).

The script prints the name and email the commits are made with. **The email
must be added to your GitHub account** (Settings → Emails), or be your GitHub
"noreply" email. Otherwise the commits will not show up on your graph. See
[Troubleshooting](#troubleshooting) if nothing shows up.

## How it works

1. The script checks that it can reach your repository, so a wrong link or a
   login problem is caught before anything is created.
2. It creates a new git repository in a folder named after your repository
   (or `repository-<date>-<time>` if you do not give a link).
3. It picks which days get commits and how many, and makes all the commits in
   one go with `git fast-import`. Each commit changes `README.md`. This takes
   about a second, even for thousands of commits.
4. It pushes the commits to your repository.

Commit times are random, between 10 AM and 8 PM your local time. GitHub puts
commits on the graph by their date in
[UTC](https://docs.github.com/en/account-and-profile/concepts/contributions-on-your-profile),
not your local date, so the script only picks times that are on the same date
in both. Otherwise, a commit made at 8 PM in New York would show up on the
next day.

## Options

| Option | Short | Default | What it does |
| --- | --- | --- | --- |
| `--repository=LINK` | `-r` | none | Link to an empty GitHub repository to push to. Without it, nothing is pushed. |
| `--max_commits=N` | `-mc` | 10 | Most commits on one day (1 to 20). |
| `--min_commits=N` | `-mn` | 1 | Fewest commits on a day that has commits (1 to 20). |
| `--frequency=N` | `-fr` | 80 | Percentage of days that get commits (0 to 100). |
| `--no_weekends` | `-nw` | off | Skip Saturdays and Sundays. |
| `--days_before=N` | `-db` | 365 | Start this many days before today. |
| `--days_after=N` | `-da` | 0 | End this many days after today. Negative numbers end before today. |
| `--start_date=YYYY-MM-DD` | `-sd` | none | First day with commits. Use instead of `--days_before`. |
| `--end_date=YYYY-MM-DD` | `-ed` | none | Last day with commits. Use instead of `--days_after`. |
| `--user_name=NAME` | `-un` | git config | Name to make the commits with. |
| `--user_email=EMAIL` | `-ue` | git config | Email to make the commits with. |

The first and last days are both included. For example, the default range is
the last 365 days plus today.

Run `python contribute.py --help` to see all options.

### Examples

Make 1 to 12 commits a day on about 60% of days:
```sh
python contribute.py --max_commits=12 --frequency=60 --repository=git@github.com:USER/REPO.git
```

Make 3 to 8 commits a day, and skip weekends:
```sh
python contribute.py --min_commits=3 --max_commits=8 --no_weekends --repository=git@github.com:USER/REPO.git
```

Fill a specific period, from April 1 to October 1, 2024:
```sh
python contribute.py --start_date=2024-04-01 --end_date=2024-10-01 --repository=git@github.com:USER/REPO.git
```

Start 30 days ago and stop 5 days ago:
```sh
python contribute.py --days_before=30 --days_after=-5 --repository=git@github.com:USER/REPO.git
```

Create the commits on your computer only, without pushing:
```sh
python contribute.py --no_weekends
```
The commits end up in a `repository-<date>-<time>` folder. To push them
later, create an empty GitHub repository and run these commands inside that
folder:
```sh
git remote add origin git@github.com:USER/REPO.git
```
```sh
git push -u origin main
```

## Running it again

Run the script again **from the same folder, with the same `--repository`
link**, and it adds more commits on top of the ones from the last run and
pushes them. It never deletes or rewrites commits.

To keep your files safe, the script only reuses a folder that it created
itself. It stops with a message instead if:

- the folder exists but was not made by this script,
- the folder has changes that are not committed,
- the folder was made for a different repository link, or
- the commits from the last run were never pushed. The message shows the
  command to push them.

## Troubleshooting

#### "could not connect to the remote repository" or "Permission denied (publickey)"
Git could not log in to GitHub, or could not find the repository.
- With an SSH link (`git@github.com:...`), you need an SSH key that is added
  to your GitHub account. Follow
  [GitHub's SSH guide](https://docs.github.com/en/authentication/connecting-to-github-with-ssh),
  or use the HTTPS link instead.
- With an HTTPS link, GitHub does not accept your account password. Sign in
  with GitHub CLI (`gh auth login`) or Git Credential Manager. See
  [Caching your GitHub credentials in Git](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git).
- Check that the repository exists and that the link is spelled correctly.

#### "the remote repository already has commits"
The repository is not empty. This happens if you added a README, license or
.gitignore when creating it, or if you used it before. Create a new, empty
repository and use its link.

#### "the folder ... already exists and was not created by this script"
There is already a folder with the same name as your repository where you are
running the script. Rename or delete it, or run the script from another
folder.

#### The commits are in the repository, but my graph did not change
GitHub only counts commits that meet
[all of these rules](https://docs.github.com/en/account-and-profile/how-tos/contribution-settings/troubleshooting-missing-contributions):
- **The commit email is added to your GitHub account.** The script prints the
  email it uses. Compare it with the list in GitHub's Settings → Emails. To
  change the email, run the line below and then run the script again with a
  new, empty repository:
  ```sh
  git config --global user.email "you@example.com"
  ```
  You can also pass `--user_email=you@example.com` to the script.
- **The commits are on the default branch.** The script pushes to `main`,
  which becomes the default branch of an empty repository.
- **The repository is not a fork.**

Also, wait a while. It can take up to 24 hours.

#### Only I can see the new activity, other people cannot
Your repository is probably private. By default, other people only see
contributions to public repositories. Either make the repository public, or
go to your profile page, click **Contribution settings** above the graph, and
turn on **Private contributions**. See
[GitHub's guide](https://docs.github.com/en/account-and-profile/how-tos/contribution-settings/manage-visibility-settings-for-private-contributions-and-achievements).

#### "Git is not installed, or it is not on your PATH"
Install Git from [git-scm.com](https://git-scm.com/downloads). Then close
your terminal, open a new one, and run the script again.

## Running the tests

The tests need only Python and Git:
```sh
python -m unittest -v test_contribute
```

## What changed in this fork

- **Much faster:** all commits are written with one `git fast-import` call.
  A default run takes about a second instead of a few minutes.
- **Commits land on the right day:** commit times are on the same date in UTC
  and in your time zone. Before, commits made west of UTC (for example in
  the Americas) showed up one day late, and `--no_weekends` put commits on
  Saturdays.
- **Running again works:** a second run adds more commits instead of
  crashing with "directory already exists".
- **Login problems are found early:** the script checks access to the
  repository before creating anything, and explains how to fix SSH and HTTPS
  login errors.
- **Errors are not hidden:** if a git command fails, the script stops and
  says what went wrong, instead of printing "completed successfully".
- **Fixed** an empty folder name (and a crash) when the link does not end in
  `.git`.
- **Fixed** the commit messages, which had extra quote marks in them.
- **Fixed** `--frequency=100`, which skipped about 1 in 100 days.
- **Works with older Git versions** that do not support `git init -b`.
- **New options:** `--min_commits`, `--start_date`, `--end_date`, and
  negative `--days_after`.
- **Checks option values** and shows a clear message for invalid ones,
  instead of silently changing them.
- Both the author and the committer date are set to the commit time (before,
  only the author date was).
- New tests that run in temporary folders, and CI on Linux, Windows and macOS.

## License

This project is licensed under the [Apache License 2.0](../LICENSE). It is
based on [github-activity-generator](https://github.com/Shpota/github-activity-generator)
by [Sasha Shpota](https://github.com/Shpota). This fork changes the original
code as described above.
