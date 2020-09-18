# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import git_cl


def CommonChecks(input_api, output_api):
  results = []

  # recipes.py test run
  results += input_api.RunTests([
      input_api.Command(
          name='recipes test',
          cmd=[input_api.python_executable, 'recipes.py', 'test', 'run'],
          kwargs={},
          message=output_api.PresubmitError,
      )
  ])

  # Python formatting issues are errors, but we need to ignore recipes.py, which
  # we do not control.
  bad_format = False
  cmd = [
      '-C',
      input_api.change.RepositoryRoot(), 'cl', 'format', '--dry-run',
      '--presubmit', '--python', '--no-clang-format', '--diff'
  ]
  code, out = git_cl.RunGitWithCode(cmd, suppress_stderr=True)
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
