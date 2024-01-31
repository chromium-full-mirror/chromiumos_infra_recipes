# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'cros_source',
    'src_state',
]



def RunSteps(api):
  api.cros_source.uprev_packages(workspace_path=api.src_state.workspace_path)


# add post checks
def GenTests(api):
  yield api.test(
      'basic', api.post_check(post_process.MustRun, 'uprev packages'),
      api.post_check(
          post_process.MustRun,
          ('uprev packages.call chromite.api.PackageService/Uprev.write '
           'input file')),
      api.post_check(
          post_process.MustRun,
          ('uprev packages.call chromite.api.PackageService/Uprev.call '
           'build API script')), api.post_process(post_process.DropExpectation))
