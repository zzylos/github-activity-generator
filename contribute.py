#!/usr/bin/env python3
"""Generate a git repository full of backdated commits.

The commits show up on the GitHub contributions graph of the account that
owns the email address they are made with. If a link to an empty remote
repository is given, the result is pushed there.

All commits are written in one go with `git fast-import`, which takes
seconds instead of the minutes needed to run `git commit` thousands of
times.
"""
import argparse
import os
import random
import re
import shutil
import subprocess
import sys
import time as clock
from datetime import date, datetime, time, timedelta

if sys.version_info < (3, 8):
    sys.exit('This script needs Python 3.8 or newer. Check your version '
             'with "python --version", or try running it with "python3".')

BRANCH = 'main'
FILE_NAME = 'README.md'
# Git config key stored in every repository this script creates. It lets
# a later run recognise the folder as safe to add more commits to.
MARKER = 'activity-generator.generated'
MAX_COMMITS_PER_DAY = 20
EARLIEST_DATE = date(1970, 1, 2)
# Commits are placed between these hours of the local day (10 AM to 8 PM).
DAYTIME_HOURS = (10, 20)
SECONDS_PER_DAY = 24 * 60 * 60

SSH_HELP = ('https://docs.github.com/en/authentication/'
            'connecting-to-github-with-ssh')
HTTPS_HELP = ('https://docs.github.com/en/get-started/git-basics/'
              'caching-your-github-credentials-in-git')


class GitError(Exception):
    """A git command exited with an error."""

    def __init__(self, args, code):
        super().__init__("the command 'git %s' failed with exit code %d. "
                         "See the message from git above."
                         % (' '.join(args), code))


def main(argv=None):
    args = arguments(sys.argv[1:] if argv is None else argv)
    if shutil.which('git') is None:
        fail('Git is not installed, or it is not on your PATH. Install it '
             'from https://git-scm.com/downloads, then open a new terminal '
             'window and run the script again.')

    start, end = date_range(args, date.today())
    commits = plan_commits(start, end, args.frequency, args.min_commits,
                           args.max_commits, args.no_weekends)
    if not commits:
        fail('these settings produce no commits. Use a higher --frequency '
             'or a longer date range.')

    repository = args.repository
    if repository and os.path.isdir(repository):
        # A local path. Make it absolute so it still works from inside the
        # new repository folder.
        repository = os.path.abspath(repository)
    directory = directory_name(repository, datetime.now())

    reuse = check_existing_directory(directory, repository)
    name, email = author_identity(args, directory if reuse else None)
    if repository:
        check_remote(repository, directory if reuse else None)

    days = len({commit.date() for commit in commits})
    print('Making %d commits on %d days between %s and %s.'
          % (len(commits), days, start, end))
    print('Author: %s <%s>' % (name, email))
    print('  (This email must be added to your GitHub account, or be your '
          'GitHub "noreply"\n  email. Otherwise the commits will not show '
          'up on your graph.)')

    if not reuse:
        try:
            os.mkdir(directory)
        except OSError as error:
            fail('could not create the folder "%s": %s'
                 % (directory, error.strerror))
    try:
        if not reuse:
            run_git(['init', '--quiet'], directory)
        # This also marks repositories made by older versions of the script.
        run_git(['config', MARKER, 'true'], directory)
        if args.user_name:
            run_git(['config', 'user.name', args.user_name], directory)
        if args.user_email:
            run_git(['config', 'user.email', args.user_email], directory)

        started = clock.monotonic()
        write_commits(directory, commits, name, email)
        print('Created %d commits in %.1f seconds in the folder "%s".'
              % (len(commits), clock.monotonic() - started, directory))

        if repository:
            push(directory, repository)
    except GitError as error:
        fail(str(error))

    print('\nRepository generation ' + green('completed successfully') + '!')
    if repository:
        print('It can take a few minutes (rarely up to 24 hours) for GitHub '
              'to update your graph.')
    else:
        print('Nothing was pushed because --repository was not given.')


