# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cros_source',
    'src_state',
]

from recipe_engine import post_process

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  _ = api.cros_source.uprev_packages(api.src_state.workspace_path)


# add post checks
def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(post_process.MustRun, 'uprev ebuilds'),
      api.post_check(
          post_process.MustRun,
          ('uprev ebuilds.call chromite.api.PackageService/Uprev.write '
           'input file')),
      api.post_check(
          post_process.MustRun,
          ('uprev ebuilds.call chromite.api.PackageService/Uprev.call '
           'build API script')),
  )
