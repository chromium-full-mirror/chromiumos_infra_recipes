# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import git_cl


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
      if not (' recipes.py\t' in line or
              ' recipes_release/protos/recipes_autoreleaser.py\t' in line):
        bad_format = True
        break

  if bad_format:
    return input_api.canned_checks.CheckPatchFormatted(
        input_api, output_api, check_python=True, check_clang_format=False,
        result_factory=output_api.PresubmitError)
  return []


def DocCheck(input_api, output_api):
  """Check that the documentation markdown file is up to date.

  Args:
    input_api: the input api
    output_api: the output api

  Returns:
    A test instance wrapping an invocation to `$PYTHON3 recipes.py doc --check`.
  """
  # If you are reading the code and got to this region in this file, then
  # you forgot to regenerate the docs.
  #
  # For additional context, see:
  #  - b/286419420
  #  - https://chromium-review.googlesource.com/c/infra/luci/recipes-py/+/4575394
  #  - https://chromium-review.googlesource.com/c/chromiumos/infra/recipes/+/4575982
  #
  return input_api.RunTests([
      input_api.Command(
          name='recipe doc check',
          cmd=[input_api.python3_executable, 'recipes.py', 'doc', '--check'],
          kwargs={},
          message=output_api.PresubmitError,
      ),
  ])


def ReleaseScriptUnitTestsCheck(input_api, output_api):
  """Run ./recipes_release/bin/run_tests."""
  return input_api.RunTests([
      input_api.Command(
          name='recipes_release/bin/run_tests',
          cmd=['./recipes_release/bin/run_tests'],
          kwargs={},
          message=output_api.PresubmitError,
      )
  ])


def CommitChecks(input_api, output_api):
  file_filter = lambda x: x.LocalPath() == 'infra/config/recipes.cfg'
  results = input_api.canned_checks.CheckJsonParses(input_api, output_api,
                                                    file_filter=file_filter)

  # recipes.py test run
  results += input_api.RunTests([
      input_api.Command(
          name='recipes test',
          cmd=[input_api.python3_executable, 'recipes.py', 'test', 'run'],
          kwargs={},
          message=output_api.PresubmitError,
      )
  ])
  # Python formatting issues are errors, but we need to ignore recipes.py, which
  # we do not control.
  results += FormatCheck(input_api, output_api)
  results += ReleaseScriptUnitTestsCheck(input_api, output_api)
  return results


def UploadChecks(input_api, output_api):
  file_filter = lambda x: x.LocalPath() == 'infra/config/recipes.cfg'
  results = input_api.canned_checks.CheckJsonParses(input_api, output_api,
                                                    file_filter=file_filter)
  # Python formatting issues are errors, but we need to ignore recipes.py, which
  # we do not control.
  results += FormatCheck(input_api, output_api)
  results += DocCheck(input_api, output_api)
  results += ReleaseScriptUnitTestsCheck(input_api, output_api)
  return results


CheckChangeOnUpload = UploadChecks
CheckChangeOnCommit = CommitChecks