def arguments(argv):
    parser = argparse.ArgumentParser(
        description='Fill your GitHub contributions graph with commits.')
    parser.add_argument('-nw', '--no_weekends',
                        required=False, action='store_true', default=False,
                        help="""Do not commit on Saturdays and Sundays.""")
    parser.add_argument('-mc', '--max_commits', default=10,
                        type=number_between(1, MAX_COMMITS_PER_DAY),
                        help="""The maximum number of commits a day, from 1
                        to %d. On each day with commits, the script picks a
                        random number of commits between --min_commits and
                        this value. The default is 10."""
                        % MAX_COMMITS_PER_DAY)
    parser.add_argument('-mn', '--min_commits', default=1,
                        type=number_between(1, MAX_COMMITS_PER_DAY),
                        help="""The minimum number of commits on a day that
                        has commits, from 1 to %d. The default is 1."""
                        % MAX_COMMITS_PER_DAY)
    parser.add_argument('-fr', '--frequency', default=80,
                        type=number_between(0, 100),
                        help="""Percentage of days that get commits, from 0
                        to 100. For example, 60 means about 60%% of days get
                        commits. The default is 80.""")
    parser.add_argument('-r', '--repository', type=str, required=False,
                        help="""Link to an empty remote repository (no
                        README, license or .gitignore). If given, the script
                        pushes the commits there. SSH and HTTPS links both
                        work, for example git@github.com:user/repo.git or
                        https://github.com/user/repo.git""")
    parser.add_argument('-un', '--user_name', type=str, required=False,
                        help="""Name to make the commits with. If not given,
                        your git config user.name is used.""")
    parser.add_argument('-ue', '--user_email', type=str, required=False,
                        help="""Email to make the commits with. It must be
                        added to your GitHub account. If not given, your git
                        config user.email is used.""")
    start_group = parser.add_mutually_exclusive_group()
    start_group.add_argument('-db', '--days_before', type=int, default=365,
                             help="""How many days before today the commits
                             start. The default is 365.""")
    start_group.add_argument('-sd', '--start_date', type=parse_date,
                             help="""The first date to commit on, as
                             YYYY-MM-DD. Use instead of --days_before.""")
    end_group = parser.add_mutually_exclusive_group()
    end_group.add_argument('-da', '--days_after', type=int, default=0,
                           help="""How many days after today the commits
                           end. Use a negative number to stop before today:
                           -5 means the last commit is 5 days ago. The
                           default is 0 (the last commit is today).""")
    end_group.add_argument('-ed', '--end_date', type=parse_date,
                           help="""The last date to commit on, as
                           YYYY-MM-DD. Use instead of --days_after.""")
    args = parser.parse_args(argv)
    if args.min_commits > args.max_commits:
        parser.error('--min_commits (%d) must not be bigger than '
                     '--max_commits (%d)'
                     % (args.min_commits, args.max_commits))
    return args


def number_between(low, high):
    """Return an argparse type for whole numbers from low to high."""
    def parse(value):
        try:
            number = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(
                "'%s' is not a whole number" % value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(
                'must be from %d to %d, but got %d' % (low, high, number))
        return number
    return parse


def parse_date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            "'%s' is not a valid date. Use YYYY-MM-DD, for example "
            "2024-01-31" % value)


def date_range(args, today):
    """Return the first and last day to commit on (both included)."""
    try:
        start = args.start_date or today - timedelta(days=args.days_before)
        end = args.end_date or today + timedelta(days=args.days_after)
    except OverflowError:
        fail('the date range is too large.')
    if start > end:
        fail('the start date (%s) is after the end date (%s).'
             % (start, end))
    if start < EARLIEST_DATE:
        fail('the start date (%s) must be %s or later.'
             % (start, EARLIEST_DATE))
    return start, end


def plan_commits(start, end, frequency, min_commits, max_commits,
                 no_weekends, rng=random):
    """Return the times of all commits to make, oldest first."""
    commits = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        if no_weekends and day.weekday() >= 5:
            continue
        if rng.random() * 100 < frequency:
            count = rng.randint(min_commits, max_commits)
            commits.extend(commit_times(day, count, rng))
    return commits


def commit_times(day, count, rng=random):
    """Return `count` different times on `day`, as local aware datetimes.

    GitHub puts a commit on the graph by its date in UTC, not in your time
    zone. A commit at 8 PM in New York is 1 AM the next day in UTC, so it
    would land on the wrong day (and a Friday commit would land on a
    Saturday). The times picked here are on the same date both locally and
    in UTC, and during the day when possible.
    """
    midnight = datetime.combine(day, time())
    noon = (midnight + timedelta(hours=12)).astimezone()
    utc_offset = int(noon.utcoffset().total_seconds())
    # Local times (in seconds after midnight) that are on `day` in UTC too.
    low = max(0, utc_offset)
    high = min(SECONDS_PER_DAY, SECONDS_PER_DAY + utc_offset)
    day_low = max(low, DAYTIME_HOURS[0] * 3600)
    day_high = min(high, DAYTIME_HOURS[1] * 3600)
    if day_high > day_low:
        low, high = day_low, day_high
    seconds = sorted(rng.sample(range(low, high), count))
    return [(midnight + timedelta(seconds=s)).astimezone() for s in seconds]


