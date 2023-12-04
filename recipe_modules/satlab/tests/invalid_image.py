# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.post_process import DropExpectation, DoesNotRun

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'satlab',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.satlab.stage_build("bad", "my-bucket")


def GenTests(api):
  yield api.test(
      'bad image fails', api.expect_exception("ValueError"),
      api.post_process(DoesNotRun, 'get access token for default account'),
      api.post_process(DoesNotRun, 'write headers'),
      api.post_process(DoesNotRun, 'stage build request'),
      api.post_process(DropExpectation), status='FAILURE')
