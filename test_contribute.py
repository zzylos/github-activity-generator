import io
import os
import random
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import contribute

NAME = 'Test User'
EMAIL = 'test@example.com'
IDENTITY = ['--user_name=' + NAME, '--user_email=' + EMAIL]
# A short range where every day gets commits, so no run ends up empty.
FEW_DAYS = ['--days_before=3', '--frequency=100']


def git(*args, cwd=None):
    """Run git (with a fixed identity) and return its output."""
    command = ['git', '-c', 'user.name=' + NAME, '-c', 'user.email=' + EMAIL]
    return subprocess.run(command + list(args), cwd=cwd, check=True,
                          stdout=subprocess.PIPE,
                          encoding='utf-8').stdout.strip()


def remove_tree(path):
    # Git makes its object files read-only, which Windows refuses to delete.
    def make_writable_and_retry(function, target, _):
        os.chmod(target, stat.S_IWRITE)
        function(target)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=make_writable_and_retry)
    else:
        shutil.rmtree(path, onerror=make_writable_and_retry)


class ArgumentTests(unittest.TestCase):

    def assert_rejected(self, argv):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            contribute.arguments(argv)

    def test_defaults(self):
        args = contribute.arguments([])
        self.assertFalse(args.no_weekends)
        self.assertEqual(args.max_commits, 10)
        self.assertEqual(args.min_commits, 1)
        self.assertEqual(args.frequency, 80)
        self.assertEqual(args.days_before, 365)
        self.assertEqual(args.days_after, 0)
        self.assertIsNone(args.repository)

    def test_short_options(self):
        args = contribute.arguments(['-nw', '-mc=12', '-mn=3', '-fr=60',
                                     '-db=10', '-da=-2'])
        self.assertTrue(args.no_weekends)
        self.assertEqual((args.max_commits, args.min_commits), (12, 3))
        self.assertEqual(args.frequency, 60)
        self.assertEqual((args.days_before, args.days_after), (10, -2))

    def test_rejects_invalid_values(self):
        for argv in (['-mc=0'], ['-mc=21'], ['-mc=abc'], ['-mn=0'],
                     ['-fr=101'], ['-fr=-1'], ['-mn=5', '-mc=3'],
                     ['--start_date=2024-13-01'], ['--end_date=yesterday']):
            with self.subTest(argv=argv):
                self.assert_rejected(argv)

    def test_rejects_days_and_dates_together(self):
        self.assert_rejected(['-db=5', '--start_date=2024-01-01'])
        self.assert_rejected(['-da=5', '--end_date=2024-01-01'])

    def test_default_range_is_last_year_up_to_today(self):
        today = date(2024, 6, 15)
        args = contribute.arguments([])
        self.assertEqual(contribute.date_range(args, today),
                         (date(2023, 6, 16), today))

    def test_negative_days_after_stops_before_today(self):
        today = date(2024, 6, 15)
        args = contribute.arguments(['-db=30', '-da=-5'])
        self.assertEqual(contribute.date_range(args, today),
                         (date(2024, 5, 16), date(2024, 6, 10)))

    def test_start_and_end_dates(self):
        args = contribute.arguments(['--start_date=2015-04-01',
                                     '--end_date=2015-10-01'])
        self.assertEqual(contribute.date_range(args, date(2024, 1, 1)),
                         (date(2015, 4, 1), date(2015, 10, 1)))

    def test_start_date_with_days_after(self):
        args = contribute.arguments(['--start_date=2024-01-01', '-da=3'])
        self.assertEqual(contribute.date_range(args, date(2024, 1, 10)),
                         (date(2024, 1, 1), date(2024, 1, 13)))

    def test_rejects_bad_ranges(self):
        for argv in (['-db=5', '-da=-6'],
                     ['--start_date=2024-02-01', '--end_date=2024-01-01'],
                     ['--start_date=1969-12-31'],
                     ['-db=999999999999']):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                contribute.date_range(contribute.arguments(argv),
                                      date(2024, 1, 1))