def directory_name(repository, now):
    name = repo_name(repository) if repository else ''
    return name or 'repository-' + now.strftime('%Y-%m-%d-%H-%M-%S')


def repo_name(url):
    """Return the repository name from a git link or path, or ''."""
    name = re.split(r'[/\\:]', url.strip().rstrip('/\\'))[-1]
    if name.lower().endswith('.git'):
        name = name[:-4]
    name = re.sub(r'[^A-Za-z0-9._-]', '-', name)
    return name if name.strip('.') else ''


def check_existing_directory(directory, repository):
    """Return True if `directory` is a repository from an earlier run.

    Stops the script if the folder exists but cannot safely be reused.
    """
    if not os.path.exists(directory):
        return False
    if not is_generated_repository(directory):
        fail('the folder "%s" already exists and was not created by this '
             'script. Rename or delete it, or run the script from another '
             'folder.' % directory)
    if git_output(['status', '--porcelain'], directory):
        fail('the repository in "%s" has uncommitted changes. Commit or '
             'undo them, then run the script again.' % directory)
    if repository:
        origin = git_output(['config', '--get', 'remote.origin.url'],
                            directory, check=False)
        if not origin:
            run_git(['remote', 'add', 'origin', repository], directory)
        elif origin != repository:
            fail('the repository in "%s" was made for %s, not %s. Rename '
                 'or delete the folder to start over, or change its link '
                 'with:\n  git -C %s remote set-url origin %s'
                 % (directory, origin, repository, directory, repository))
    print('Found the repository "%s" from an earlier run. New commits will '
          'be added to it.' % directory)
    return True


def is_generated_repository(directory):
    if not os.path.isdir(os.path.join(directory, '.git')):
        return False
    if git_output(['config', '--get', MARKER], directory,
                  check=False) == 'true':
        return True
    # Older versions of the script did not set the marker, but their
    # README.md always starts with a "Contribution: " line.
    try:
        with open(os.path.join(directory, FILE_NAME),
                  encoding='utf-8') as file:
            return file.readline().startswith('Contribution: ')
    except (OSError, UnicodeDecodeError):
        return False


def author_identity(args, directory):
    """Return the (name, email) the commits are made with."""
    name, email = args.user_name, args.user_email
    if not name or not email:
        # `git var` uses the same rules as `git commit` to find these.
        ident = git_output(['var', 'GIT_AUTHOR_IDENT'], directory,
                           check=False, quiet=True)
        match = re.match(r'(.*) <(.*)> \d+ [+-]\d{4}$', ident or '')
        if match:
            name = name or match.group(1)
            email = email or match.group(2)
    if not name or not email:
        fail('git does not know your name and email yet. Set them once '
             'with:\n'
             '  git config --global user.name "Your Name"\n'
             '  git config --global user.email "you@example.com"\n'
             'or pass --user_name and --user_email to the script. Use an '
             'email that is added to your GitHub account.')
    if any(char in value for value in (name, email) for char in '<>\n'):
        fail('the name and email must not contain "<", ">" or line breaks.')
    if '@' not in email:
        fail('"%s" is not an email address.' % email)
    return name, email


def check_remote(repository, directory):
    """Make sure the remote repository can be reached and pushed to.

    This runs before any commits are made, so that a wrong link or missing
    login is found right away instead of after generating everything.
    """
    print('Checking access to %s ...' % repository)
    result = subprocess.run(['git', 'ls-remote', repository],
                            stdout=subprocess.PIPE,
                            encoding='utf-8', errors='replace')
    if result.returncode != 0:
        fail('could not connect to the remote repository.\n'
             + remote_help(repository))
    refs = {}
    for line in result.stdout.splitlines():
        sha, _, ref = line.partition('\t')
        if ref:
            refs[ref] = sha

    not_empty = ('the remote repository already has commits. Create a new, '
                 'empty repository on GitHub (do not add a README, license '
                 'or .gitignore) and use its link.')
    local_head = None
    if directory:
        local_head = git_output(
            ['rev-parse', '--verify', '--quiet', 'refs/heads/' + BRANCH],
            directory, check=False)
    remote_head = refs.get('refs/heads/' + BRANCH)

    if not local_head:
        # Nothing to continue from, so the remote must be empty.
        if refs:
            fail(not_empty)
        return
    if remote_head == local_head:
        return  # Everything from the earlier run was pushed.
    if remote_head is None and refs:
        fail(not_empty)
    if remote_head is None or is_ancestor(remote_head, directory):
        fail('commits from your previous run in "%s" were never pushed. '
             'To push them without adding more, run:\n'
             '  git -C %s push -u origin %s\n'
             'To start over instead, delete the "%s" folder.'
             % (directory, directory, BRANCH, directory))
    fail('the remote repository has commits that the folder "%s" does not '
         'have. Use a new, empty repository instead.' % directory)


