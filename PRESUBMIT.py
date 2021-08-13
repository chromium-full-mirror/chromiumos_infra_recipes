# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import git_cl
from subprocess2 import CalledProcessError


def PylintCheck(input_api, output_api):
  """Run pylint checks for modified files."""
  pylint_errors = []
  for affected in input_api.AffectedFiles():
    if str(affected).endswith(".py"):
      try:
        input_api.subprocess.check_output(
            ['pylint', '--rcfile', 'pylintrc',
             '%s' % (affected)])
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


def CommonChecks(input_api, output_api):
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
    results += input_api.canned_checks.CheckPatchFormatted(
        input_api, output_api, check_python=True, check_clang_format=False,
        result_factory=output_api.PresubmitError)

  return results


CheckChangeOnUpload = CommonChecks
CheckChangeOnCommit = CommonChecks