class RepoNameTests(unittest.TestCase):

    def test_repo_name(self):
        cases = {
            'git@github.com:user/repo.git': 'repo',
            'https://github.com/user/repo.git': 'repo',
            # A link without ".git" used to give an empty folder name.
            'https://github.com/user/repo': 'repo',
            'https://github.com/user/repo/': 'repo',
            'https://github.com/user/my.repo.git': 'my.repo',
            'ssh://git@github.com/user/Repo-1.GIT': 'Repo-1',
            'C:\\Users\\me\\remote.git': 'remote',
            '/tmp/remote.git': 'remote',
            ' git@github.com:user/repo.git ': 'repo',
            'https://example.com/a b?.git': 'a-b-',
            '': '',
            '.git': '',
            '..': '',
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(contribute.repo_name(url), expected)

    def test_directory_name_falls_back_to_timestamp(self):
        now = datetime(2024, 1, 2, 3, 4, 5)
        self.assertEqual(contribute.directory_name(None, now),
                         'repository-2024-01-02-03-04-05')
        self.assertEqual(contribute.directory_name('https://x.co/u/.git', now),
                         'repository-2024-01-02-03-04-05')
        self.assertEqual(contribute.directory_name('git@x:u/r.git', now),
                         'r')


class PlanTests(unittest.TestCase):
    START = date(2024, 1, 1)  # A Monday.
    END = date(2024, 3, 31)

    def plan(self, frequency=100, min_commits=1, max_commits=10,
             no_weekends=False, seed=1):
        return contribute.plan_commits(self.START, self.END, frequency,
                                       min_commits, max_commits,
                                       no_weekends, random.Random(seed))

    def per_day(self, commits):
        counts = {}
        for commit in commits:
            counts[commit.date()] = counts.get(commit.date(), 0) + 1
        return counts

    def test_frequency_100_commits_every_day(self):
        days = (self.END - self.START).days + 1
        self.assertEqual(len(self.per_day(self.plan())), days)

    def test_frequency_0_makes_no_commits(self):
        self.assertEqual(self.plan(frequency=0), [])

    def test_frequency_is_roughly_respected(self):
        days = len(self.per_day(self.plan(frequency=50, seed=7)))
        self.assertTrue(25 <= days <= 66, days)

    def test_no_weekends(self):
        days = self.per_day(self.plan(no_weekends=True))
        self.assertTrue(days)
        self.assertTrue(all(day.weekday() < 5 for day in days))

    def test_commits_per_day_between_min_and_max(self):
        counts = self.per_day(self.plan(min_commits=3, max_commits=5))
        self.assertEqual(set(counts.values()), {3, 4, 5})
        counts = self.per_day(self.plan(min_commits=20, max_commits=20))
        self.assertEqual(set(counts.values()), {20})

    def test_commits_are_sorted_unique_and_same_day_in_utc(self):
        commits = self.plan(min_commits=20, max_commits=20)
        self.assertEqual(commits, sorted(set(commits)))
        for commit in commits:
            self.assertIsNotNone(commit.tzinfo)
            self.assertEqual(commit.astimezone(timezone.utc).date(),
                             commit.date())

    @unittest.skipUnless(hasattr(time, 'tzset'), 'needs time.tzset()')
    def test_time_zones(self):
        # GitHub places commits by their UTC date. Commits made in the
        # evening west of UTC (or the morning far east of it) used to land
        # on the next (or previous) day, even on weekends with -nw.
        zones = ['America/New_York', 'America/Los_Angeles', 'Asia/Kolkata',
                 'Asia/Kathmandu', 'Pacific/Kiritimati', 'Etc/GMT+12',
                 'Australia/Lord_Howe', 'UTC']
        old = os.environ.get('TZ')
        self.addCleanup(time.tzset)
        if old is None:
            self.addCleanup(os.environ.pop, 'TZ', None)
        else:
            self.addCleanup(os.environ.__setitem__, 'TZ', old)
        for zone in zones:
            os.environ['TZ'] = zone
            time.tzset()
            with self.subTest(zone=zone):
                commits = self.plan(min_commits=20, max_commits=20,
                                    no_weekends=True)
                self.assertTrue(commits)
                for commit in commits:
                    utc_day = commit.astimezone(timezone.utc).date()
                    self.assertEqual(utc_day, commit.date())
                    self.assertLess(utc_day.weekday(), 5)


class FastImportTests(unittest.TestCase):

    def test_commit_format(self):
        when = datetime(2024, 3, 5, 14, 7, 9,
                        tzinfo=timezone(timedelta(hours=-5)))
        stream = contribute.fast_import_commit(when, 'José', 'j@x.com',
                                               'refs/heads/main^0')
        lines = stream.decode('utf-8').split('\n')
        stamp = '%d -0500' % when.timestamp()
        self.assertEqual(lines[0], 'commit refs/heads/main')
        self.assertEqual(lines[1], 'author José <j@x.com> ' + stamp)
        self.assertEqual(lines[2], 'committer José <j@x.com> ' + stamp)
        self.assertEqual(lines[3], 'data 30')
        self.assertEqual(lines[4], 'Contribution: 2024-03-05 14:07')
        self.assertEqual(lines[5], 'from refs/heads/main^0')
        self.assertEqual(lines[6], 'M 100644 inline README.md')
        self.assertEqual(lines[7], 'data 34')
        self.assertEqual(lines[8], 'Contribution: 2024-03-05 14:07:09')

    def test_commit_without_parent(self):
        when = datetime(2024, 3, 5, 14, 7, 9, tzinfo=timezone.utc)
        stream = contribute.fast_import_commit(when, 'A', 'a@b.c')
        self.assertNotIn(b'\nfrom ', stream)


class EndToEndTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(remove_tree, self.root)
        # Ignore the git settings of the computer the tests run on.
        config = os.path.join(self.root, 'gitconfig')
        open(config, 'w').close()
        environment = mock.patch.dict(os.environ, {
            'GIT_CONFIG_GLOBAL': config,
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_TERMINAL_PROMPT': '0',
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.work = os.path.join(self.root, 'work')
        os.mkdir(self.work)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.work)

    def run_script(self, *argv):
        """Run the script and return how many commits it said it made."""
        output = io.StringIO()
        with redirect_stdout(output):
            contribute.main(list(argv))
        made = re.search(r'Making (\d+) commits', output.getvalue())
        return int(made.group(1))

    def assert_fails(self, message, *argv):
        with redirect_stdout(io.StringIO()), \
                self.assertRaises(SystemExit) as raised:
            contribute.main(list(argv))
        self.assertIn(message, str(raised.exception.code))

    def make_remote(self, name='remote'):
        path = os.path.join(self.root, name, 'remote.git')
        os.makedirs(path)
        git('init', '--quiet', '--bare', path)
        return path

    def count(self, repository, ref='HEAD'):
        return int(git('rev-list', '--count', ref, cwd=repository))

    def test_creates_repository_without_remote(self):
        made = self.run_script('-db=20', '-da=5', '-fr=90', '-mc=12',
                               '-nw', *IDENTITY)
        [folder] = os.listdir(self.work)
        self.assertTrue(folder.startswith('repository-'))
        self.assertEqual(self.count(folder), made)
        self.assertEqual(git('status', '--porcelain', cwd=folder), '')
        self.assertEqual(git('symbolic-ref', '--short', 'HEAD', cwd=folder),
                         'main')
        self.assertEqual(git('config', contribute.MARKER, cwd=folder),
                         'true')
        self.assertEqual(git('config', 'user.email', cwd=folder), EMAIL)
        log = git('log', '--format=%an|%ae|%cn|%ce|%at|%ct|%s', cwd=folder)
        for line in log.splitlines():
            name, email, cname, cemail, authored, committed, subject = \
                line.split('|')
            self.assertEqual((name, email, cname, cemail),
                             (NAME, EMAIL, NAME, EMAIL))
            self.assertEqual(authored, committed)
            self.assertRegex(subject,
                             r'^Contribution: \d{4}-\d\d-\d\d \d\d:\d\d$')
        with open(os.path.join(folder, 'README.md')) as file:
            self.assertTrue(file.read().startswith('Contribution: '))

    def test_uses_git_config_identity(self):
        with mock.patch.dict(os.environ, {'GIT_AUTHOR_NAME': 'From Env',
                                          'GIT_AUTHOR_EMAIL': 'env@x.com'}):
            self.run_script(*FEW_DAYS)
        [folder] = os.listdir(self.work)
        self.assertEqual(git('log', '-1', '--format=%an <%ae>', cwd=folder),
                         'From Env <env@x.com>')

    def test_missing_identity(self):
        with mock.patch('contribute.git_output', return_value=''):
            self.assert_fails('git does not know your name and email')
        self.assertEqual(os.listdir(self.work), [])

    def test_invalid_email(self):
        self.assert_fails('is not an email address',
                          '--user_name=A', '--user_email=nope')

    def test_git_not_installed(self):
        with mock.patch('shutil.which', return_value=None):
            self.assert_fails('Git is not installed', *IDENTITY)

    def test_no_commits_planned(self):
        self.assert_fails('produce no commits', '-fr=0', *IDENTITY)
        self.assertEqual(os.listdir(self.work), [])

    def test_pushes_and_adds_commits_on_rerun(self):
        remote = self.make_remote()
        first = self.run_script('-r', remote, '-db=10', '-fr=100',
                                *IDENTITY)
        self.assertEqual(os.listdir(self.work), ['remote'])
        self.assertEqual(self.count(remote, 'main'), first)
        # Running again for the same repository adds more commits on top
        # instead of failing because the folder already exists.
        second = self.run_script('-r', remote, '-db=10', '-fr=100',
                                 *IDENTITY)
        self.assertEqual(self.count(remote, 'main'), first + second)
        self.assertEqual(git('rev-parse', 'HEAD', cwd='remote'),
                         git('rev-parse', 'main', cwd=remote))

    def test_rejects_remote_with_commits(self):
        remote = self.make_remote()
        self.run_script('-r', remote, *FEW_DAYS, *IDENTITY)
        os.mkdir('elsewhere')
        os.chdir('elsewhere')
        self.assert_fails('already has commits', '-r', remote, *IDENTITY)
        self.assertEqual(os.listdir('.'), [])

    def test_rejects_unreachable_remote(self):
        missing = os.path.join(self.root, 'missing', 'remote.git')
        self.assert_fails('could not connect', '-r', missing, *IDENTITY)
        self.assertEqual(os.listdir(self.work), [])

    def test_does_not_touch_other_folders(self):
        remote = self.make_remote()
        os.mkdir('remote')
        with open(os.path.join('remote', 'notes.txt'), 'w') as file:
            file.write('mine')
        self.assert_fails('was not created by this script',
                          '-r', remote, *IDENTITY)
        self.assertEqual(os.listdir('remote'), ['notes.txt'])

    def test_stops_on_uncommitted_changes(self):
        remote = self.make_remote()
        self.run_script('-r', remote, *FEW_DAYS, *IDENTITY)
        with open(os.path.join('remote', 'README.md'), 'a') as file:
            file.write('edit')
        self.assert_fails('uncommitted changes', '-r', remote, *IDENTITY)

    def test_stops_when_previous_run_was_not_pushed(self):
        remote = self.make_remote()
        self.run_script('-r', remote, *FEW_DAYS, *IDENTITY)
        # Replace the remote with an empty one, as if the push had failed.
        remove_tree(remote)
        git('init', '--quiet', '--bare', remote)
        self.assert_fails('were never pushed', '-r', remote, *IDENTITY)
        self.assertEqual(self.count(remote, '--all'), 0)

    def test_stops_when_some_commits_were_not_pushed(self):
        remote = self.make_remote()
        self.run_script('-r', remote, *FEW_DAYS, *IDENTITY)
        git('commit', '--quiet', '--allow-empty', '-m', 'extra', cwd='remote')
        self.assert_fails('were never pushed', '-r', remote, *IDENTITY)

    def test_stops_when_remote_has_other_commits(self):
        remote = self.make_remote()
        self.run_script('-r', remote, *FEW_DAYS, *IDENTITY)
        clone = os.path.join(self.root, 'clone')
        git('clone', '--quiet', '--branch', 'main', remote, clone)
        git('commit', '--quiet', '--allow-empty', '-m', 'other', cwd=clone)
        git('push', '--quiet', 'origin', 'main', cwd=clone)
        self.assert_fails('does not have', '-r', remote, *IDENTITY)

    def test_stops_when_folder_belongs_to_another_remote(self):
        remote = self.make_remote('first')
        other = self.make_remote('second')
        self.run_script('-r', remote, *FEW_DAYS, *IDENTITY)
        self.assert_fails('remote set-url', '-r', other, *IDENTITY)

    def test_reuses_repository_from_older_version(self):
        # Older versions made the same kind of repository, without the
        # marker in the git config.
        remote = self.make_remote()
        git('init', '--quiet', 'remote')
        with open(os.path.join('remote', 'README.md'), 'w') as file:
            file.write('Contribution: 2020-01-01 20:00\n\n')
        git('add', 'README.md', cwd='remote')
        git('commit', '--quiet', '-m', 'Contribution: 2020-01-01 20:00',
            cwd='remote')
        git('branch', '-M', 'main', cwd='remote')
        git('remote', 'add', 'origin', remote, cwd='remote')
        git('push', '--quiet', '-u', 'origin', 'main', cwd='remote')
        made = self.run_script('-r', remote, *FEW_DAYS, *IDENTITY)
        self.assertEqual(self.count(remote, 'main'), made + 1)

    @unittest.skipIf(os.name == 'nt', 'uses a shell script as a git hook')
    def test_explains_failed_push(self):
        remote = self.make_remote()
        hook = os.path.join(remote, 'hooks', 'pre-receive')
        with open(hook, 'w') as file:
            file.write('#!/bin/sh\nexit 1\n')
        os.chmod(hook, 0o755)
        self.assert_fails('git -C remote push -u origin main',
                          '-r', remote, *FEW_DAYS, *IDENTITY)
        self.assertTrue(self.count('remote') > 0)


if __name__ == '__main__':
    unittest.main()