def is_ancestor(commit, directory):
    result = subprocess.run(
        ['git', 'merge-base', '--is-ancestor', commit, 'HEAD'],
        cwd=directory, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def remote_help(repository):
    lines = []
    if repository.startswith(('git@', 'ssh://')):
        lines.append(
            'This is an SSH link. It only works if you have an SSH key that '
            'is added to your GitHub account. See ' + SSH_HELP + '\n'
            'Or use the HTTPS link instead, for example '
            'https://github.com/USER/REPO.git')
    elif repository.startswith(('https://', 'http://')):
        lines.append(
            'GitHub does not accept your account password here. Sign in '
            'with GitHub CLI ("gh auth login") or Git Credential Manager '
            '(included with Git for Windows). See ' + HTTPS_HELP)
    lines.append('Also check that the repository exists, that the link is '
                 'spelled correctly, and that your account can push to it.')
    return '\n'.join(lines)


def write_commits(directory, commits, name, email):
    """Add all commits to the `main` branch with one `git fast-import`."""
    parent = None
    if git_output(['rev-parse', '--verify', '--quiet',
                   'refs/heads/' + BRANCH], directory, check=False):
        # Continue from the existing branch. The "^0" is required by
        # fast-import to start a branch from its own current value.
        parent = 'refs/heads/%s^0' % BRANCH
    command = ['fast-import', '--quiet']
    process = subprocess.Popen(['git'] + command, cwd=directory,
                               stdin=subprocess.PIPE)
    try:
        for when in commits:
            process.stdin.write(fast_import_commit(when, name, email, parent))
            parent = None
        process.stdin.close()
    except BrokenPipeError:
        pass  # fast-import stopped early; its exit code is checked below.
    code = process.wait()
    if code != 0:
        raise GitError(command, code)
    # Point HEAD at the branch and update the files in the folder.
    run_git(['symbolic-ref', 'HEAD', 'refs/heads/' + BRANCH], directory)
    run_git(['reset', '--quiet', '--hard'], directory)


def fast_import_commit(when, name, email, parent=None):
    """Return one commit in the `git fast-import` stream format."""
    stamp = '%d %s' % (when.timestamp(), when.strftime('%z'))
    who = '%s <%s> %s' % (name, email, stamp)
    message = message_for(when).encode('utf-8')
    content = when.strftime('Contribution: %Y-%m-%d %H:%M:%S\n')
    content = content.encode('utf-8')
    lines = [
        ('commit refs/heads/' + BRANCH).encode('utf-8'),
        ('author ' + who).encode('utf-8'),
        ('committer ' + who).encode('utf-8'),
        b'data %d' % len(message), message,
    ]
    if parent:
        lines.append(('from ' + parent).encode('utf-8'))
    lines += [
        ('M 100644 inline ' + FILE_NAME).encode('utf-8'),
        b'data %d' % len(content), content,
    ]
    return b'\n'.join(lines) + b'\n'


def message_for(when):
    return when.strftime('Contribution: %Y-%m-%d %H:%M')


def push(directory, repository):
    if not git_output(['config', '--get', 'remote.origin.url'], directory,
                      check=False):
        run_git(['remote', 'add', 'origin', repository], directory)
    print('\nPushing to %s ...' % repository)
    result = run_git(['push', '--set-upstream', 'origin', BRANCH], directory,
                     check=False)
    if result.returncode != 0:
        fail('the commits were made, but pushing them failed.\n'
             + remote_help(repository) + '\n'
             'After fixing the problem, push the commits with:\n'
             '  git -C %s push -u origin %s' % (directory, BRANCH))


def run_git(args, directory=None, check=True):
    result = subprocess.run(['git'] + args, cwd=directory)
    if check and result.returncode != 0:
        raise GitError(args, result.returncode)
    return result


def git_output(args, directory=None, check=True, quiet=False):
    """Run git and return what it printed, without the trailing newline."""
    result = subprocess.run(['git'] + args, cwd=directory,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL if quiet else None,
                            encoding='utf-8', errors='replace')
    if check and result.returncode != 0:
        raise GitError(args, result.returncode)
    return result.stdout.strip()


def green(text):
    if sys.stdout.isatty() and os.name != 'nt' \
            and 'NO_COLOR' not in os.environ:
        return '\x1b[6;30;42m' + text + '\x1b[0m'
    return text


def fail(message):
    sys.exit('Error: ' + message)


if __name__ == '__main__':
    main()
