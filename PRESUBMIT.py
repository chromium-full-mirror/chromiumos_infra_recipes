# Copyright 2019 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import git_cl
from subprocess2 import CalledProcessError

UNLINTABLE_FILES = set(['recipes.py'])


def PylintCheck(input_api, output_api):
  """Run pylint checks for modified files."""

  pylint_errors = []

  # Find pylint (currently v2.7).
  canned_checks_path = input_api.canned_checks.__file__
  canned_checks_path = input_api.os_path.abspath(canned_checks_path)
  depot_tools_path = input_api.os_path.dirname(canned_checks_path)
  pylint_path = input_api.os_path.join(depot_tools_path, 'pylint-2.7')

  for affected in input_api.AffectedFiles(include_deletes=False):
    affected_str = str(affected)
    if affected_str.endswith(".py"):
      if affected_str in UNLINTABLE_FILES:
        continue
      try:
        input_api.subprocess.check_output(
            [pylint_path, '--rcfile', 'pylintrc',
             '%s' % (affected_str)])
      except CalledProcessError as error:
        pylint_errors.append("%s" % error)
  if pylint_errors:
    pylint_errors = [
        output_api.PresubmitError((
            'Please fix pylint errors or add \'#pylint: disable=your-error\' in the source code '
            'at the end of the relevant line:\n\n%s') %
                                  "\n".join(pylint_errors))
    ]
  return pylint_errors


def FormatCheck(input_api, output_api):
  bad_format = False
  cmd = [
      '-C',
      input_api.change.RepositoryRoot(), 'cl', 'format', '--dry-run',
      '--presubmit', '--python', '--no-clang-format', '--diff'
  ]
  _, out = git_cl.RunGitWithCode(cmd, suppress_stderr=True)
  for line in out.splitlines():
    if line.startswith('--- ') or line.startswith('+++ '):
      if not ' recipes.py\t' in line:
        bad_format = True
        break

  if bad_format:
    return input_api.canned_checks.CheckPatchFormatted(
        input_api, output_api, check_python=True, check_clang_format=False,
        result_factory=output_api.PresubmitError)
  return None


def CommitChecks(input_api, output_api):
  file_filter = lambda x: x.LocalPath() == 'infra/config/recipes.cfg'
  results = input_api.canned_checks.CheckJsonParses(input_api, output_api,
                                                    file_filter=file_filter)

  # recipes.py test run
  results += input_api.RunTests([
      input_api.Command(
          name='recipes test',
          cmd=[input_api.python_executable, 'recipes.py', 'test', 'run'],
          kwargs={},
          message=output_api.PresubmitError,
      )
  ])
  results += PylintCheck(input_api, output_api)
  # Python formatting issues are errors, but we need to ignore recipes.py, which
  # we do not control.
  fmt_results = FormatCheck(input_api, output_api)
  if fmt_results:
    results += fmt_results
  return results


def UploadChecks(input_api, output_api):
  file_filter = lambda x: x.LocalPath() == 'infra/config/recipes.cfg'
  results = input_api.canned_checks.CheckJsonParses(input_api, output_api,
                                                    file_filter=file_filter)
  results += PylintCheck(input_api, output_api)
  # Python formatting issues are errors, but we need to ignore recipes.py, which
  # we do not control.
  fmt_results = FormatCheck(input_api, output_api)
  if fmt_results:
    results += fmt_results
  return results


CheckChangeOnUpload = UploadChecks
CheckChangeOnCommit = CommitChecks
