# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'gerrit',
]



def RunSteps(api):
  gerrit_change = GerritChange(
      host='chromium-review.googlesource.com',
      project='project',
      change=123,
  )

  # No easy way to test this. Just call the function.
  api.gerrit.set_change_description(gerrit_change, 'my new desc',
                                    amend_local=True)
  api.gerrit.set_change_description_remote(gerrit_change, 'my new desc')


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(
          post_process.StepCommandContains,
          'set CL 123 description (2).curl https://chromium-review.googlesource.com/changes/123/message',
          [
              '-d', '{"message": "my new desc"}',
              'https://chromium-review.googlesource.com/changes/123/message'
          ]))
