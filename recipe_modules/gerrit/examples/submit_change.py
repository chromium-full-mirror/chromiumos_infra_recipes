# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from recipe_engine import post_process

DEPS = [
    'recipe_engine/raw_io',
    'gerrit',
]


ALREADY_MERGED_STDERR = '''
[W2023-04-14 08:55:56,903 21912 140092904916864 gerrit_util.py] A transient error occurred while querying chrome-internal-review.googlesource.com:
POST https://chrome-internal-review.googlesource.com/a/changes/chromeos%2Fmanifest-versions~5752695/submit HTTP/1.1
HTTP/1.1 409 Conflict
change is merged
...
  File "/b/s/w/ir/kitchen-checkout/depot_tools/gerrit_util.py", line 504, in ReadHttpJsonResponse
    fh = ReadHttpResponse(conn, accept_statuses)
  File "/b/s/w/ir/kitchen-checkout/depot_tools/gerrit_util.py", line 499, in ReadHttpResponse
    raise GerritError(response.status, reason)
gerrit_util.GerritError: (409) Conflict: change is merged

'''


def RunSteps(api):
  gerrit_change = GerritChange(
      host='chromium-review.googlesource.com',
      project='project',
      change=123,
  )

  # Difficult to assert on, so just call the function.
  api.gerrit.submit_change(gerrit_change, retries=1)


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'already-merged',
      api.step_data('submit CL 123.git_cl land', retcode=1,
                    stderr=api.raw_io.output_text(ALREADY_MERGED_STDERR)),
  )

  yield api.test(
      'retry-succeed', api.step_data('submit CL 123.git_cl land', retcode=1),
      api.post_check(post_process.MustRun, 'submit CL 123.git_cl land (2)'))

  yield api.test(
      'retry-fail',
      api.step_data('submit CL 123.git_cl land', retcode=1),
      api.step_data('submit CL 123.git_cl land (2)', retcode=1),
      api.post_check(post_process.StepFailure, 'submit CL 123'),
      status='FAILURE',
  )
