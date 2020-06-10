# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


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

  # Python formatting issues are errors.
  results += input_api.canned_checks.CheckPatchFormatted(
      input_api, output_api, check_python=True, check_clang_format=False,
      result_factory=output_api.PresubmitError)

  return results


CheckChangeOnUpload = CommonChecks
CheckChangeOnCommit = CommonChecks
