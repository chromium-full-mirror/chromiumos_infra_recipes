# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'gcloud',
]



def RunSteps(api):
  api.gcloud.storage_ls('gs://my-bucket/fake-dlc/dlc.img')


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(
          post_process.StepCommandContains, 'gcloud storage ls',
          ['gcloud', 'storage', 'ls', 'gs://my-bucket/fake-dlc/dlc.img']),
      api.post_process(post_process.DropExpectation),
  )
