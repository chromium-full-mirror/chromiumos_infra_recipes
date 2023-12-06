# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Success workflow tests for the signing recipe module."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_debug',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.cros_debug.patch_chromite_head(5095955, 1)


def GenTests(api):

  yield api.test(
      'basic',
      api.post_process(
          post_process.StepCommandContains, 'fetch crrev.com/c/5095955', [
              'git', 'fetch',
              'https://chromium.googlesource.com/chromiumos/chromite',
              'refs/changes/55/5095955/1'
          ]),
      api.post_process(post_process.MustRun, 'checkout crrev.com/c/5095955'),
      api.post_process(post_process.DropExpectation),
  )
