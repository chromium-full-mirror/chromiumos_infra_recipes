# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'repo',
    'recipe_engine/context',
    'recipe_engine/path',
]


def RunSteps(api):
  with api.context(cwd=api.path['cleanup']):
    api.repo.init(
        'https://chromium.googlesource.com/chromiumos/manifest',
        local_manifest=api.repo.LocalManifest(
            repo='https://chrome-internal.googlesource.com/chromeos/project/galaxy/milkyway',
            path='local_manifest.xml',
        ),
    )


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('fetch master:local_manifest.xml', retcode=1),
      api.post_process(
          post_process.StepCommandContains,
          'fetch main:local_manifest.xml',
          [
              '--url',
              'https://chrome-internal.googlesource.com/chromeos/project/galaxy/milkyway/+/main/local_manifest.xml',
          ],
      ),
  )
