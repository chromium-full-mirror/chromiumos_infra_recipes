# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""An example for mirror_prod_refs_to_latest."""

from recipe_engine import post_process


DEPS = [
    'gobin',
]


def RunSteps(api):
  api.gobin.mirror_prod_refs_to_latest()


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(
          post_process.StepCommandContains,
          r'mirror prod to latest for setup_project.cipd set-ref chromiumos/infra/setup_project/${platform}',
          [
              'cipd',
              'set-ref',
              'chromiumos/infra/setup_project/${platform}',
              '-version',
              'latest',
              '-ref',
              'prod',
          ]),
      api.post_process(post_process.DropExpectation),
  )
